"""Typed loader for the ``[occupational]`` settings (worker box model and dosimetry)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from config.parsing import read_toml, require_number, require_str, section, subtable

NAME = "occupational"


@dataclass(frozen=True)
class Ventilation:
    """One ventilation tier of the box model.

    Attributes:
        label: Name shown with the result.
        rate_ft3_per_min: Room ventilation rate, ft^3/min.
        mixing_factor: Mixing efficiency k, unitless, in (0, 1].
    """

    label: str
    rate_ft3_per_min: float
    mixing_factor: float


@dataclass(frozen=True)
class Thresholds:
    """Tier boundaries: ratio and hazard quotient are unitless, cancer risk is a probability."""

    exceedance_ratio: float
    elevated_ratio: float
    exceedance_hq: float
    elevated_hq: float
    exceedance_cancer_risk: float
    elevated_cancer_risk: float


@dataclass(frozen=True)
class OccupationalSettings:
    """Worker screening factors.

    Attributes:
        shift_inhalation_m3: Air a worker breathes in a shift, m^3/day.
        daily_inhalation_m3: Air breathed in 24 hours (the resident rate), m^3/day.
        worker_days_per_year: Most days a worker works in a year, days/yr.
        tenure_years: Years of work, yr.
        lifetime_years: Averaging time for cancer risk, yr.
        twa_hours: Length of the time-weighted-average day, h.
        low_volatility_mmhg: Vapor pressure at or below which a warning is added, mmHg.
        thresholds: Tier boundaries.
        baseline: The baseline ventilation tier.
        worst_case: The worst-case (enclosed zone) tier.
    """

    shift_inhalation_m3: float
    daily_inhalation_m3: float
    worker_days_per_year: float
    tenure_years: float
    lifetime_years: float
    twa_hours: float
    low_volatility_mmhg: float
    thresholds: Thresholds
    baseline: Ventilation
    worst_case: Ventilation


def _tier(table: dict[str, object], key: str) -> Ventilation:
    name = f"{NAME}.ventilation.{key}"
    block = subtable(subtable(table, "ventilation", NAME), key, f"{NAME}.ventilation")
    mixing = require_number(block, "mixing_factor", minimum=1e-9, name=name)
    if mixing > 1.0:
        raise ValueError(f"{name}.mixing_factor must be at most 1")
    return Ventilation(
        label=require_str(block, "label", name),
        rate_ft3_per_min=require_number(block, "rate_ft3_per_min", minimum=1e-9, name=name),
        mixing_factor=mixing,
    )


def _pair(block: dict[str, object], high: str, low: str) -> tuple[float, float]:
    name = f"{NAME}.thresholds"
    upper = require_number(block, high, minimum=1e-30, name=name)
    lower = require_number(block, low, minimum=1e-30, name=name)
    if lower >= upper:
        raise ValueError(f"{name}.{low} must be below {name}.{high}")
    return upper, lower


def _thresholds(table: dict[str, object]) -> Thresholds:
    block = subtable(table, "thresholds", NAME)
    ratio = _pair(block, "exceedance_ratio", "elevated_ratio")
    hq = _pair(block, "exceedance_hq", "elevated_hq")
    risk = _pair(block, "exceedance_cancer_risk", "elevated_cancer_risk")
    return Thresholds(ratio[0], ratio[1], hq[0], hq[1], risk[0], risk[1])


def _check(table: dict[str, object]) -> None:
    if require_number(table, "shift_inhalation_m3", minimum=1e-9, name=NAME) > require_number(
        table,
        "daily_inhalation_m3",
        minimum=1e-9,
        name=NAME,
    ):
        raise ValueError(f"{NAME}.shift_inhalation_m3 must not exceed daily_inhalation_m3")
    if require_number(table, "worker_days_per_year", minimum=1e-9, name=NAME) > 365.0:
        raise ValueError(f"{NAME}.worker_days_per_year must be at most 365")
    if require_number(table, "twa_hours", minimum=1e-9, name=NAME) > 24.0:
        raise ValueError(f"{NAME}.twa_hours must be at most 24")
    tenure = require_number(table, "tenure_years", minimum=1e-9, name=NAME)
    if tenure > require_number(table, "lifetime_years", minimum=1e-9, name=NAME):
        raise ValueError(f"{NAME}.tenure_years must not exceed lifetime_years")


def load_occupational_settings(path: Path | None = None) -> OccupationalSettings:
    """Load and validate the occupational settings.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If a key is missing or invalid; the message names the key.
    """
    table = section(read_toml(path), NAME)
    _check(table)

    def number(key: str) -> float:
        return require_number(table, key, minimum=1e-9, name=NAME)

    return OccupationalSettings(
        shift_inhalation_m3=number("shift_inhalation_m3"),
        daily_inhalation_m3=number("daily_inhalation_m3"),
        worker_days_per_year=number("worker_days_per_year"),
        tenure_years=number("tenure_years"),
        lifetime_years=number("lifetime_years"),
        twa_hours=number("twa_hours"),
        low_volatility_mmhg=number("low_volatility_mmhg"),
        thresholds=_thresholds(table),
        baseline=_tier(table, "baseline"),
        worst_case=_tier(table, "worst_case"),
    )


@lru_cache(maxsize=1)
def get_occupational_settings() -> OccupationalSettings:
    """Return the cached occupational settings from the default file."""
    return load_occupational_settings()
