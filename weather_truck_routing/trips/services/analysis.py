from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Protocol, Sequence
from uuid import uuid4

from trips.clients.geoapify import GeoapifyClient
from trips.clients.models import GeocodedLocation, ProviderRoute
from trips.clients.open_meteo import HourlyWeather, LocationForecast, OpenMeteoClient
from trips.constants import RISK_SCORES, RiskLevel
from trips.exceptions import TripAnalysisError
from trips.services.checkpoints import (
    Checkpoint,
    Coordinate,
    TimingSpan,
    assign_checkpoint_etas,
    place_checkpoints,
)
from trips.services.recommendation import (
    RiskSample,
    RouteCandidate,
    calculate_risk_exposure,
    recommend_route,
)
from trips.services.risk import CheckpointRisk, classify_checkpoint

METERS_PER_MILE = 1_609.344
COORDINATE_CACHE_PRECISION = 5
HEATMAP_FORECAST_HOURS = 48


class RouteProvider(Protocol):
    def geocode(
        self, query: str, *, limit: int = 5
    ) -> tuple[GeocodedLocation, ...]: ...

    def truck_routes(
        self,
        origin: Coordinate,
        destination: Coordinate,
        departure_time: datetime,
        *,
        alternatives: int = 2,
    ) -> tuple[ProviderRoute, ...]: ...


class WeatherProvider(Protocol):
    def forecasts(
        self,
        coordinates: list[Coordinate] | tuple[Coordinate, ...],
        start_time: datetime,
        end_time: datetime,
    ) -> tuple[LocationForecast, ...]: ...


@dataclass(frozen=True)
class TripAnalysisInput:
    origin: str
    destination: str
    departure_time: datetime
    cargo_weight_lb: float
    checkpoint_interval_miles: int


@dataclass(frozen=True)
class PreparedRoute:
    route_id: str
    provider_order: int
    label: str | None
    coordinates: tuple[Coordinate, ...]
    distance_miles: float
    duration_seconds: float
    checkpoints: tuple[Checkpoint, ...]
    notices: tuple[str, ...]


@dataclass(frozen=True)
class AnalyzedCheckpoint:
    checkpoint: Checkpoint
    weather: HourlyWeather | None
    risk: CheckpointRisk
    hourly_forecast: tuple[HourlyWeather, ...]


