from datetime import datetime, timedelta, timezone

import pytest

from trips.clients.models import (
    GeocodedLocation,
    ProviderRoute,
    RouteSection,
    RouteSpan,
)
from trips.clients.open_meteo import HourlyWeather, LocationForecast
from trips.exceptions import TripAnalysisError
from trips.services.analysis import TripAnalysisInput, TripAnalysisService
from trips.services.checkpoints import Coordinate


ORIGIN = Coordinate(41.0, -87.0)
DESTINATION = Coordinate(42.0, -83.0)


def make_route(
    route_id="route-1",
    *,
    distance_miles=100,
    duration_seconds=7_200,
    middle=Coordinate(41.5, -85.0),
    critical=False,
):
    section = RouteSection(
        section_id=f"{route_id}-section",
        coordinates=(ORIGIN, middle, DESTINATION),
        length_meters=distance_miles * 1_609.344,
        duration_seconds=duration_seconds,
        spans=(
            RouteSpan(0, distance_miles * 804.672, duration_seconds * 0.6),
            RouteSpan(1, distance_miles * 804.672, duration_seconds * 0.4),
        ),
        notices=("Critical mock notice",) if critical else (),
        has_critical_notice=critical,
    )
    return ProviderRoute(
        route_id=route_id,
        label=f"Mock {route_id}",
        sections=(section,),
        notices=(),
        has_critical_notice=critical,
    )


class FakeRouteClient:
    def __init__(self, routes=None, missing_location=None):
        self.routes = tuple(routes or [make_route()])
        self.missing_location = missing_location

    def geocode(self, query, *, limit=5):
        if query == self.missing_location:
            return ()
        coordinate = ORIGIN if "Lahore" in query else DESTINATION
        return (
            GeocodedLocation(
                provider_id=f"mock:{query}",
                label=f"Resolved {query}",
                coordinate=coordinate,
                result_type="locality",
            ),
        )

    def truck_routes(
        self, origin, destination, departure_time, *, alternatives=2
    ):
        assert origin == ORIGIN
        assert destination == DESTINATION
        assert alternatives == 2
        return self.routes


class FakeWeatherClient:
    def __init__(self, *, wind_mph=20.0, rain=0.0, snow=0.0):
        self.wind_mph = wind_mph
        self.rain = rain
        self.snow = snow
        self.requested_coordinates = ()
        self.requested_start_time = None
        self.requested_end_time = None

    def forecasts(self, coordinates, start_time, end_time):
        self.requested_coordinates = tuple(coordinates)
        self.requested_start_time = start_time
        self.requested_end_time = end_time
        current = start_time.replace(minute=0, second=0, microsecond=0)
        final = end_time.replace(minute=0, second=0, microsecond=0) + timedelta(
            hours=1
        )
        hours = []
        while current <= final:
            hours.append(
                HourlyWeather(
                    time=current,
                    wind_mph=self.wind_mph,
                    wind_gust_mph=self.wind_mph,
                    rain_in_per_hr=self.rain,
                    snow_in_per_hr=self.snow,
                )
            )
            current += timedelta(hours=1)
        return tuple(
            LocationForecast(
                requested_coordinate=coordinate,
                provider_coordinate=coordinate,
                elevation_meters=100,
                hourly=tuple(hours),
            )
            for coordinate in coordinates
        )


def trip_input():
    return TripAnalysisInput(
        origin="Lahore, Pakistan",
        destination="Karachi, Pakistan",
        departure_time=datetime(2026, 10, 16, 12, tzinfo=timezone.utc),
        cargo_weight_lb=35_000,
        checkpoint_interval_miles=25,
    )


