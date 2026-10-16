from datetime import datetime, timedelta, timezone

import pytest

from trips.services.checkpoints import (
    Coordinate,
    TimingSpan,
    assign_checkpoint_etas,
    haversine_miles,
    place_checkpoints,
)


def test_places_checkpoints_every_25_miles_and_includes_destination():
    coordinates = [Coordinate(0.0, 0.0), Coordinate(0.0, 1.0)]

    checkpoints = place_checkpoints(coordinates, interval_miles=25)

    assert [point.distance_miles for point in checkpoints[:-1]] == [0, 25, 50]
    assert checkpoints[-1].distance_miles == pytest.approx(
        haversine_miles(*coordinates)
    )
    assert checkpoints[-1].coordinate == coordinates[-1]


def test_checkpoint_distance_follows_bent_road_geometry():
    coordinates = [
        Coordinate(0.0, 0.0),
        Coordinate(0.0, 0.5),
        Coordinate(0.5, 0.5),
    ]

    checkpoints = place_checkpoints(coordinates, interval_miles=25)
    straight_line_distance = haversine_miles(coordinates[0], coordinates[-1])

    assert checkpoints[-1].distance_miles > straight_line_distance
    assert any(point.distance_miles == 50 for point in checkpoints)
    fifty_mile_checkpoint = next(
        point for point in checkpoints if point.distance_miles == 50
    )
    assert fifty_mile_checkpoint.coordinate.lng == pytest.approx(0.5)
    assert fifty_mile_checkpoint.coordinate.lat > 0


def test_provider_route_distance_can_scale_checkpoint_mile_markers():
    coordinates = [Coordinate(0.0, 0.0), Coordinate(0.0, 1.0)]

    checkpoints = place_checkpoints(
        coordinates,
        interval_miles=25,
        route_distance_miles=100,
    )

    assert [point.distance_miles for point in checkpoints] == [0, 25, 50, 75, 100]
    assert checkpoints[2].coordinate.lng == pytest.approx(0.5)


def test_checkpoint_etas_use_each_timing_span_duration():
    checkpoints = place_checkpoints(
        [Coordinate(0.0, 0.0), Coordinate(0.0, 1.0)],
        interval_miles=25,
        route_distance_miles=100,
    )
    spans = [
        TimingSpan(0, 50, 3_600),
        TimingSpan(50, 100, 1_800),
    ]
    departure = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)

    result = assign_checkpoint_etas(checkpoints, spans, departure)

    assert [point.elapsed_seconds for point in result] == [
        0,
        1_800,
        3_600,
        4_500,
        5_400,
    ]
    assert result[-1].eta == departure + timedelta(seconds=5_400)


def test_checkpoint_eta_requires_timezone_aware_departure():
    checkpoints = place_checkpoints(
        [Coordinate(0.0, 0.0), Coordinate(0.0, 1.0)],
        interval_miles=25,
        route_distance_miles=100,
    )

    with pytest.raises(ValueError, match="timezone"):
        assign_checkpoint_etas(
            checkpoints,
            [TimingSpan(0, 100, 3_600)],
            datetime(2026, 10, 16, 12, 0),
        )


def test_timing_spans_must_cover_route_without_gaps():
    checkpoints = place_checkpoints(
        [Coordinate(0.0, 0.0), Coordinate(0.0, 1.0)],
        interval_miles=25,
        route_distance_miles=100,
    )

    with pytest.raises(ValueError, match="contiguous"):
        assign_checkpoint_etas(
            checkpoints,
            [TimingSpan(0, 40, 1_000), TimingSpan(50, 100, 1_000)],
            datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc),
        )
