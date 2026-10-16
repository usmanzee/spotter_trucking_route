import math
from dataclasses import dataclass

from trips.constants import (
    HEAVY_LOAD_NO_TRAVEL_LB,
    RAIN_HIGH_IN_PER_HR,
    RAIN_MODERATE_IN_PER_HR,
    RAIN_NO_TRAVEL_ABOVE_IN_PER_HR,
    RAIN_SEVERE_IN_PER_HR,
    RISK_SCORES,
    SNOW_HIGH_IN_PER_HR,
    SNOW_MODERATE_IN_PER_HR,
    SNOW_NO_TRAVEL_ABOVE_IN_PER_HR,
    SNOW_SEVERE_IN_PER_HR,
    VERY_HEAVY_LOAD_SEVERE_LB,
    WIND_HIGH_MPH,
    WIND_MODERATE_MPH,
    WIND_NO_TRAVEL_MPH,
    WIND_SEVERE_MPH,
    RiskLevel,
)


@dataclass(frozen=True)
class WindRisk:
    level: RiskLevel
    load_adjusted: bool = False


@dataclass(frozen=True)
class CheckpointRisk:
    level: RiskLevel
    score: int | None
    condition_levels: dict[str, RiskLevel]
    drivers: tuple[str, ...]
    is_complete: bool


def _validate_measurement(name: str, value: float) -> float:
    numeric_value = float(value)
    if not math.isfinite(numeric_value) or numeric_value < 0:
        raise ValueError(f"{name} must be a finite, nonnegative number.")
    return numeric_value


def classify_wind(wind_mph: float, cargo_weight_lb: float) -> WindRisk:
    wind = _validate_measurement("wind_mph", wind_mph)
    load = _validate_measurement("cargo_weight_lb", cargo_weight_lb)

    if wind >= WIND_NO_TRAVEL_MPH:
        return WindRisk(RiskLevel.NO_TRAVEL)
    if wind >= WIND_SEVERE_MPH:
        if load > HEAVY_LOAD_NO_TRAVEL_LB:
            return WindRisk(RiskLevel.NO_TRAVEL, load_adjusted=True)
        return WindRisk(RiskLevel.SEVERE)
    if wind >= WIND_HIGH_MPH:
        if load > VERY_HEAVY_LOAD_SEVERE_LB:
            return WindRisk(RiskLevel.SEVERE, load_adjusted=True)
        return WindRisk(RiskLevel.HIGH)
    if wind >= WIND_MODERATE_MPH:
        return WindRisk(RiskLevel.MODERATE)
    return WindRisk(RiskLevel.LOW)


def classify_rain(rain_in_per_hr: float) -> RiskLevel:
    rain = _validate_measurement("rain_in_per_hr", rain_in_per_hr)

    if rain > RAIN_NO_TRAVEL_ABOVE_IN_PER_HR:
        return RiskLevel.NO_TRAVEL
    if rain >= RAIN_SEVERE_IN_PER_HR:
        return RiskLevel.SEVERE
    if rain >= RAIN_HIGH_IN_PER_HR:
        return RiskLevel.HIGH
    if rain >= RAIN_MODERATE_IN_PER_HR:
        return RiskLevel.MODERATE
    return RiskLevel.LOW


def classify_snow(snow_in_per_hr: float) -> RiskLevel:
    snow = _validate_measurement("snow_in_per_hr", snow_in_per_hr)

    if snow > SNOW_NO_TRAVEL_ABOVE_IN_PER_HR:
        return RiskLevel.NO_TRAVEL
    if snow >= SNOW_SEVERE_IN_PER_HR:
        return RiskLevel.SEVERE
    if snow >= SNOW_HIGH_IN_PER_HR:
        return RiskLevel.HIGH
    if snow >= SNOW_MODERATE_IN_PER_HR:
        return RiskLevel.MODERATE
    return RiskLevel.LOW


def classify_checkpoint(
    *,
    wind_mph: float | None,
    rain_in_per_hr: float | None,
    snow_in_per_hr: float | None,
    cargo_weight_lb: float,
) -> CheckpointRisk:
    load = _validate_measurement("cargo_weight_lb", cargo_weight_lb)
    condition_levels: dict[str, RiskLevel] = {}
    wind_load_adjusted = False

    if wind_mph is not None:
        wind_risk = classify_wind(wind_mph, load)
        condition_levels["wind"] = wind_risk.level
        wind_load_adjusted = wind_risk.load_adjusted
    if rain_in_per_hr is not None:
        condition_levels["rain"] = classify_rain(rain_in_per_hr)
    if snow_in_per_hr is not None:
        condition_levels["snow"] = classify_snow(snow_in_per_hr)

    required_conditions = {"wind", "rain", "snow"}
    if set(condition_levels) != required_conditions:
        return CheckpointRisk(
            level=RiskLevel.UNKNOWN,
            score=None,
            condition_levels=condition_levels,
            drivers=tuple(
                f"missing_{condition}"
                for condition in sorted(required_conditions - set(condition_levels))
            ),
            is_complete=False,
        )

    overall_level = max(condition_levels.values(), key=RISK_SCORES.__getitem__)
    drivers = [
        condition
        for condition, level in condition_levels.items()
        if level == overall_level
    ]
    if wind_load_adjusted and "wind" in drivers:
        drivers.append("cargo_weight")

    return CheckpointRisk(
        level=overall_level,
        score=RISK_SCORES[overall_level],
        condition_levels=condition_levels,
        drivers=tuple(drivers),
        is_complete=True,
    )
