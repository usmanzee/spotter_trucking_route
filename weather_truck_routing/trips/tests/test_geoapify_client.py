from datetime import datetime, timezone

import httpx
import pytest

from trips.clients.geoapify import GeoapifyClient
from trips.exceptions import (
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderRateLimitError,
    ProviderResponseError,
)
from trips.services.checkpoints import Coordinate


def mock_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def route_payload(route_profile="balanced", *, same_geometry=False):
    latitude_offset = 0 if same_geometry else {
        "balanced": 0,
        "short": 0.1,
        "highway-light": 0.2,
        "less_maneuvers": 0.2,
        "toll-conscious": 0.3,
    }[route_profile]
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "distance": 2_000,
                    "time": 3_600,
                    "legs": [
                        {
                            "distance": 2_000,
                            "time": 3_600,
                            "steps": [
                                {
                                    "from_index": 0,
                                    "to_index": 1,
                                    "distance": 1_000,
                                    "time": 2_000,
                                },
                                {
                                    "from_index": 1,
                                    "to_index": 2,
                                    "distance": 1_000,
                                    "time": 1_600,
                                },
                            ],
                        }
                    ],
                },
                "geometry": {
                    "type": "MultiLineString",
                    "coordinates": [
                        [
                            [-87.0, 41.0],
                            [-86.8, 41.1 + latitude_offset],
                            [-86.6, 41.2 + latitude_offset],
                        ]
                    ],
                },
            }
        ],
    }


def test_geoapify_api_key_is_required():
    with pytest.raises(ProviderConfigurationError):
        GeoapifyClient("  ")


def test_geocode_normalizes_geoapify_results():
    def handler(request):
        assert request.url.path == "/v1/geocode/search"
        assert request.url.params["text"] == "Lahore, Pakistan"
        assert request.url.params["limit"] == "3"
        assert request.url.params["format"] == "json"
        assert request.url.params["apiKey"] == "test-key"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "formatted": "Lahore, Punjab, Pakistan",
                        "place_id": "mock-lahore",
                        "result_type": "city",
                        "lat": 31.5204,
                        "lon": 74.3587,
                    }
                ]
            },
        )

    client = GeoapifyClient(
        "test-key",
        http_client=mock_client(handler),
        max_retries=0,
    )

    results = client.geocode(" Lahore, Pakistan ", limit=3)

    assert len(results) == 1
    assert results[0].provider_id == "mock-lahore"
    assert results[0].label == "Lahore, Punjab, Pakistan"
    assert results[0].coordinate == Coordinate(31.5204, 74.3587)
    assert results[0].result_type == "city"


def test_truck_routes_request_three_variants_and_parse_geojson():
    requested_profiles = []

    def handler(request):
        params = request.url.params
        route_type = params["type"]
        avoid = params.get("avoid")
        requested_profiles.append((route_type, avoid))
        assert request.url.path == "/v1/routing"
        assert params["waypoints"] == "41.000000,-87.000000|42.000000,-83.000000"
        assert params["mode"] == "heavy_truck"
        assert params["traffic"] == "approximated"
        assert params["format"] == "geojson"
        assert params["apiKey"] == "test-key"
        profile = "highway-light" if avoid == "highways:0.8" else route_type
        return httpx.Response(200, json=route_payload(profile))

    client = GeoapifyClient(
        "test-key",
        http_client=mock_client(handler),
        max_retries=0,
    )

    routes = client.truck_routes(
        Coordinate(41.0, -87.0),
        Coordinate(42.0, -83.0),
        datetime(2026, 10, 16, 12, tzinfo=timezone.utc),
    )

    assert requested_profiles == [
        ("balanced", None),
        ("short", None),
        ("balanced", "highways:0.8"),
    ]
    assert [route.label for route in routes] == [
        "Balanced route",
        "Shortest distance",
        "Highway-light route",
    ]
    assert len(routes) == 3
    section = routes[0].sections[0]
    assert section.length_meters == 2_000
    assert section.duration_seconds == 3_600
    assert section.coordinates[0] == Coordinate(41.0, -87.0)
    assert section.spans[1].duration_seconds == 1_600


