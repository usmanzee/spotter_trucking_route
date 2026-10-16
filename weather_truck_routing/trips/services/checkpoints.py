import math
from bisect import bisect_left
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Sequence

EARTH_RADIUS_MILES = 3_958.7613
DISTANCE_TOLERANCE_MILES = 1e-6


@dataclass(frozen=True)
class Coordinate:
    lat: float
    lng: float


@dataclass(frozen=True)
class Checkpoint:
    sequence: int
    distance_miles: float
    coordinate: Coordinate
    elapsed_seconds: float | None = None
    eta: datetime | None = None


@dataclass(frozen=True)
class TimingSpan:
    start_distance_miles: float
    end_distance_miles: float
    duration_seconds: float


def _validate_coordinate(coordinate: Coordinate) -> None:
    if not math.isfinite(coordinate.lat) or not -90 <= coordinate.lat <= 90:
        raise ValueError("Latitude must be between -90 and 90 degrees.")
    if not math.isfinite(coordinate.lng) or not -180 <= coordinate.lng <= 180:
        raise ValueError("Longitude must be between -180 and 180 degrees.")


def haversine_miles(start: Coordinate, end: Coordinate) -> float:
    _validate_coordinate(start)
    _validate_coordinate(end)

    lat1 = math.radians(start.lat)
    lat2 = math.radians(end.lat)
    delta_lat = lat2 - lat1
    delta_lng = math.radians(end.lng - start.lng)
    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lng / 2) ** 2
    )
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(a))


def cumulative_distances(coordinates: Sequence[Coordinate]) -> list[float]:
    if len(coordinates) < 2:
        raise ValueError("A route geometry requires at least two coordinates.")
    for coordinate in coordinates:
        _validate_coordinate(coordinate)

    distances = [0.0]
    for start, end in zip(coordinates, coordinates[1:], strict=False):
        distances.append(distances[-1] + haversine_miles(start, end))
    if distances[-1] <= DISTANCE_TOLERANCE_MILES:
        raise ValueError("Route geometry must have a positive length.")
    return distances


def _checkpoint_distances(total_miles: float, interval_miles: float) -> list[float]:
    if not math.isfinite(interval_miles) or interval_miles <= 0:
        raise ValueError("Checkpoint interval must be a positive number.")

    full_intervals = int(total_miles // interval_miles)
    distances = [index * interval_miles for index in range(full_intervals + 1)]
    if not math.isclose(
        distances[-1], total_miles, abs_tol=DISTANCE_TOLERANCE_MILES
    ):
        distances.append(total_miles)
    else:
        distances[-1] = total_miles
    return distances


def _interpolate_coordinate(
    coordinates: Sequence[Coordinate],
    cumulative_miles: Sequence[float],
    target_miles: float,
) -> Coordinate:
    index = bisect_left(cumulative_miles, target_miles)
    if index == 0:
        return coordinates[0]
    if index >= len(cumulative_miles):
        return coordinates[-1]
    if math.isclose(
        cumulative_miles[index], target_miles, abs_tol=DISTANCE_TOLERANCE_MILES
    ):
        return coordinates[index]

    segment_start = cumulative_miles[index - 1]
    segment_end = cumulative_miles[index]
    fraction = (target_miles - segment_start) / (segment_end - segment_start)
    start = coordinates[index - 1]
    end = coordinates[index]
    return Coordinate(
        lat=start.lat + (end.lat - start.lat) * fraction,
        lng=start.lng + (end.lng - start.lng) * fraction,
    )


def place_checkpoints(
    coordinates: Sequence[Coordinate],
    interval_miles: float,
    *,
    route_distance_miles: float | None = None,
) -> list[Checkpoint]:
    geometry_distances = cumulative_distances(coordinates)
    geometry_total = geometry_distances[-1]
    total_miles = geometry_total if route_distance_miles is None else route_distance_miles

    if not math.isfinite(total_miles) or total_miles <= 0:
        raise ValueError("Route distance must be a positive number.")

    scale = total_miles / geometry_total
    scaled_distances = [distance * scale for distance in geometry_distances]
    targets = _checkpoint_distances(total_miles, interval_miles)

    return [
        Checkpoint(
            sequence=sequence,
            distance_miles=target,
            coordinate=_interpolate_coordinate(
                coordinates, scaled_distances, target
            ),
        )
        for sequence, target in enumerate(targets)
    ]


def _validate_timing_spans(
    spans: Sequence[TimingSpan], route_distance_miles: float
) -> None:
    if not spans:
        raise ValueError("At least one timing span is required.")

    expected_start = 0.0
    for span in spans:
        values = (
            span.start_distance_miles,
            span.end_distance_miles,
            span.duration_seconds,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Timing span values must be finite.")
        if span.duration_seconds < 0:
            raise ValueError("Timing span duration cannot be negative.")
        if span.end_distance_miles <= span.start_distance_miles:
            raise ValueError("Timing spans must have a positive distance.")
        if not math.isclose(
            span.start_distance_miles,
            expected_start,
            abs_tol=DISTANCE_TOLERANCE_MILES,
        ):
            raise ValueError("Timing spans must be ordered, contiguous, and gap-free.")
        expected_start = span.end_distance_miles

    if not math.isclose(
        expected_start, route_distance_miles, abs_tol=DISTANCE_TOLERANCE_MILES
    ):
        raise ValueError("Timing spans must cover the full route distance.")


def elapsed_seconds_at_distance(
    distance_miles: float, spans: Sequence[TimingSpan]
) -> float:
    route_distance = spans[-1].end_distance_miles if spans else 0.0
    _validate_timing_spans(spans, route_distance)
    if distance_miles < 0 or distance_miles > route_distance + DISTANCE_TOLERANCE_MILES:
        raise ValueError("Checkpoint distance is outside the route.")

    elapsed = 0.0
    for span in spans:
        if distance_miles >= span.end_distance_miles - DISTANCE_TOLERANCE_MILES:
            elapsed += span.duration_seconds
            continue
        fraction = (
            (distance_miles - span.start_distance_miles)
            / (span.end_distance_miles - span.start_distance_miles)
        )
        return elapsed + span.duration_seconds * max(0.0, fraction)
    return elapsed


def assign_checkpoint_etas(
    checkpoints: Sequence[Checkpoint],
    spans: Sequence[TimingSpan],
    departure_time: datetime,
) -> list[Checkpoint]:
    if departure_time.tzinfo is None or departure_time.utcoffset() is None:
        raise ValueError("Departure time must include a timezone offset.")
    if not checkpoints:
        raise ValueError("At least one checkpoint is required.")

    route_distance = checkpoints[-1].distance_miles
    _validate_timing_spans(spans, route_distance)

    timed_checkpoints = []
    for checkpoint in checkpoints:
        elapsed = elapsed_seconds_at_distance(checkpoint.distance_miles, spans)
        timed_checkpoints.append(
            replace(
                checkpoint,
                elapsed_seconds=elapsed,
                eta=departure_time + timedelta(seconds=elapsed),
            )
        )
    return timed_checkpoints
