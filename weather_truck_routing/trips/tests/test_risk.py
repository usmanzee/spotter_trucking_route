import pytest

from trips.constants import RiskLevel
from trips.services.risk import (
    classify_checkpoint,
    classify_rain,
    classify_snow,
    classify_wind,
)


@pytest.mark.parametrize(
    ("wind_mph", "expected"),
    [
        (24.99, RiskLevel.LOW),
        (25.0, RiskLevel.MODERATE),
        (34.99, RiskLevel.MODERATE),
        (35.0, RiskLevel.HIGH),
        (44.99, RiskLevel.HIGH),
        (45.0, RiskLevel.SEVERE),
        (54.99, RiskLevel.SEVERE),
        (55.0, RiskLevel.NO_TRAVEL),
    ],
)
def test_wind_boundaries_for_light_load(wind_mph, expected):
    assert classify_wind(wind_mph, cargo_weight_lb=20_000).level == expected


@pytest.mark.parametrize(
    ("rain", "expected"),
    [
        (0.099, RiskLevel.LOW),
        (0.10, RiskLevel.MODERATE),
        (0.25, RiskLevel.HIGH),
        (0.50, RiskLevel.SEVERE),
        (1.00, RiskLevel.SEVERE),
        (1.001, RiskLevel.NO_TRAVEL),
    ],
)
def test_rain_boundaries(rain, expected):
    assert classify_rain(rain) == expected


@pytest.mark.parametrize(
    ("snow", "expected"),
    [
        (0.499, RiskLevel.LOW),
        (0.5, RiskLevel.MODERATE),
        (1.0, RiskLevel.HIGH),
        (2.0, RiskLevel.SEVERE),
        (3.0, RiskLevel.SEVERE),
        (3.001, RiskLevel.NO_TRAVEL),
    ],
)
def test_snow_boundaries(snow, expected):
    assert classify_snow(snow) == expected


def test_45_mph_wind_only_becomes_no_travel_above_30000_lb():
    at_boundary = classify_wind(45.0, cargo_weight_lb=30_000)
    above_boundary = classify_wind(45.0, cargo_weight_lb=30_000.01)

    assert at_boundary.level == RiskLevel.SEVERE
    assert not at_boundary.load_adjusted
    assert above_boundary.level == RiskLevel.NO_TRAVEL
    assert above_boundary.load_adjusted


def test_35_mph_wind_only_becomes_severe_above_40000_lb():
    at_boundary = classify_wind(35.0, cargo_weight_lb=40_000)
    above_boundary = classify_wind(35.0, cargo_weight_lb=40_000.01)

    assert at_boundary.level == RiskLevel.HIGH
    assert above_boundary.level == RiskLevel.SEVERE
    assert above_boundary.load_adjusted


def test_checkpoint_uses_highest_condition_risk():
    result = classify_checkpoint(
        wind_mph=26.0,
        rain_in_per_hr=0.3,
        snow_in_per_hr=0.0,
        cargo_weight_lb=35_000,
    )

    assert result.level == RiskLevel.HIGH
    assert result.score == 2
    assert result.drivers == ("rain",)
    assert result.is_complete


def test_checkpoint_reports_load_adjustment_as_a_driver():
    result = classify_checkpoint(
        wind_mph=45.0,
        rain_in_per_hr=0.0,
        snow_in_per_hr=0.0,
        cargo_weight_lb=35_000,
    )

    assert result.level == RiskLevel.NO_TRAVEL
    assert result.drivers == ("wind", "cargo_weight")


def test_missing_weather_is_unknown_not_low():
    result = classify_checkpoint(
        wind_mph=20.0,
        rain_in_per_hr=None,
        snow_in_per_hr=0.0,
        cargo_weight_lb=35_000,
    )

    assert result.level == RiskLevel.UNKNOWN
    assert result.score is None
    assert result.drivers == ("missing_rain",)
    assert not result.is_complete


@pytest.mark.parametrize(
    ("function", "arguments"),
    [
        (classify_rain, (-0.01,)),
        (classify_snow, (float("nan"),)),
        (classify_wind, (20.0, -1.0)),
    ],
)
def test_invalid_measurements_are_rejected(function, arguments):
    with pytest.raises(ValueError):
        function(*arguments)
