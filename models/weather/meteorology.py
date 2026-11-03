"""Summary of an hourly meteorological series into representative annual conditions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

import numpy as np
from numpy.typing import NDArray

from models.weather.stability import classify_stability

_FULL_CIRCLE = 360.0


@dataclass(frozen=True)
class HourlySummary:
    """Representative conditions of a series of hours.

    Attributes:
        wind_speed: Mean wind speed, not below the given minimum, in meters per second (m/s).
        mean_wind_speed: Mean wind speed before the minimum was applied (m/s).
        wind_direction: Centre of the most frequent direction sector, in degrees clockwise
            from north, the direction the wind blows from (0 to < 360).
        stability_class: Most frequent Pasquill-Gifford class, "A" to "F".
        class_frequency: Class -> fraction of hours (unitless, sums to 1).
        temperature: Mean of the finite temperatures, in the unit they were given in;
            NaN if there were none.
        hours: Number of hours summarized.
    """

    wind_speed: float
    mean_wind_speed: float
    wind_direction: float
    stability_class: str
    class_frequency: Mapping[str, float]
    temperature: float
    hours: int


@dataclass(frozen=True)
class HourlyInputs:
    """Equal-length series of already-validated hours (arrays of the same shape).

    Attributes:
        wind_speed: Wind speed at 10 m (m/s).
        wind_direction: Direction the wind blows from (degrees, 0 to 360).
        solar_radiation: Total solar radiation (W/m^2).
        cloud_cover: Total cloud cover (%).
        low_cloud_cover: Low cloud cover (%).
        is_day: True for daytime hours.
        temperature: Air temperature in any unit; NaN where missing.
    """

    wind_speed: NDArray[np.float64]
    wind_direction: NDArray[np.float64]
    solar_radiation: NDArray[np.float64]
    cloud_cover: NDArray[np.float64]
    low_cloud_cover: NDArray[np.float64]
    is_day: NDArray[np.bool_]
    temperature: NDArray[np.float64]


def classify_hours(hours: HourlyInputs) -> list[str]:
    """Return the Pasquill-Gifford class of every hour (see ``classify_stability``).

    Raises:
        ValueError: If any hour has an impossible value.
    """
    return [
        classify_stability(float(u), float(r), float(c), float(low), bool(day))
        for u, r, c, low, day in zip(
            hours.wind_speed,
            hours.solar_radiation,
            hours.cloud_cover,
            hours.low_cloud_cover,
            hours.is_day,
            strict=True,
        )
    ]


def _check_lengths(hours: HourlyInputs) -> int:
    lengths = {
        len(series)
        for series in (
            hours.wind_speed,
            hours.wind_direction,
            hours.solar_radiation,
            hours.cloud_cover,
            hours.low_cloud_cover,
            hours.is_day,
            hours.temperature,
        )
    }
    if len(lengths) != 1:
        raise ValueError("hourly series must have equal lengths")
    count = lengths.pop()
    if count == 0:
        raise ValueError("hourly series must not be empty")
    return count


def prevailing_direction(wind_direction: NDArray[np.float64], sector_width: float) -> float:
    """Return the centre of the most frequent sector, in degrees (0 to < 360).

    Args:
        wind_direction: Directions the wind blows from, in degrees (0 to 360).
        sector_width: Sector width, in degrees; must divide 360.

    Ties go to the smallest sector centre.
    """
    if sector_width <= 0 or wind_direction.size == 0:
        raise ValueError("sector_width must be positive and directions must not be empty")
    centres = np.mod(np.round(wind_direction / sector_width) * sector_width, _FULL_CIRCLE)
    values, counts = np.unique(centres, return_counts=True)
    return float(values[int(np.argmax(counts))])


def _class_frequency(classes: Sequence[str]) -> tuple[str, Mapping[str, float]]:
    values, counts = np.unique(np.asarray(classes), return_counts=True)
    frequency = {str(v): float(c) / len(classes) for v, c in zip(values, counts, strict=True)}
    return str(values[int(np.argmax(counts))]), MappingProxyType(frequency)


def _mean_temperature(temperature: NDArray[np.float64]) -> float:
    finite = temperature[np.isfinite(temperature)]
    return float(np.mean(finite)) if finite.size else float("nan")


def summarize_hours(
    hours: HourlyInputs,
    *,
    minimum_wind_speed: float,
    sector_width: float,
) -> HourlySummary:
    """Summarize validated hours into representative conditions.

    Args:
        hours: Equal-length series (see ``HourlyInputs``).
        minimum_wind_speed: Lowest wind speed reported, in meters per second (m/s).
        sector_width: Direction sector width, in degrees (divides 360).

    Returns:
        Mean wind speed (not below the minimum, m/s), prevailing direction (degrees), the
        most frequent class (ties: earliest letter), class frequencies, mean temperature
        (input unit) and the number of hours.

    Raises:
        ValueError: If the series are empty, differ in length, or hold an impossible hour.
    """
    count = _check_lengths(hours)
    mean_speed = float(np.mean(hours.wind_speed))
    modal, frequency = _class_frequency(classify_hours(hours))
    return HourlySummary(
        wind_speed=max(mean_speed, minimum_wind_speed),
        mean_wind_speed=mean_speed,
        wind_direction=prevailing_direction(hours.wind_direction, sector_width),
        stability_class=modal,
        class_frequency=frequency,
        temperature=_mean_temperature(hours.temperature),
        hours=count,
    )
