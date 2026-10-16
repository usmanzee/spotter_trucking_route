import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from trips.clients.base import JsonHttpClient
from trips.exceptions import ProviderResponseError
from trips.services.checkpoints import Coordinate

OPEN_METEO_PROVIDER = "Open-Meteo"
DEFAULT_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
HOURLY_VARIABLES = (
    "wind_speed_10m",
    "wind_gusts_10m",
    "rain",
    "showers",
    "snowfall",
)


@dataclass(frozen=True)
class HourlyWeather:
    time: datetime
    wind_mph: float | None
    wind_gust_mph: float | None
    rain_in_per_hr: float | None
    snow_in_per_hr: float | None


@dataclass(frozen=True)
class LocationForecast:
    requested_coordinate: Coordinate
    provider_coordinate: Coordinate
    elevation_meters: float | None
    hourly: tuple[HourlyWeather, ...]


class OpenMeteoClient:
    def __init__(
        self,
        *,
        api_key: str = "",
        forecast_url: str = DEFAULT_FORECAST_URL,
        http_client: httpx.Client | None = None,
        timeout_seconds: float = 10.0,
        max_retries: int = 1,
        max_batch_size: int = 50,
        sleeper=None,
    ) -> None:
        if max_batch_size < 1:
            raise ValueError("Weather batch size must be positive.")
        http_options: dict[str, Any] = {
            "http_client": http_client,
            "timeout_seconds": timeout_seconds,
            "max_retries": max_retries,
        }
        if sleeper is not None:
            http_options["sleeper"] = sleeper
        self.api_key = api_key.strip()
        self.forecast_url = forecast_url
        self.max_batch_size = max_batch_size
        self.http = JsonHttpClient(OPEN_METEO_PROVIDER, **http_options)

    def forecasts(
        self,
        coordinates: list[Coordinate] | tuple[Coordinate, ...],
        start_time: datetime,
        end_time: datetime,
    ) -> tuple[LocationForecast, ...]:
        if not coordinates:
            raise ValueError("At least one weather coordinate is required.")
        for coordinate in coordinates:
            self._validate_coordinate(coordinate)
        if start_time.tzinfo is None or start_time.utcoffset() is None:
            raise ValueError("Weather start time must include a timezone offset.")
        if end_time.tzinfo is None or end_time.utcoffset() is None:
            raise ValueError("Weather end time must include a timezone offset.")
        if end_time < start_time:
            raise ValueError("Weather end time cannot be before start time.")

        start_hour = self._floor_hour(start_time.astimezone(timezone.utc))
        end_hour = self._ceil_hour(end_time.astimezone(timezone.utc))
        results = []
        for start_index in range(0, len(coordinates), self.max_batch_size):
            batch = coordinates[start_index : start_index + self.max_batch_size]
            results.extend(self._request_batch(batch, start_hour, end_hour))
        return tuple(results)

    def _request_batch(
        self,
        coordinates: list[Coordinate] | tuple[Coordinate, ...],
        start_hour: datetime,
        end_hour: datetime,
    ) -> tuple[LocationForecast, ...]:
        params = {
            "latitude": ",".join(f"{point.lat:.6f}" for point in coordinates),
            "longitude": ",".join(f"{point.lng:.6f}" for point in coordinates),
            "hourly": ",".join(HOURLY_VARIABLES),
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",
            "timezone": "GMT",
            "timeformat": "unixtime",
            "start_hour": self._format_hour(start_hour),
            "end_hour": self._format_hour(end_hour),
        }
        if self.api_key:
            params["apikey"] = self.api_key

        payload = self.http.get_json(self.forecast_url, params)
        raw_forecasts = payload if isinstance(payload, list) else [payload]
        if len(raw_forecasts) != len(coordinates):
            raise self._invalid_response(
                "number of locations does not match the request"
            )
        return tuple(
            self._parse_forecast(raw, requested)
            for raw, requested in zip(raw_forecasts, coordinates, strict=True)
        )

    def _parse_forecast(
        self, payload: Any, requested_coordinate: Coordinate
    ) -> LocationForecast:
        if not isinstance(payload, dict) or not isinstance(payload.get("hourly"), dict):
            raise self._invalid_response("forecast is missing hourly data")
        hourly = payload["hourly"]
        times = hourly.get("time")
        if not isinstance(times, list) or not times:
            raise self._invalid_response("forecast is missing hourly timestamps")

        arrays: dict[str, list[Any]] = {}
        for variable in HOURLY_VARIABLES:
            values = hourly.get(variable)
            if not isinstance(values, list) or len(values) != len(times):
                raise self._invalid_response(
                    f"hourly {variable} values do not align with timestamps"
                )
            arrays[variable] = values

        try:
            provider_coordinate = self._coordinate(
                payload["latitude"], payload["longitude"]
            )
            elevation = self._optional_number(payload.get("elevation"))
            weather = tuple(
                self._parse_hour(index, timestamp, arrays)
                for index, timestamp in enumerate(times)
            )
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise self._invalid_response("forecast fields are invalid") from exc

        return LocationForecast(
            requested_coordinate=requested_coordinate,
            provider_coordinate=provider_coordinate,
            elevation_meters=elevation,
            hourly=weather,
        )

    def _parse_hour(
        self,
        index: int,
        timestamp: Any,
        arrays: dict[str, list[Any]],
    ) -> HourlyWeather:
        time = datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
        rain = self._optional_number(arrays["rain"][index])
        showers = self._optional_number(arrays["showers"][index])
        combined_rain = None if rain is None or showers is None else rain + showers
        return HourlyWeather(
            time=time,
            wind_mph=self._optional_number(arrays["wind_speed_10m"][index]),
            wind_gust_mph=self._optional_number(arrays["wind_gusts_10m"][index]),
            rain_in_per_hr=combined_rain,
            snow_in_per_hr=self._optional_number(arrays["snowfall"][index]),
        )

    @staticmethod
    def _floor_hour(value: datetime) -> datetime:
        return value.replace(minute=0, second=0, microsecond=0)

    @staticmethod
    def _ceil_hour(value: datetime) -> datetime:
        floored = OpenMeteoClient._floor_hour(value)
        return floored if value == floored else floored + timedelta(hours=1)

    @staticmethod
    def _format_hour(value: datetime) -> str:
        return value.strftime("%Y-%m-%dT%H:%M")

    @staticmethod
    def _optional_number(value: Any) -> float | None:
        if value is None:
            return None
        number = float(value)
        if not math.isfinite(number) or number < 0:
            raise ValueError("Weather values must be finite and nonnegative.")
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
    def _invalid_response(detail: str) -> ProviderResponseError:
        return ProviderResponseError(
            OPEN_METEO_PROVIDER,
            f"Open-Meteo returned an invalid response: {detail}.",
            code="invalid_provider_response",
        )
