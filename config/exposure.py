"""Typed loader for the ``[exposure]`` settings (exposure metrics tool)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import cast

from config.parsing import as_table, read_toml, require_number, section, subtable

STABILITY_CLASSES = ("A", "B", "C", "D", "E", "F")
STABLE_CLASSES = ("E", "F")
AGE_BANDS = ("0-4", "5-17", "18-64", "65+")
_HOURS_PER_DAY = 24.0
_DAYS_PER_YEAR = 365.0


@dataclass(frozen=True)
class ExposureFactors:
    """Resident-air exposure factors.

    Attributes:
        exposure_time_hours_per_day: Hours per day exposed (h/day).
        exposure_frequency_days_per_year: Days per year exposed (days/yr).
        exposure_duration_years: Years of exposure (yr).
        lifetime_years: Lifetime for the carcinogenic averaging time (yr).
    """

    exposure_time_hours_per_day: float
    exposure_frequency_days_per_year: float
    exposure_duration_years: float
    lifetime_years: float


@dataclass(frozen=True)
class AgeBandFactors:
    """Inhalation rate (m^3/day) and body weight (kg) of one age band."""

    inhalation_rate_m3_per_day: float
    body_weight_kg: float


@dataclass(frozen=True)
class ExposureSettings:
    """Screening meteorology, distances, atmospheric parameters and exposure factors.

    Attributes:
        receptor_height_m: Receptor height above ground (m).
        annual_average_factor: 1-hour maximum -> annual average multiplier (0 to 1).
        distances_m: The expanded distance array, ascending, in meters.
        wind_speeds: Stability class -> 10 m wind speeds (m/s) of the screening grid.
        wind_exponent: Stability class -> wind-profile power-law exponent.
        potential_temperature_gradient: Stable class -> d(theta)/dz (K/m).
        factors: Resident-air exposure factors.
        age_bands: Age band -> inhalation rate and body weight.
    """

    receptor_height_m: float
    annual_average_factor: float
    distances_m: tuple[float, ...]
    wind_speeds: Mapping[str, tuple[float, ...]]
    wind_exponent: Mapping[str, float]
    potential_temperature_gradient: Mapping[str, float]
    factors: ExposureFactors
    age_bands: Mapping[str, AgeBandFactors]

    @property
    def combinations(self) -> tuple[tuple[str, float], ...]:
        """Every (stability class, 10 m wind speed) pair of the screening grid."""
        return tuple((cls, u) for cls in STABILITY_CLASSES for u in self.wind_speeds[cls])


def _speeds(table: dict[str, object], name: str) -> Mapping[str, tuple[float, ...]]:
    unknown = sorted(set(table) - set(STABILITY_CLASSES))
    if unknown:
        raise ValueError(f"{name} has unknown classes: {', '.join(unknown)}")
    speeds: dict[str, tuple[float, ...]] = {}
    for cls in STABILITY_CLASSES:
        raw = table.get(cls)
        items = cast(list[object], raw) if isinstance(raw, list) else None
        if not items:
            raise ValueError(f"{name}.{cls} must be a non-empty list of wind speeds")
        values = [{"u": item} for item in items]
        speeds[cls] = tuple(
            require_number(v, "u", minimum=1e-9, name=f"{name}.{cls}") for v in values
        )
    return MappingProxyType(speeds)


def _per_class(
    table: dict[str, object],
    name: str,
    classes: tuple[str, ...],
) -> Mapping[str, float]:
    unknown = sorted(set(table) - set(classes))
    if unknown:
        raise ValueError(f"{name} has unknown classes: {', '.join(unknown)}")
    return MappingProxyType(
        {cls: require_number(table, cls, minimum=1e-9, name=name) for cls in classes},
    )


def _atmosphere(
    table: dict[str, object],
    key: str,
    classes: tuple[str, ...],
) -> Mapping[str, float]:
    return _per_class(subtable(table, key, "exposure"), f"exposure.{key}", classes)


def _segment(raw: object, index: int) -> tuple[float, ...]:
    name = f"exposure.distance_segments[{index}]"
    seg = as_table(raw, name)
    start = require_number(seg, "start", minimum=1e-9, name=name)
    end = require_number(seg, "end", minimum=1e-9, name=name)
    step = require_number(seg, "step", minimum=1e-9, name=name)
    if end < start:
        raise ValueError(f"{name} must have end >= start")
    count = int(round((end - start) / step))
    return tuple(start + i * step for i in range(count + 1) if start + i * step <= end + 1e-9)


def _distances(table: dict[str, object]) -> tuple[float, ...]:
    raw = table.get("distance_segments")
    if not isinstance(raw, list) or not raw:
        raise ValueError("exposure.distance_segments must be a non-empty list of tables")
    distances: list[float] = []
    for index, item in enumerate(cast(list[object], raw)):
        distances.extend(_segment(item, index))
    if any(b <= a for a, b in zip(distances, distances[1:], strict=False)):
        raise ValueError("exposure.distance_segments must give ascending distances")
    minimum = require_number(table, "min_distance_m", minimum=1e-9, name="exposure")
    kept = tuple(d for d in distances if d >= minimum)
    if not kept:
        raise ValueError("exposure.min_distance_m leaves no distance in the array")
    return kept


def _factors(table: dict[str, object]) -> ExposureFactors:
    name = "exposure.factors"
    block = subtable(table, "factors", "exposure")
    time = require_number(block, "exposure_time_hours_per_day", minimum=1e-9, name=name)
    frequency = require_number(block, "exposure_frequency_days_per_year", minimum=1e-9, name=name)
    if time > _HOURS_PER_DAY:
        raise ValueError(f"{name}.exposure_time_hours_per_day must be at most 24")
    if frequency > _DAYS_PER_YEAR:
        raise ValueError(f"{name}.exposure_frequency_days_per_year must be at most 365")
    duration = require_number(block, "exposure_duration_years", minimum=1e-9, name=name)
    lifetime = require_number(block, "lifetime_years", minimum=1e-9, name=name)
    if duration > lifetime:
        raise ValueError(f"{name}.exposure_duration_years must not exceed lifetime_years")
    return ExposureFactors(time, frequency, duration, lifetime)


def _age_bands(table: dict[str, object]) -> Mapping[str, AgeBandFactors]:
    name = "exposure.age_bands"
    block = subtable(table, "age_bands", "exposure")
    unknown = sorted(set(block) - set(AGE_BANDS))
    if unknown:
        raise ValueError(f"{name} has unknown bands: {', '.join(unknown)}")
    bands = {band: _age_band(block, f"{name}.{band}", band) for band in AGE_BANDS}
    return MappingProxyType(bands)


def _age_band(block: dict[str, object], name: str, band: str) -> AgeBandFactors:
    """One band's breathing rate (m^3/day) and body weight (kg), both positive."""
    entry = as_table(block.get(band), name)
    return AgeBandFactors(
        inhalation_rate_m3_per_day=require_number(
            entry,
            "inhalation_rate_m3_per_day",
            minimum=1e-9,
            name=name,
        ),
        body_weight_kg=require_number(entry, "body_weight_kg", minimum=1e-9, name=name),
    )