class TripAnalysisService:
    def __init__(
        self,
        route_client: GeoapifyClient | RouteProvider,
        weather_client: OpenMeteoClient | WeatherProvider,
    ) -> None:
        self.route_client = route_client
        self.weather_client = weather_client

    def analyze(self, trip: TripAnalysisInput) -> dict:
        origin = self._resolve_location(trip.origin, "origin")
        destination = self._resolve_location(trip.destination, "destination")
        provider_routes = self.route_client.truck_routes(
            origin.coordinate,
            destination.coordinate,
            trip.departure_time,
            alternatives=2,
        )
        if not provider_routes:
            raise TripAnalysisError(
                "no_routes_found",
                "The routing provider could not find a truck route for this trip.",
            )

        warnings: list[dict[str, str]] = []
        usable_routes = []
        for provider_order, route in enumerate(provider_routes):
            if route.has_critical_notice:
                warnings.append(
                    {
                        "code": "route_excluded_critical_notice",
                        "message": f"Route {route.route_id} was excluded because the routing provider returned a critical notice.",
                    }
                )
                continue
            usable_routes.append(
                self._prepare_route(
                    route,
                    provider_order,
                    trip.departure_time,
                    trip.checkpoint_interval_miles,
                )
            )

        if not usable_routes:
            raise TripAnalysisError(
                "no_usable_routes",
                "All returned routes contained critical routing notices.",
            )
        if len(usable_routes) < 3:
            warnings.append(
                {
                    "code": "fewer_route_alternatives",
                    "message": f"Geoapify returned {len(usable_routes)} distinct usable route option(s); three are not always available.",
                }
            )

        forecasts = self._fetch_checkpoint_forecasts(usable_routes, trip.departure_time)
        analyzed_routes = []
        candidates = []
        for prepared in usable_routes:
            analyzed_checkpoints = self._analyze_checkpoints(
                prepared,
                forecasts,
                trip.cargo_weight_lb,
                trip.departure_time,
            )
            exposure = calculate_risk_exposure(
                [
                    RiskSample(
                        item.checkpoint.distance_miles,
                        item.risk.level,
                        item.risk.is_complete,
                    )
                    for item in analyzed_checkpoints
                ],
                prepared.distance_miles,
            )
            candidates.append(
                RouteCandidate(
                    route_id=prepared.route_id,
                    duration_seconds=prepared.duration_seconds,
                    exposure=exposure,
                    provider_order=prepared.provider_order,
                )
            )
            analyzed_routes.append((prepared, analyzed_checkpoints, exposure))

        recommendation = recommend_route(candidates)
        if any(not candidate.exposure.is_complete for candidate in candidates):
            warnings.append(
                {
                    "code": "incomplete_weather_data",
                    "message": "At least one route has incomplete weather data and was not eligible for recommendation.",
                }
            )

        return {
            "analysis_id": str(uuid4()),
            "status": "complete",
            "request": {
                "origin": trip.origin,
                "destination": trip.destination,
                "departure_time": self._isoformat(trip.departure_time),
                "cargo_weight_lb": trip.cargo_weight_lb,
                "checkpoint_interval_miles": trip.checkpoint_interval_miles,
            },
            "resolved_locations": {
                "origin": self._serialize_location(origin),
                "destination": self._serialize_location(destination),
            },
            "recommendation": {
                "status": recommendation.status,
                "route_id": recommendation.recommended_route_id,
                "ranked_route_ids": list(recommendation.ranked_route_ids),
                "reason": self._recommendation_reason(recommendation.status),
            },
            "routes": [
                self._serialize_route(
                    prepared,
                    checkpoints,
                    exposure,
                    recommendation.recommended_route_id,
                    trip.cargo_weight_lb,
                )
                for prepared, checkpoints, exposure in analyzed_routes
            ],
            "warnings": warnings,
            "forecast_window": {
                "start_time": self._isoformat(trip.departure_time),
                "end_time": self._isoformat(
                    trip.departure_time + timedelta(hours=HEATMAP_FORECAST_HOURS)
                ),
                "hours": HEATMAP_FORECAST_HOURS,
            },
            "attribution": {
                "routing": "Powered by Geoapify | © OpenStreetMap contributors",
                "weather": "Weather data by Open-Meteo.com",
            },
        }

    def _resolve_location(self, query: str, field: str) -> GeocodedLocation:
        matches = self.route_client.geocode(query, limit=1)
        if not matches:
            raise TripAnalysisError(
                "location_not_found",
                f"The {field} could not be resolved.",
                details={"field": field},
            )
        return matches[0]

    def _prepare_route(
        self,
        route: ProviderRoute,
        provider_order: int,
        departure_time: datetime,
        interval_miles: int,
    ) -> PreparedRoute:
        coordinates = self._join_section_coordinates(route)
        distance_miles = sum(
            section.length_meters for section in route.sections
        ) / METERS_PER_MILE
        duration_seconds = sum(section.duration_seconds for section in route.sections)
        if distance_miles <= 0:
            raise TripAnalysisError(
                "invalid_route",
                f"Route {route.route_id} has no measurable distance.",
                status_code=502,
            )

        checkpoints = place_checkpoints(
            coordinates,
            interval_miles,
            route_distance_miles=distance_miles,
        )
        timing_spans = self._build_timing_spans(route)
        timed_checkpoints = assign_checkpoint_etas(
            checkpoints, timing_spans, departure_time
        )
        notices = list(route.notices)
        for section in route.sections:
            notices.extend(section.notices)
        return PreparedRoute(
            route_id=route.route_id,
            provider_order=provider_order,
            label=route.label,
            coordinates=coordinates,
            distance_miles=distance_miles,
            duration_seconds=duration_seconds,
            checkpoints=tuple(timed_checkpoints),
            notices=tuple(dict.fromkeys(notices)),
        )

    @staticmethod
    def _join_section_coordinates(route: ProviderRoute) -> tuple[Coordinate, ...]:
        coordinates: list[Coordinate] = []
        for section in route.sections:
            section_coordinates = list(section.coordinates)
            if coordinates and section_coordinates[0] == coordinates[-1]:
                section_coordinates = section_coordinates[1:]
            coordinates.extend(section_coordinates)
        if len(coordinates) < 2:
            raise TripAnalysisError(
                "invalid_route_geometry",
                f"Route {route.route_id} has invalid geometry.",
                status_code=502,
            )
        return tuple(coordinates)

    @staticmethod
    def _build_timing_spans(route: ProviderRoute) -> list[TimingSpan]:
        timing_spans: list[TimingSpan] = []
        route_cursor = 0.0
        for section in route.sections:
            section_distance = section.length_meters / METERS_PER_MILE
            section_end = route_cursor + section_distance
            usable_spans = [span for span in section.spans if span.length_meters > 0]
            span_length_total = sum(span.length_meters for span in usable_spans)
            span_duration_total = sum(span.duration_seconds for span in usable_spans)

            if not usable_spans or span_length_total <= 0:
                timing_spans.append(
                    TimingSpan(route_cursor, section_end, section.duration_seconds)
                )
                route_cursor = section_end
                continue

            span_cursor = route_cursor
            duration_remaining = section.duration_seconds
            for index, span in enumerate(usable_spans):
                is_last = index == len(usable_spans) - 1
                distance_fraction = span.length_meters / span_length_total
                span_end = (
                    section_end
                    if is_last
                    else span_cursor + section_distance * distance_fraction
                )
                if span_duration_total > 0:
                    duration = (
                        duration_remaining
                        if is_last
                        else section.duration_seconds
                        * span.duration_seconds
                        / span_duration_total
                    )
                else:
                    duration = (
                        duration_remaining
                        if is_last
                        else section.duration_seconds * distance_fraction
                    )
                timing_spans.append(TimingSpan(span_cursor, span_end, duration))
                span_cursor = span_end
                duration_remaining -= duration
            route_cursor = section_end

        route_distance = sum(section.length_meters for section in route.sections) / METERS_PER_MILE
        if timing_spans:
            timing_spans[-1] = replace(
                timing_spans[-1], end_distance_miles=route_distance
            )
        return timing_spans

    def _fetch_checkpoint_forecasts(
        self,
        routes: Sequence[PreparedRoute],
        departure_time: datetime,
    ) -> dict[tuple[float, float], LocationForecast]:
        unique_coordinates: dict[tuple[float, float], Coordinate] = {}
        latest_eta = departure_time
        for route in routes:
            for checkpoint in route.checkpoints:
                key = self._coordinate_key(checkpoint.coordinate)
                unique_coordinates.setdefault(key, checkpoint.coordinate)
                if checkpoint.eta and checkpoint.eta > latest_eta:
                    latest_eta = checkpoint.eta

        coordinates = list(unique_coordinates.values())
        forecast_end_time = max(
            latest_eta,
            departure_time + timedelta(hours=HEATMAP_FORECAST_HOURS),
        )
        forecasts = self.weather_client.forecasts(
            coordinates,
            departure_time,
            forecast_end_time,
        )
        return {
            self._coordinate_key(forecast.requested_coordinate): forecast
            for forecast in forecasts
        }

    def _analyze_checkpoints(
        self,
        route: PreparedRoute,
        forecasts: dict[tuple[float, float], LocationForecast],
        cargo_weight_lb: float,
        departure_time: datetime,
    ) -> tuple[AnalyzedCheckpoint, ...]:
        results = []
        forecast_end_time = departure_time + timedelta(hours=HEATMAP_FORECAST_HOURS)
        for checkpoint in route.checkpoints:
            forecast = forecasts.get(self._coordinate_key(checkpoint.coordinate))
            weather = self._nearest_weather(forecast, checkpoint.eta)
            risk = classify_checkpoint(
                wind_mph=weather.wind_mph if weather else None,
                rain_in_per_hr=weather.rain_in_per_hr if weather else None,
                snow_in_per_hr=weather.snow_in_per_hr if weather else None,
                cargo_weight_lb=cargo_weight_lb,
            )
            hourly_forecast = tuple(
                hour
                for hour in (forecast.hourly if forecast else ())
                if departure_time - timedelta(hours=1)
                <= hour.time
                <= forecast_end_time + timedelta(hours=1)
            )
            results.append(
                AnalyzedCheckpoint(checkpoint, weather, risk, hourly_forecast)
            )
        return tuple(results)

    @staticmethod
    def _nearest_weather(
        forecast: LocationForecast | None, eta: datetime | None
    ) -> HourlyWeather | None:
        if forecast is None or eta is None or not forecast.hourly:
            return None
        nearest = min(
            forecast.hourly,
            key=lambda weather: abs((weather.time - eta).total_seconds()),
        )
        if abs((nearest.time - eta).total_seconds()) > 3_600:
            return None
        return nearest

    @staticmethod
    def _serialize_location(location: GeocodedLocation) -> dict:
        return {
            "provider_id": location.provider_id,
            "label": location.label,
            "lat": location.coordinate.lat,
            "lng": location.coordinate.lng,
            "result_type": location.result_type,
        }

    def _serialize_route(
        self,
        route: PreparedRoute,
        checkpoints: Sequence[AnalyzedCheckpoint],
        exposure,
        recommended_route_id: str | None,
        cargo_weight_lb: float,
    ) -> dict:
        return {
            "id": route.route_id,
            "label": route.label or f"Route {route.provider_order + 1}",
            "provider_order": route.provider_order,
            "is_recommended": route.route_id == recommended_route_id,
            "geometry": {
                "type": "LineString",
                "coordinates": [
                    [coordinate.lng, coordinate.lat]
                    for coordinate in route.coordinates
                ],
            },
            "summary": {
                "distance_miles": round(route.distance_miles, 3),
                "duration_seconds": round(route.duration_seconds),
                "severe_miles": round(
                    exposure.miles_for(RiskLevel.SEVERE), 3
                ),
                "high_miles": round(exposure.miles_for(RiskLevel.HIGH), 3),
                "no_travel_miles": round(
                    exposure.miles_for(RiskLevel.NO_TRAVEL), 3
                ),
                "unknown_miles": round(exposure.unknown_miles, 3),
                "average_risk": (
                    round(exposure.average_risk, 4)
                    if exposure.average_risk is not None
                    else None
                ),
                "contains_no_travel": exposure.contains_no_travel,
                "weather_complete": exposure.is_complete,
                "risk_miles": {
                    level.value: round(exposure.miles_for(level), 3)
                    for level in RISK_SCORES
                },
            },
            "checkpoints": [
                self._serialize_checkpoint(checkpoint, cargo_weight_lb)
                for checkpoint in checkpoints
            ],
            "notices": list(route.notices),
        }

    def _serialize_checkpoint(
        self, analyzed: AnalyzedCheckpoint, cargo_weight_lb: float
    ) -> dict:
        checkpoint = analyzed.checkpoint
        weather = analyzed.weather
        return {
            "sequence": checkpoint.sequence,
            "distance_miles": round(checkpoint.distance_miles, 3),
            "location": {
                "lat": checkpoint.coordinate.lat,
                "lng": checkpoint.coordinate.lng,
            },
            "elapsed_seconds": (
                round(checkpoint.elapsed_seconds)
                if checkpoint.elapsed_seconds is not None
                else None
            ),
            "eta": self._isoformat(checkpoint.eta),
            "forecast_time": self._isoformat(weather.time if weather else None),
            "weather": {
                "wind_mph": weather.wind_mph if weather else None,
                "wind_gust_mph": weather.wind_gust_mph if weather else None,
                "rain_in_per_hr": weather.rain_in_per_hr if weather else None,
                "snow_in_per_hr": weather.snow_in_per_hr if weather else None,
            },
            "risk": {
                "level": analyzed.risk.level.value,
                "score": analyzed.risk.score,
                "condition_levels": {
                    condition: level.value
                    for condition, level in analyzed.risk.condition_levels.items()
                },
                "drivers": list(analyzed.risk.drivers),
                "is_complete": analyzed.risk.is_complete,
            },
            "hourly_forecast": [
                self._serialize_forecast_hour(hour, cargo_weight_lb)
                for hour in analyzed.hourly_forecast
            ],
        }

    def _serialize_forecast_hour(
        self, weather: HourlyWeather, cargo_weight_lb: float
    ) -> dict:
        risk = classify_checkpoint(
            wind_mph=weather.wind_mph,
            rain_in_per_hr=weather.rain_in_per_hr,
            snow_in_per_hr=weather.snow_in_per_hr,
            cargo_weight_lb=cargo_weight_lb,
        )
        return {
            "time": self._isoformat(weather.time),
            "weather": {
                "wind_mph": weather.wind_mph,
                "wind_gust_mph": weather.wind_gust_mph,
                "rain_in_per_hr": weather.rain_in_per_hr,
                "snow_in_per_hr": weather.snow_in_per_hr,
            },
            "risk": {
                "level": risk.level.value,
                "score": risk.score,
                "is_complete": risk.is_complete,
            },
        }

    @staticmethod
    def _coordinate_key(coordinate: Coordinate) -> tuple[float, float]:
        return (
            round(coordinate.lat, COORDINATE_CACHE_PRECISION),
            round(coordinate.lng, COORDINATE_CACHE_PRECISION),
        )

    @staticmethod
    def _isoformat(value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.isoformat().replace("+00:00", "Z")

    @staticmethod
    def _recommendation_reason(status: str) -> str:
        if status == "recommended":
            return "Selected by fewest Severe miles, then fewest High miles, lowest average risk, and shortest travel time."
        if status == "no_safe_route":
            return "No route was recommended because every complete route contains No Travel conditions."
        return "No route was recommended because complete weather data was unavailable."
