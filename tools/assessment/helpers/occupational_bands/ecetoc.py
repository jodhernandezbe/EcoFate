"""ECETOC TRA tier-1 worker inhalation estimate by process category and volatility band.

Source: ECETOC Technical Report No. 114 (2012), read from the bundled table named in the
``[ecetoc_tra]`` settings. The estimate is for an industrial setting without local exhaust
ventilation; it is banded, not specific to the chemical beyond its vapor pressure band.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType

from config.ecetoc_tra import EcetocTraSettings

BANDS = ("very_low", "low", "moderate", "high")
MAX_HOURS = 24.0
STATEMENT = (
    "ECETOC TRA tier-1 value for a process category and volatility band: not specific to the "
    "chemical beyond its band nor to the facility; no local exhaust ventilation or protective "
    "equipment was assumed."
)


@dataclass(frozen=True)
class Duration:
    """An exposure duration modifier: ``min_hours <= h < max_hours`` takes ``factor``."""

    min_hours: float
    max_hours: float
    factor: float


@dataclass(frozen=True)
class TraTable:
    """The parsed table.

    Attributes:
        estimates: Initial 8-hour estimate, ppm, by (process category, band).
        durations: Exposure duration modifiers, ordered by ``min_hours``, covering [0, 24] h.
    """

    estimates: MappingProxyType[tuple[str, str], float]
    durations: tuple[Duration, ...]


@dataclass(frozen=True)
class BandEstimate:
    """A band estimate for an activity, or the reason there is none.

    Attributes:
        proc: Process category, or None.
        band: Volatility band of the vapor pressure, or None when it could not be set.
        ppm: Estimate, ppm, or None.
        worst_case_mg_m3: 8-hour average with no duration modifier, mg/m^3, or None.
        baseline_mg_m3: 8-hour average with the duration modifier of the activity's hours,
            mg/m^3, or None.
        statement: The label that the value is a banded tier-1 value, or None without a value.
        reason: Why there is no estimate, or None.
    """

    proc: str | None
    band: str | None
    ppm: float | None
    worst_case_mg_m3: float | None
    baseline_mg_m3: float | None
    statement: str | None
    reason: str | None


def _number(text: str, field: str, where: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise ValueError(f"{where}: {field} must be a number, got {text!r}") from None
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{where}: {field} must be finite and non-negative, got {text!r}")
    return value


def _estimate_row(row: dict[str, str], where: str) -> tuple[tuple[str, str], float]:
    proc, band = row["proc"].strip(), row["band"].strip()
    if not proc:
        raise ValueError(f"{where}: an estimate needs a proc")
    if band not in BANDS:
        raise ValueError(f"{where}: band must be one of {', '.join(BANDS)}, got {band!r}")
    if row["unit"].strip() != "ppm":
        raise ValueError(f"{where}: an estimate must be in ppm, got {row['unit']!r}")
    return (proc, band), _number(row["value"], "value", where)


def _duration_row(row: dict[str, str], where: str) -> Duration:
    low = _number(row["min_hours"], "min_hours", where)
    high = _number(row["max_hours"], "max_hours", where)
    if low >= high:
        raise ValueError(f"{where}: min_hours must be below max_hours")
    return Duration(low, high, _number(row["value"], "value", where))


def _check_durations(durations: list[Duration], path: Path) -> tuple[Duration, ...]:
    ordered = tuple(sorted(durations, key=lambda d: d.min_hours))
    edges = [(d.min_hours, d.max_hours) for d in ordered]
    if not edges or edges[0][0] != 0 or edges[-1][1] != MAX_HOURS:
        raise ValueError(f"{path.name}: duration rows must cover 0 to {MAX_HOURS:g} hours")
    if any(before[1] != after[0] for before, after in zip(edges, edges[1:], strict=False)):
        raise ValueError(f"{path.name}: duration rows leave a gap or overlap")
    return ordered


HEADER = ["kind", "proc", "band", "min_hours", "max_hours", "value", "unit"]


def _record(path: Path, number: int, line: str) -> dict[str, str]:
    fields = next(csv.reader([line]))
    if len(fields) != len(HEADER):
        raise ValueError(f"{path.name} line {number}: expected {len(HEADER)} fields")
    return dict(zip(HEADER, fields, strict=True))


def _rows(path: Path) -> list[tuple[int, dict[str, str]]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise FileNotFoundError(f"ECETOC TRA table {path.name} cannot be read: {error}") from error
    lines = [(n, line) for n, line in enumerate(text.splitlines(), 1) if line.strip()]
    data = [(n, line) for n, line in lines if not line.startswith("#")]
    if not data or next(csv.reader([data[0][1]])) != HEADER:
        raise ValueError(f"{path.name}: the header is missing or wrong")
    return [(n, _record(path, n, line)) for n, line in data[1:]]


def parse_table(path: Path) -> TraTable:
    """Parse and validate the table at ``path``.

    Raises:
        FileNotFoundError: If the file cannot be read (the message names it).
        ValueError: If a row is malformed (the message names the file and line) or the duration
            rows do not cover 0 to 24 h without gaps.
    """
    estimates: dict[tuple[str, str], float] = {}
    durations: list[Duration] = []
    for number, row in _rows(path):
        where = f"{path.name} line {number}"
        if row["kind"].strip() == "estimate":
            key, value = _estimate_row(row, where)
            estimates[key] = value
        elif row["kind"].strip() == "duration":
            durations.append(_duration_row(row, where))
        else:
            raise ValueError(f"{where}: kind must be estimate or duration, got {row['kind']!r}")
    return TraTable(MappingProxyType(estimates), _check_durations(durations, path))


@lru_cache(maxsize=4)
def load_table(path: Path) -> TraTable:
    """The table at ``path``, parsed once (the result is immutable)."""
    return parse_table(path)


def volatility_band(vapor_pressure_pa: float, settings: EcetocTraSettings) -> str:
    """Volatility band of a vapor pressure, Pa.

    Very low strictly below the first limit (TR 114: below 0.01 Pa), so a value on it is low; low
    up to and including the second limit; moderate up to and including the third; high above it.

    Raises:
        ValueError: If the vapor pressure is not finite and non-negative.
    """
    if isinstance(vapor_pressure_pa, bool) or not math.isfinite(vapor_pressure_pa):
        raise ValueError(f"vapor_pressure_pa must be finite, got {vapor_pressure_pa!r}")
    if vapor_pressure_pa < 0:
        raise ValueError(f"vapor_pressure_pa must be non-negative, got {vapor_pressure_pa!r}")
    if vapor_pressure_pa < settings.very_low_below_pa:
        return "very_low"
    if vapor_pressure_pa <= settings.low_up_to_pa:
        return "low"
    return "moderate" if vapor_pressure_pa <= settings.moderate_up_to_pa else "high"


def duration_factor(hours: float, table: TraTable) -> float:
    """Duration modifier for ``hours`` per day: the row with ``min_hours <= h < max_hours``.

    24 h belongs to the last row, so a duration on a boundary takes the larger factor.

    Raises:
        ValueError: If ``hours`` is not in [0, 24].
    """
    if isinstance(hours, bool) or not math.isfinite(hours) or not 0 <= hours <= MAX_HOURS:
        raise ValueError(f"hours must be between 0 and {MAX_HOURS:g}, got {hours!r}")
    for row in table.durations:
        if row.min_hours <= hours < row.max_hours:
            return row.factor
    return table.durations[-1].factor


def _none(proc: str | None, band: str | None, reason: str) -> BandEstimate:
    return BandEstimate(proc, band, None, None, None, None, reason)


def estimate(
    proc: str | None,
    vapor_pressure_pa: float,
    molecular_weight: float | None,
    hours: float,
    molar_volume_l_per_mol: float,
    table: TraTable,
    settings: EcetocTraSettings,
) -> BandEstimate:
    """The tier-1 estimate for an activity, or the reason there is none.

    The worst case is ppm x MW / molar volume, mg/m^3 (an 8-hour average with no duration
    modifier); the baseline is that times the duration modifier of ``hours``.

    Args:
        proc: ECETOC process category of the activity, or None.
        vapor_pressure_pa: Vapor pressure at the operating temperature, Pa.
        molecular_weight: Molecular weight, g/mol, or None.
        hours: Hours per day of the activity, h/day.
        molar_volume_l_per_mol: Molar volume of the air, L/mol (mg/m^3 = ppm x MW / molar volume).
        table: The parsed table.
        settings: Band limits.
    """
    band = volatility_band(vapor_pressure_pa, settings)
    if proc is None:
        return _none(None, band, "the activity has no ECETOC process category")
    if molecular_weight is None or not _valid(molecular_weight):
        return _none(proc, band, "the molecular weight is missing or invalid")
    ppm = table.estimates.get((proc, band))
    if ppm is None:
        return _none(proc, band, f"the table has no value for PROC {proc} in the {band} band")
    worst = ppm * molecular_weight / molar_volume_l_per_mol
    baseline = worst * duration_factor(hours, table)
    return BandEstimate(proc, band, ppm, worst, baseline, STATEMENT, None)


def _valid(value: float) -> bool:
    return not isinstance(value, bool) and math.isfinite(value) and value > 0
