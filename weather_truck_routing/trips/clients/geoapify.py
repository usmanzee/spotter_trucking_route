import math
from datetime import datetime
from typing import Any

import httpx

from trips.clients.base import JsonHttpClient
from trips.clients.models import (
    GeocodedLocation,
    ProviderRoute,
    RouteSection,
    RouteSpan,
)
from trips.exceptions import ProviderConfigurationError, ProviderResponseError
from trips.services.checkpoints import Coordinate

GEOAPIFY_PROVIDER = "Geoapify"
DEFAULT_GEOCODING_URL = "https://api.geoapify.com/v1/geocode/search"
DEFAULT_ROUTING_URL = "https://api.geoapify.com/v1/routing"
ROUTE_CANDIDATES = (
    ("balanced", "balanced", "Balanced route", None),
    ("short", "short", "Shortest distance", None),
    ("highway-light", "balanced", "Highway-light route", "highways:0.8"),
    ("less-maneuvers", "less_maneuvers", "Fewer maneuvers route", None),
    ("toll-conscious", "balanced", "Toll-conscious route", "tolls:0.9"),
)


class GeoapifyClient:
    def __init__(
        self,
        api_key: str,
        *,
        geocoding_url: str = DEFAULT_GEOCODING_URL,
        routing_url: str = DEFAULT_ROUTING_URL,
        http_client: httpx.Client | None = None,
        timeout_seconds: float = 10.0,
        max_retries: int = 1,
        sleeper=None,
    ) -> None:
        if not api_key.strip():
            raise ProviderConfigurationError(
                GEOAPIFY_PROVIDER,
                "GEOAPIFY_API_KEY is not configured.",
                code="provider_not_configured",
            )
        http_options: dict[str, Any] = {
            "http_client": http_client,
            "timeout_seconds": timeout_seconds,
            "max_retries": max_retries,
        }
        if sleeper is not None:
            http_options["sleeper"] = sleeper
        self.api_key = api_key.strip()
        self.geocoding_url = geocoding_url
        self.routing_url = routing_url
        self.http = JsonHttpClient(GEOAPIFY_PROVIDER, **http_options)

    def geocode(self, query: str, *, limit: int = 5) -> tuple[GeocodedLocation, ...]:
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("Geocoding query cannot be empty.")
        if not 1 <= limit <= 20:
            raise ValueError("Geocoding limit must be between 1 and 20.")

        payload = self.http.get_json(
            self.geocoding_url,
            {
                "text": normalized_query,
                "limit": limit,
                "format": "json",
                "apiKey": self.api_key,
            },
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            raise self._invalid_response("geocoding response is missing results")

        results = []
        for item in payload["results"]:
            if not isinstance(item, dict):
                raise self._invalid_response("geocoding result is invalid")
            try:
                coordinate = self._coordinate(item["lat"], item["lon"])
                label = str(item["formatted"])
                provider_id = str(
                    item.get("place_id")
                    or self._raw_place_id(item.get("datasource"))
                    or f"{coordinate.lat},{coordinate.lng}"
                )
                result_type = str(item.get("result_type", "unknown"))
            except (KeyError, TypeError, ValueError) as exc:
                raise self._invalid_response(
                    "geocoding result has invalid fields"
                ) from exc
            results.append(
                GeocodedLocation(
                    provider_id=provider_id,
                    label=label,
                    coordinate=coordinate,
                    result_type=result_type,
                )
            )
        return tuple(results)

    def truck_routes(
        self,
        origin: Coordinate,
        destination: Coordinate,
        departure_time: datetime,
        *,
        alternatives: int = 2,
    ) -> tuple[ProviderRoute, ...]:
        self._validate_coordinate(origin)
        self._validate_coordinate(destination)
        if departure_time.tzinfo is None or departure_time.utcoffset() is None:
            raise ValueError("Departure time must include a timezone offset.")
        if not 0 <= alternatives <= 2:
            raise ValueError("Geoapify alternatives must be between 0 and 2.")

        requested_count = alternatives + 1
        routes: list[ProviderRoute] = []
        signatures: set[tuple[tuple[float, float], ...]] = set()
        for candidate_id, route_type, label, avoid in ROUTE_CANDIDATES:
            params = {
                "waypoints": (
                    f"{origin.lat:.6f},{origin.lng:.6f}|"
                    f"{destination.lat:.6f},{destination.lng:.6f}"
                ),
                "mode": "heavy_truck",
                "type": route_type,
                "traffic": "approximated",
                "units": "metric",
                "format": "geojson",
                "lang": "en",
                "apiKey": self.api_key,
            }
            if avoid:
                params["avoid"] = avoid
            payload = self.http.get_json(
                self.routing_url,
                params,
            )
            features = self._extract_features(payload)
            for feature_index, feature in enumerate(features):
                route = self._parse_route(
                    feature,
                    candidate_id=candidate_id,
                    label=label,
                    feature_index=feature_index,
                )
                signature = self._route_signature(route)
                if signature in signatures:
                    continue
                signatures.add(signature)
                routes.append(route)
                if len(routes) == requested_count:
                    return tuple(routes)
        return tuple(routes)

    def _extract_features(self, payload: Any) -> list[dict]:
        if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
            raise self._invalid_response("routing response is missing features")
        return payload["features"]

    def _parse_route(
        self,
        feature: Any,
        *,
        candidate_id: str,
        label: str,
        feature_index: int,
    ) -> ProviderRoute:
        if not isinstance(feature, dict):
            raise self._invalid_response("route feature is invalid")
        geometry = feature.get("geometry")
        properties = feature.get("properties")
        if not isinstance(geometry, dict) or not isinstance(properties, dict):
            raise self._invalid_response("route feature is missing geometry or properties")

        raw_lines = geometry.get("coordinates")
        geometry_type = geometry.get("type")
        if geometry_type == "LineString":
            raw_lines = [raw_lines]
        elif geometry_type != "MultiLineString":
            raise self._invalid_response("route geometry type is unsupported")
        if not isinstance(raw_lines, list) or not raw_lines:
            raise self._invalid_response("route geometry has no coordinates")

        legs = properties.get("legs", [])
        if not isinstance(legs, list):
            raise self._invalid_response("route legs are invalid")
        try:
            total_length = self._positive_number(properties["distance"], "distance")
            total_duration = self._nonnegative_number(properties["time"], "time")
        except (KeyError, TypeError, ValueError) as exc:
            raise self._invalid_response("route summary fields are invalid") from exc

        if len(legs) == len(raw_lines) and legs:
            sections = tuple(
                self._parse_section(
                    line,
                    leg,
                    section_id=f"geoapify-{candidate_id}-{feature_index}-{index}",
                )
                for index, (line, leg) in enumerate(
                    zip(raw_lines, legs, strict=True)
                )
            )
        else:
            combined_line = self._combine_lines(raw_lines)
            combined_steps = []
            for leg in legs:
                if isinstance(leg, dict) and isinstance(leg.get("steps"), list):
                    combined_steps.extend(leg["steps"])
            sections = (
                self._section_from_values(
                    combined_line,
                    total_length,
                    total_duration,
                    combined_steps,
                    section_id=f"geoapify-{candidate_id}-{feature_index}-0",
                ),
            )

        return ProviderRoute(
            route_id=f"geoapify-{candidate_id}-{feature_index}",
            label=label,
            sections=sections,
        )

    def _parse_section(
        self, raw_line: Any, leg: Any, *, section_id: str
    ) -> RouteSection:
        if not isinstance(leg, dict):
            raise self._invalid_response("route leg is invalid")
        try:
            length = self._positive_number(leg["distance"], "leg distance")
            duration = self._nonnegative_number(leg["time"], "leg time")
        except (KeyError, TypeError, ValueError) as exc:
            raise self._invalid_response("route leg summary is invalid") from exc
        steps = leg.get("steps", [])
        if not isinstance(steps, list):
            raise self._invalid_response("route leg steps are invalid")
        return self._section_from_values(
            raw_line, length, duration, steps, section_id=section_id
        )

    def _section_from_values(
        self,
        raw_line: Any,
        length: float,
        duration: float,
        steps: list,
        *,
        section_id: str,
    ) -> RouteSection:
        coordinates = self._parse_line(raw_line)
        spans = []
        for step in steps:
            if not isinstance(step, dict):
                continue
            try:
                step_length = self._nonnegative_number(
                    step["distance"], "step distance"
                )
                step_duration = self._nonnegative_number(step["time"], "step time")
                offset = int(step.get("from_index", len(spans)))
            except (KeyError, TypeError, ValueError) as exc:
                raise self._invalid_response("route step is invalid") from exc
            if step_length > 0:
                spans.append(RouteSpan(offset, step_length, step_duration))
        return RouteSection(
            section_id=section_id,
            coordinates=coordinates,
            length_meters=length,
            duration_seconds=duration,
            spans=tuple(spans),
        )

    def _parse_line(self, raw_line: Any) -> tuple[Coordinate, ...]:
        if not isinstance(raw_line, list):
            raise self._invalid_response("route line is invalid")
        try:
            coordinates = tuple(
                self._coordinate(point[1], point[0])
                for point in raw_line
                if isinstance(point, list) and len(point) >= 2
            )
        except (TypeError, ValueError, IndexError) as exc:
            raise self._invalid_response("route coordinate is invalid") from exc
        if len(coordinates) < 2:
            raise self._invalid_response("route line has fewer than two coordinates")
        return coordinates

    @staticmethod
    def _combine_lines(raw_lines: list) -> list:
        combined = []
        for line in raw_lines:
            if not isinstance(line, list):
                continue
            if combined and line and combined[-1] == line[0]:
                combined.extend(line[1:])
            else:
                combined.extend(line)
        return combined

    @staticmethod
    def _route_signature(route: ProviderRoute) -> tuple[tuple[float, float], ...]:
        coordinates = []
        for section in route.sections:
            coordinates.extend(section.coordinates)
        if not coordinates:
            return ()
        sample_indexes = {0, len(coordinates) - 1}
        sample_indexes.update(
            round(index * (len(coordinates) - 1) / 8) for index in range(1, 8)
        )
        return tuple(
            (round(coordinates[index].lat, 4), round(coordinates[index].lng, 4))
            for index in sorted(sample_indexes)
        )

    @staticmethod
    def _positive_number(value: Any, name: str) -> float:
        number = GeoapifyClient._nonnegative_number(value, name)
        if number <= 0:
            raise ValueError(f"{name} must be positive")
        return number

    @staticmethod
    def _nonnegative_number(value: Any, name: str) -> float:
        number = float(value)
        if not math.isfinite(number) or number < 0:
            raise ValueError(f"{name} must be nonnegative")
        return number

    @classmethod
    def _coordinate(cls, lat: Any, lng: Any) -> Coordinate:
        coordinate = Coordinate(float(lat), float(lng))
        cls._validate_coordinate(coordinate)
        return coordinate

    @staticmethod
    def _validate_coordinate(coordinate: Coordinate) -> None:
        if not math.isfinite(coordinate.lat) or not -90 <= coordinate.lat <= 90:
            raise ValueError("Latitude must be between -90 and 90 degrees.")
        if not math.isfinite(coordinate.lng) or not -180 <= coordinate.lng <= 180:
            raise ValueError("Longitude must be between -180 and 180 degrees.")

    @staticmethod
    def _raw_place_id(datasource: Any) -> Any:
        if not isinstance(datasource, dict):
            return None
        raw = datasource.get("raw")
        return raw.get("place_id") if isinstance(raw, dict) else None

    @staticmethod
    def _invalid_response(detail: str) -> ProviderResponseError:
        return ProviderResponseError(
            GEOAPIFY_PROVIDER,
            f"Geoapify returned an invalid response: {detail}.",
            code="invalid_provider_response",
        )
