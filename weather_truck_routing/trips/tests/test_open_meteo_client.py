from datetime import datetime, timezone

import httpx
import pytest

from trips.clients.open_meteo import OpenMeteoClient
from trips.exceptions import ProviderResponseError
from trips.services.checkpoints import Coordinate


TIMES = [1_797_246_000, 1_797_249_600]


def forecast_payload(lat, lng, *, rain=None, showers=None):
    return {
        "latitude": lat,
        "longitude": lng,
        "elevation": 180.0,
        "hourly": {
            "time": TIMES,
            "wind_speed_10m": [20.0, 35.0],
            "wind_gusts_10m": [25.0, 42.0],
            "rain": rain if rain is not None else [0.1, 0.2],
            "showers": showers if showers is not None else [0.05, 0.0],
            "snowfall": [0.0, 0.5],
        },
    }


def mock_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_multiple_coordinate_forecasts_are_normalized_and_unit_safe():
    def handler(request):
        params = request.url.params
        assert params["latitude"] == "41.000000,42.000000"
        assert params["longitude"] == "-87.000000,-83.000000"
        assert params["wind_speed_unit"] == "mph"
        assert params["precipitation_unit"] == "inch"
        assert params["timezone"] == "GMT"
        assert params["timeformat"] == "unixtime"
        assert params["start_hour"] == "2026-12-14T10:00"
        assert params["end_hour"] == "2026-12-14T13:00"
        return httpx.Response(
            200,
            json=[
                forecast_payload(41.0, -87.0),
                forecast_payload(42.0, -83.0),
            ],
        )

    client = OpenMeteoClient(
        http_client=mock_client(handler),
        max_retries=0,
    )
    coordinates = [Coordinate(41.0, -87.0), Coordinate(42.0, -83.0)]

    result = client.forecasts(
        coordinates,
        datetime(2026, 12, 14, 10, 15, tzinfo=timezone.utc),
        datetime(2026, 12, 14, 12, 5, tzinfo=timezone.utc),
    )

    assert len(result) == 2
    assert result[0].requested_coordinate == coordinates[0]
    assert result[0].provider_coordinate == Coordinate(41.0, -87.0)
    assert result[0].hourly[0].rain_in_per_hr == pytest.approx(0.15)
    assert result[0].hourly[1].snow_in_per_hr == 0.5
    assert result[0].hourly[0].time.tzinfo == timezone.utc


def test_single_coordinate_dictionary_response_is_supported():
    client = OpenMeteoClient(
        http_client=mock_client(
            lambda request: httpx.Response(
                200, json=forecast_payload(41.0, -87.0)
            )
        ),
        max_retries=0,
    )

    result = client.forecasts(
        [Coordinate(41.0, -87.0)],
        datetime(2026, 12, 14, 10, tzinfo=timezone.utc),
        datetime(2026, 12, 14, 11, tzinfo=timezone.utc),
    )

    assert len(result) == 1
    assert len(result[0].hourly) == 2


def test_missing_rain_component_produces_unknown_combined_rain():
    client = OpenMeteoClient(
        http_client=mock_client(
            lambda request: httpx.Response(
                200,
                json=forecast_payload(
                    41.0,
                    -87.0,
                    rain=[None, 0.2],
                    showers=[0.1, 0.0],
                ),
            )
        ),
        max_retries=0,
    )

    result = client.forecasts(
        [Coordinate(41.0, -87.0)],
        datetime(2026, 12, 14, 10, tzinfo=timezone.utc),
        datetime(2026, 12, 14, 11, tzinfo=timezone.utc),
    )

    assert result[0].hourly[0].rain_in_per_hr is None
    assert result[0].hourly[1].rain_in_per_hr == 0.2


def test_forecasts_are_split_into_configured_batches():
    requests = 0

    def handler(request):
        nonlocal requests
        requests += 1
        latitude = float(request.url.params["latitude"])
        longitude = float(request.url.params["longitude"])
        return httpx.Response(200, json=forecast_payload(latitude, longitude))

    client = OpenMeteoClient(
        http_client=mock_client(handler),
        max_retries=0,
        max_batch_size=1,
    )

    result = client.forecasts(
        [Coordinate(41.0, -87.0), Coordinate(42.0, -83.0)],
        datetime(2026, 12, 14, 10, tzinfo=timezone.utc),
        datetime(2026, 12, 14, 11, tzinfo=timezone.utc),
    )

    assert requests == 2
    assert len(result) == 2


def test_misaligned_hourly_arrays_are_rejected():
    payload = forecast_payload(41.0, -87.0)
    payload["hourly"]["snowfall"] = [0.0]
    client = OpenMeteoClient(
        http_client=mock_client(
            lambda request: httpx.Response(200, json=payload)
        ),
        max_retries=0,
    )

    with pytest.raises(ProviderResponseError, match="do not align"):
        client.forecasts(
            [Coordinate(41.0, -87.0)],
            datetime(2026, 12, 14, 10, tzinfo=timezone.utc),
            datetime(2026, 12, 14, 11, tzinfo=timezone.utc),
        )


def test_location_count_mismatch_is_rejected():
    client = OpenMeteoClient(
        http_client=mock_client(
            lambda request: httpx.Response(
                200, json=[forecast_payload(41.0, -87.0)]
            )
        ),
        max_retries=0,
    )

    with pytest.raises(ProviderResponseError, match="number of locations"):
        client.forecasts(
            [Coordinate(41.0, -87.0), Coordinate(42.0, -83.0)],
            datetime(2026, 12, 14, 10, tzinfo=timezone.utc),
            datetime(2026, 12, 14, 11, tzinfo=timezone.utc),
        )