def test_analysis_connects_routes_checkpoints_weather_and_recommendation():
    weather = FakeWeatherClient()
    service = TripAnalysisService(
        FakeRouteClient(
            routes=[
                make_route("route-fast", duration_seconds=7_200),
                make_route(
                    "route-slow",
                    distance_miles=110,
                    duration_seconds=8_000,
                    middle=Coordinate(42.0, -85.5),
                ),
            ]
        ),
        weather,
    )

    result = service.analyze(trip_input())

    assert result["status"] == "complete"
    assert result["recommendation"]["route_id"] == "route-fast"
    assert len(result["routes"]) == 2
    assert result["routes"][0]["geometry"]["type"] == "LineString"
    assert result["routes"][0]["geometry"]["coordinates"][0] == [-87.0, 41.0]
    assert [
        checkpoint["distance_miles"]
        for checkpoint in result["routes"][0]["checkpoints"]
    ] == [0, 25, 50, 75, 100]
    assert result["routes"][0]["checkpoints"][1]["elapsed_seconds"] == 2_160
    assert result["routes"][0]["checkpoints"][0]["risk"]["level"] == "low"
    assert result["routes"][0]["summary"]["weather_complete"]
    assert result["routes"][0]["summary"]["risk_miles"]["low"] == 100
    assert "Geoapify" in result["attribution"]["routing"]
    assert "Open-Meteo" in result["attribution"]["weather"]
    assert result["forecast_window"]["hours"] == 48
    assert weather.requested_end_time >= trip_input().departure_time + timedelta(
        hours=48
    )
    assert len(result["routes"][0]["checkpoints"][0]["hourly_forecast"]) >= 48
    assert (
        result["routes"][0]["checkpoints"][0]["hourly_forecast"][0]["risk"][
            "level"
        ]
        == "low"
    )
    assert any(
        warning["code"] == "fewer_route_alternatives"
        for warning in result["warnings"]
    )
    assert len(weather.requested_coordinates) < sum(
        len(route["checkpoints"]) for route in result["routes"]
    )


def test_all_no_travel_weather_returns_no_safe_route():
    service = TripAnalysisService(
        FakeRouteClient(routes=[make_route("unsafe-a"), make_route("unsafe-b")]),
        FakeWeatherClient(wind_mph=55.0),
    )

    result = service.analyze(trip_input())

    assert result["recommendation"]["status"] == "no_safe_route"
    assert result["recommendation"]["route_id"] is None
    assert all(
        route["summary"]["contains_no_travel"] for route in result["routes"]
    )


def test_missing_weather_makes_route_ineligible_for_recommendation():
    service = TripAnalysisService(
        FakeRouteClient(),
        FakeWeatherClient(wind_mph=None),
    )

    result = service.analyze(trip_input())

    assert result["recommendation"]["status"] == "insufficient_weather_data"
    assert result["routes"][0]["summary"]["unknown_miles"] == 100
    assert result["routes"][0]["summary"]["average_risk"] is None
    assert any(
        warning["code"] == "incomplete_weather_data"
        for warning in result["warnings"]
    )


def test_unresolved_location_identifies_the_input_field():
    service = TripAnalysisService(
        FakeRouteClient(missing_location="Lahore, Pakistan"),
        FakeWeatherClient(),
    )

    with pytest.raises(TripAnalysisError) as error:
        service.analyze(trip_input())

    assert error.value.code == "location_not_found"
    assert error.value.details == {"field": "origin"}


def test_critical_routes_are_excluded_with_warning():
    service = TripAnalysisService(
        FakeRouteClient(
            routes=[make_route("critical", critical=True), make_route("safe")]
        ),
        FakeWeatherClient(),
    )

    result = service.analyze(trip_input())

    assert [route["id"] for route in result["routes"]] == ["safe"]
    assert any(
        warning["code"] == "route_excluded_critical_notice"
        for warning in result["warnings"]
    )


def test_all_critical_routes_produce_no_usable_routes_error():
    service = TripAnalysisService(
        FakeRouteClient(routes=[make_route("critical", critical=True)]),
        FakeWeatherClient(),
    )

    with pytest.raises(TripAnalysisError) as error:
        service.analyze(trip_input())

    assert error.value.code == "no_usable_routes"
