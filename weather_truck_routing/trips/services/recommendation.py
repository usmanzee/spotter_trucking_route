import math
from dataclasses import dataclass
from typing import Sequence

from trips.constants import RISK_SCORES, RiskLevel

DISTANCE_TOLERANCE_MILES = 1e-6


@dataclass(frozen=True)
class RiskSample:
    distance_miles: float
    level: RiskLevel
    is_complete: bool = True


@dataclass(frozen=True)
class RiskExposure:
    miles_by_level: dict[RiskLevel, float]
    unknown_miles: float
    average_risk: float | None
    route_distance_miles: float

    @property
    def is_complete(self) -> bool:
        return self.unknown_miles <= DISTANCE_TOLERANCE_MILES

    @property
    def contains_no_travel(self) -> bool:
        return (
            self.miles_by_level.get(RiskLevel.NO_TRAVEL, 0.0)
            > DISTANCE_TOLERANCE_MILES
        )

    def miles_for(self, level: RiskLevel) -> float:
        return self.miles_by_level.get(level, 0.0)


@dataclass(frozen=True)
class RouteCandidate:
    route_id: str
    duration_seconds: float
    exposure: RiskExposure
    provider_order: int


@dataclass(frozen=True)
class Recommendation:
    status: str
    recommended_route_id: str | None
    ranked_route_ids: tuple[str, ...]


def calculate_risk_exposure(
    samples: Sequence[RiskSample], route_distance_miles: float
) -> RiskExposure:
    if not math.isfinite(route_distance_miles) or route_distance_miles <= 0:
        raise ValueError("Route distance must be a positive number.")
    if len(samples) < 2:
        raise ValueError("At least two risk samples are required.")

    distances = [sample.distance_miles for sample in samples]
    if any(not math.isfinite(distance) for distance in distances):
        raise ValueError("Risk sample distances must be finite.")
    if any(current <= previous for previous, current in zip(distances, distances[1:])):
        raise ValueError("Risk samples must be strictly ordered by distance.")
    if not math.isclose(distances[0], 0.0, abs_tol=DISTANCE_TOLERANCE_MILES):
        raise ValueError("The first risk sample must be at mile zero.")
    if not math.isclose(
        distances[-1], route_distance_miles, abs_tol=DISTANCE_TOLERANCE_MILES
    ):
        raise ValueError("The final risk sample must be at the route endpoint.")

    miles_by_level = {level: 0.0 for level in RISK_SCORES}
    unknown_miles = 0.0
    weighted_score = 0.0

    for index, sample in enumerate(samples):
        left_boundary = (
            0.0
            if index == 0
            else (distances[index - 1] + sample.distance_miles) / 2
        )
        right_boundary = (
            route_distance_miles
            if index == len(samples) - 1
            else (sample.distance_miles + distances[index + 1]) / 2
        )
        represented_miles = right_boundary - left_boundary

        if not sample.is_complete or sample.level == RiskLevel.UNKNOWN:
            unknown_miles += represented_miles
            continue
        if sample.level not in RISK_SCORES:
            raise ValueError(f"Unsupported risk level: {sample.level}")

        miles_by_level[sample.level] += represented_miles
        weighted_score += represented_miles * RISK_SCORES[sample.level]

    average_risk = (
        None
        if unknown_miles > DISTANCE_TOLERANCE_MILES
        else weighted_score / route_distance_miles
    )
    return RiskExposure(
        miles_by_level=miles_by_level,
        unknown_miles=unknown_miles,
        average_risk=average_risk,
        route_distance_miles=route_distance_miles,
    )


def _validate_candidates(routes: Sequence[RouteCandidate]) -> None:
    if not routes:
        raise ValueError("At least one route candidate is required.")
    route_ids = [route.route_id for route in routes]
    if any(not route_id for route_id in route_ids):
        raise ValueError("Every route candidate requires an ID.")
    if len(route_ids) != len(set(route_ids)):
        raise ValueError("Route candidate IDs must be unique.")
    for route in routes:
        if not math.isfinite(route.duration_seconds) or route.duration_seconds < 0:
            raise ValueError("Route duration must be a finite, nonnegative number.")


def recommend_route(routes: Sequence[RouteCandidate]) -> Recommendation:
    _validate_candidates(routes)
    complete_routes = [
        route
        for route in routes
        if route.exposure.is_complete and route.exposure.average_risk is not None
    ]
    safe_routes = [
        route for route in complete_routes if not route.exposure.contains_no_travel
    ]

    if safe_routes:
        ranked = sorted(
            safe_routes,
            key=lambda route: (
                route.exposure.miles_for(RiskLevel.SEVERE),
                route.exposure.miles_for(RiskLevel.HIGH),
                route.exposure.average_risk,
                route.duration_seconds,
                route.provider_order,
            ),
        )
        return Recommendation(
            status="recommended",
            recommended_route_id=ranked[0].route_id,
            ranked_route_ids=tuple(route.route_id for route in ranked),
        )

    if complete_routes:
        ranked = sorted(
            complete_routes,
            key=lambda route: (
                route.exposure.miles_for(RiskLevel.NO_TRAVEL),
                route.exposure.miles_for(RiskLevel.SEVERE),
                route.exposure.miles_for(RiskLevel.HIGH),
                route.exposure.average_risk,
                route.duration_seconds,
                route.provider_order,
            ),
        )
        return Recommendation(
            status="no_safe_route",
            recommended_route_id=None,
            ranked_route_ids=tuple(route.route_id for route in ranked),
        )

    return Recommendation(
        status="insufficient_weather_data",
        recommended_route_id=None,
        ranked_route_ids=(),
    )