def _annual_factor(table: dict[str, object]) -> float:
    factor = require_number(table, "annual_average_factor", minimum=1e-9, name="exposure")
    if factor > 1.0:
        raise ValueError("exposure.annual_average_factor must be at most 1")
    return factor


def load_exposure_settings(path: Path | None = None) -> ExposureSettings:
    """Load and validate the exposure settings.

    Args:
        path: Settings file; defaults to the ``settings.toml`` shipped in ``config/``.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If a key is missing or invalid; the message names the key.
    """
    table = section(read_toml(path), "exposure")
    return ExposureSettings(
        receptor_height_m=require_number(table, "receptor_height_m", minimum=0, name="exposure"),
        annual_average_factor=_annual_factor(table),
        distances_m=_distances(table),
        wind_speeds=_speeds(subtable(table, "wind_speeds", "exposure"), "exposure.wind_speeds"),
        wind_exponent=_atmosphere(table, "wind_exponent", STABILITY_CLASSES),
        potential_temperature_gradient=_atmosphere(
            table,
            "potential_temperature_gradient",
            STABLE_CLASSES,
        ),
        factors=_factors(table),
        age_bands=_age_bands(table),
    )


@lru_cache(maxsize=1)
def get_exposure_settings() -> ExposureSettings:
    """Return the cached exposure settings from the default file."""
    return load_exposure_settings()