def test_duplicate_route_variants_are_removed():
    attempts = 0

    def handler(request):
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            200,
            json=route_payload("balanced", same_geometry=True),
        )

    client = GeoapifyClient(
        "test-key", http_client=mock_client(handler), max_retries=0
    )

    routes = client.truck_routes(
        Coordinate(41.0, -87.0),
        Coordinate(42.0, -83.0),
        datetime(2026, 10, 16, 12, tzinfo=timezone.utc),
    )

    assert len(routes) == 1
    assert routes[0].label == "Balanced route"
    assert attempts == 5


def test_duplicate_highway_profile_falls_back_to_fewer_maneuvers():
    requested_profiles = []

    def handler(request):
        route_type = request.url.params["type"]
        avoid = request.url.params.get("avoid")
        requested_profiles.append((route_type, avoid))
        if avoid == "highways:0.8":
            profile = "balanced"
        else:
            profile = route_type
        return httpx.Response(200, json=route_payload(profile))

    client = GeoapifyClient(
        "test-key", http_client=mock_client(handler), max_retries=0
    )

    routes = client.truck_routes(
        Coordinate(41.0, -87.0),
        Coordinate(42.0, -83.0),
        datetime(2026, 10, 16, 12, tzinfo=timezone.utc),
    )

    assert requested_profiles == [
        ("balanced", None),
        ("short", None),
        ("balanced", "highways:0.8"),
        ("less_maneuvers", None),
    ]
    assert [route.label for route in routes] == [
        "Balanced route",
        "Shortest distance",
        "Fewer maneuvers route",
    ]


def test_toll_conscious_profile_is_the_final_fallback():
    attempts = 0

    def handler(request):
        nonlocal attempts
        attempts += 1
        route_type = request.url.params["type"]
        avoid = request.url.params.get("avoid")
        if route_type == "short":
            profile = "short"
        elif avoid == "tolls:0.9":
            profile = "toll-conscious"
        else:
            profile = "balanced"
        return httpx.Response(200, json=route_payload(profile))

    client = GeoapifyClient(
        "test-key", http_client=mock_client(handler), max_retries=0
    )

    routes = client.truck_routes(
        Coordinate(41.0, -87.0),
        Coordinate(42.0, -83.0),
        datetime(2026, 10, 16, 12, tzinfo=timezone.utc),
    )

    assert attempts == 5
    assert [route.label for route in routes] == [
        "Balanced route",
        "Shortest distance",
        "Toll-conscious route",
    ]


def test_empty_routes_are_allowed_for_orchestrator_to_handle():
    client = GeoapifyClient(
        "test-key",
        http_client=mock_client(
            lambda request: httpx.Response(
                200, json={"type": "FeatureCollection", "features": []}
            )
        ),
        max_retries=0,
    )

    routes = client.truck_routes(
        Coordinate(41.0, -87.0),
        Coordinate(42.0, -83.0),
        datetime(2026, 10, 16, 12, tzinfo=timezone.utc),
    )

    assert routes == ()


def test_invalid_geoapify_payload_raises_normalized_response_error():
    client = GeoapifyClient(
        "test-key",
        http_client=mock_client(
            lambda request: httpx.Response(200, json={"unexpected": []})
        ),
        max_retries=0,
    )

    with pytest.raises(ProviderResponseError) as error:
        client.geocode("Lahore")

    assert error.value.provider == "Geoapify"
    assert error.value.code == "invalid_provider_response"


def test_authentication_error_does_not_expose_api_key():
    client = GeoapifyClient(
        "super-secret-key",
        http_client=mock_client(
            lambda request: httpx.Response(401, json={"error": "unauthorized"})
        ),
        max_retries=0,
    )

    with pytest.raises(ProviderAuthenticationError) as error:
        client.geocode("Lahore")

    assert "super-secret-key" not in str(error.value)


def test_rate_limit_is_retried_once_then_normalized():
    attempts = 0

    def handler(request):
        nonlocal attempts
        attempts += 1
        return httpx.Response(429, headers={"Retry-After": "2"})

    client = GeoapifyClient(
        "test-key",
        http_client=mock_client(handler),
        max_retries=1,
        sleeper=lambda seconds: None,
    )

    with pytest.raises(ProviderRateLimitError) as error:
        client.geocode("Lahore")

    assert attempts == 2
    assert error.value.retryable
    assert error.value.retry_after_seconds == 2
