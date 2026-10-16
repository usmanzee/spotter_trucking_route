import pytest

from trips.constants import RiskLevel
from trips.services.recommendation import (
    RiskExposure,
    RiskSample,
    RouteCandidate,
    calculate_risk_exposure,
    recommend_route,
)


def exposure(
    *,
    low=0.0,
    moderate=0.0,
    high=0.0,
    severe=0.0,
    no_travel=0.0,
    unknown=0.0,
    average=0.0,
):
    return RiskExposure(
        miles_by_level={
            RiskLevel.LOW: low,
            RiskLevel.MODERATE: moderate,
            RiskLevel.HIGH: high,
            RiskLevel.SEVERE: severe,
            RiskLevel.NO_TRAVEL: no_travel,
        },
        unknown_miles=unknown,
        average_risk=None if unknown else average,
        route_distance_miles=low + moderate + high + severe + no_travel + unknown,
    )


def route(route_id, route_exposure, duration=3_600, provider_order=0):
    return RouteCandidate(
        route_id=route_id,
        duration_seconds=duration,
        exposure=route_exposure,
        provider_order=provider_order,
    )


def test_exposure_assigns_all_route_miles_once_using_midpoint_cells():
    samples = [
        RiskSample(0, RiskLevel.LOW),
        RiskSample(25, RiskLevel.MODERATE),
        RiskSample(50, RiskLevel.HIGH),
        RiskSample(75, RiskLevel.SEVERE),
        RiskSample(100, RiskLevel.NO_TRAVEL),
    ]

    result = calculate_risk_exposure(samples, route_distance_miles=100)

    assert result.miles_for(RiskLevel.LOW) == pytest.approx(12.5)
    assert result.miles_for(RiskLevel.MODERATE) == pytest.approx(25)
    assert result.miles_for(RiskLevel.HIGH) == pytest.approx(25)
    assert result.miles_for(RiskLevel.SEVERE) == pytest.approx(25)
    assert result.miles_for(RiskLevel.NO_TRAVEL) == pytest.approx(12.5)
    assert sum(result.miles_by_level.values()) == pytest.approx(100)
    assert result.average_risk == pytest.approx(2.0)


def test_fewest_severe_miles_has_priority_over_all_later_criteria():
    routes = [
        route(
            "no-severe",
            exposure(low=80, high=20, average=0.4),
            duration=10_000,
        ),
        route(
            "one-severe-mile",
            exposure(low=99, severe=1, average=0.03),
            duration=1_000,
        ),
    ]

    result = recommend_route(routes)

    assert result.recommended_route_id == "no-severe"


def test_fewest_high_miles_breaks_equal_severe_miles():
    routes = [
        route("more-high", exposure(low=85, high=15, average=0.3)),
        route("less-high", exposure(low=90, high=10, average=0.8)),
    ]

    assert recommend_route(routes).recommended_route_id == "less-high"


def test_average_risk_then_duration_break_remaining_ties():
    routes = [
        route("higher-average", exposure(low=100, average=1.0), duration=1_000),
        route("lower-average", exposure(low=100, average=0.5), duration=9_000),
    ]
    assert recommend_route(routes).recommended_route_id == "lower-average"

    duration_tie_break = [
        route("slower", exposure(low=100, average=0.5), duration=9_000),
        route("faster", exposure(low=100, average=0.5), duration=8_000),
    ]
    assert recommend_route(duration_tie_break).recommended_route_id == "faster"


def test_no_travel_route_is_never_recommended_over_safe_route():
    routes = [
        route(
            "unsafe-short",
            exposure(low=99, no_travel=1, average=0.04),
            duration=100,
        ),
        route(
            "safe-long",
            exposure(low=50, severe=50, average=1.5),
            duration=10_000,
        ),
    ]

    result = recommend_route(routes)

    assert result.status == "recommended"
    assert result.recommended_route_id == "safe-long"
    assert "unsafe-short" not in result.ranked_route_ids


def test_all_no_travel_routes_return_no_recommendation():
    routes = [
        route("unsafe-a", exposure(low=90, no_travel=10, average=0.4)),
        route("unsafe-b", exposure(low=95, no_travel=5, average=0.2)),
    ]

    result = recommend_route(routes)

    assert result.status == "no_safe_route"
    assert result.recommended_route_id is None
    assert result.ranked_route_ids == ("unsafe-b", "unsafe-a")


def test_incomplete_weather_cannot_produce_recommendation():
    result = recommend_route(
        [route("unknown", exposure(low=75, unknown=25, average=None))]
    )

    assert result.status == "insufficient_weather_data"
    assert result.recommended_route_id is None


def test_provider_order_is_stable_final_tie_breaker():
    routes = [
        route("provider-second", exposure(low=100), provider_order=1),
        route("provider-first", exposure(low=100), provider_order=0),
    ]

    assert recommend_route(routes).recommended_route_id == "provider-first"
