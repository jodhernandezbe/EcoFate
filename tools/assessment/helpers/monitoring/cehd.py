"""Look up measured workplace air concentrations in the bundled OSHA CEHD summary.

The summary (``scripts/build_osha_cehd_summary.py``) holds, per OSHA IMIS substance code, NAICS
prefix and unit, the number of personal-sample values, the non-detects, the median and the 95th
percentile. A chemical is found through the bundled IMIS-CAS crosswalk (by CAS number only, never
by name). The lookup tries the facility's NAICS code from the most specific configured prefix
down to the shortest and uses the first level with enough values. A ppm result is converted to
mg/m^3 with ``mg/m^3 = ppm * molecular weight (g/mol) / molar volume (L/mol)`` (the molar volume
is configured: 24.45 L/mol at 25 degC and 1 atm). Nothing is requested from OSHA here.
"""

from __future__ import annotations

import csv
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType

from config.osha_cehd import OshaCehdSettings, get_osha_cehd_settings

MG_M3 = "mg/m^3"
PPM = "ppm"
SOURCE = "OSHA Chemical Exposure Health Data (personal air samples taken at OSHA inspections)"
BELOW_DETECTION = "below detection"
STATEMENTS = (
    "The samples come from OSHA inspections of this industry, not from the facility assessed.",
    "OSHA inspections are targeted, so the samples are not a representative sample of the "
    "industry.",
)
SUMMARY_FIELDS = ("imis", "naics_prefix", "unit", "n", "n_nd", "median", "p95")

Key = tuple[str, str, str]


@dataclass(frozen=True)
class SummaryRow:
    """One line of the summary file.

    Attributes:
        n: Number of values (one per sampling number).
        n_nd: How many of them are non-detects.
        median: Median of the values, in ``unit``.
        p95: 95th percentile of the values, in ``unit``.
        unit: ``mg/m^3`` or ``ppm``.
    """

    imis: str
    naics_prefix: str
    unit: str
    n: int
    n_nd: int
    median: float
    p95: float
    first_year: int
    last_year: int


@dataclass(frozen=True)
class MonitoringTable:
    """The loaded summary and crosswalk (immutable)."""

    rows: Mapping[Key, SummaryRow]
    imis_by_cas: Mapping[str, tuple[str, ...]]
    window: str


@dataclass(frozen=True)
class MonitoringResult:
    """What the monitoring data says about a chemical in a facility's industry.

    Attributes:
        available: Whether measured values are returned.
        reason: Why none are returned, or why the median is missing; None otherwise.
        imis_code: OSHA substance code used.
        naics_level: The NAICS prefix used.
        level_digits: Its length.
        level_note: Says when a broader level than the facility's own was used.
        n_values: Number of values at the level.
        n_nondetect: How many are non-detects.
        median_mg_m3: Median, mg/m^3; None when below detection.
        p95_mg_m3: 95th percentile, mg/m^3.
        original_unit: Unit the row was stored in (``mg/m^3`` or ``ppm``).
        unit_note: Says which unit was used when both had rows.
        first_year: First year sampled.
        last_year: Last year sampled.
        n_found: Values found at the broadest level tried (set when none are returned).
        source: Where the data come from.
        statements: The limits of the data.
    """

    available: bool
    reason: str | None = None
    imis_code: str | None = None
    naics_level: str | None = None
    level_digits: int | None = None
    level_note: str | None = None
    n_values: int | None = None
    n_nondetect: int | None = None
    median_mg_m3: float | None = None
    p95_mg_m3: float | None = None
    original_unit: str | None = None
    unit_note: str | None = None
    first_year: int | None = None
    last_year: int | None = None
    n_found: int | None = None
    source: str = SOURCE
    statements: tuple[str, ...] = STATEMENTS


def _data_lines(path: Path) -> list[str]:
    with path.open(encoding="utf-8", newline="") as handle:
        return [line for line in handle if line.strip()]


def _summary_row(record: Mapping[str, str]) -> SummaryRow:
    try:
        row = SummaryRow(
            imis=record["imis"],
            naics_prefix=record["naics_prefix"],
            unit=record["unit"],
            n=int(record["n"]),
            n_nd=int(record["n_nd"]),
            median=float(record["median"]),
            p95=float(record["p95"]),
            first_year=int(record["first_year"]),
            last_year=int(record["last_year"]),
        )
    except (KeyError, ValueError) as error:
        raise ValueError(f"malformed OSHA summary row {dict(record)}: {error}") from error
    _check(row)
    return row


def _check(row: SummaryRow) -> None:
    if row.unit not in (MG_M3, PPM) or row.n < 1 or not 0 <= row.n_nd <= row.n:
        raise ValueError(f"inconsistent OSHA summary row {row}")
    if not (math.isfinite(row.median) and math.isfinite(row.p95)):
        raise ValueError(f"non-finite value in OSHA summary row {row}")


def read_summary(path: Path) -> tuple[dict[Key, SummaryRow], str]:
    """Read the summary file: its rows by (IMIS code, NAICS prefix, unit) and its ``#`` line."""
    lines = _data_lines(path)
    comments = [line.lstrip("# ").strip() for line in lines if line.startswith("#")]
    body = [line for line in lines if not line.startswith("#")]
    rows = (_summary_row(r) for r in csv.DictReader(body))
    return {(r.imis, r.naics_prefix, r.unit): r for r in rows}, " ".join(comments)


def read_crosswalk(path: Path) -> dict[str, tuple[str, ...]]:
    """Read the crosswalk: CAS number -> the IMIS codes OSHA gives it, ascending."""
    by_cas: dict[str, set[str]] = {}
    for record in csv.DictReader(_data_lines(path)):
        by_cas.setdefault(record["cas"], set()).add(record["imis_code"])
    return {cas: tuple(sorted(codes)) for cas, codes in by_cas.items()}


def load_table(summary_path: Path, crosswalk_path: Path) -> MonitoringTable:
    """Load both files (raises ``FileNotFoundError`` or ``ValueError`` on a bad file)."""
    rows, window = read_summary(summary_path)
    return MonitoringTable(
        MappingProxyType(rows),
        MappingProxyType(read_crosswalk(crosswalk_path)),
        window,
    )


@lru_cache(maxsize=4)
def _cached(summary_path: Path, crosswalk_path: Path) -> MonitoringTable:
    return load_table(summary_path, crosswalk_path)


def get_table(settings: OshaCehdSettings | None = None) -> MonitoringTable:
    """The table of the configured files, read once and then reused (it is immutable)."""
    resolved = settings or get_osha_cehd_settings()
    return _cached(resolved.summary_path, resolved.crosswalk_path)


def _candidates(table: MonitoringTable, codes: Iterable[str], prefix: str) -> list[SummaryRow]:
    found = (table.rows.get((code, prefix, unit)) for code in codes for unit in (MG_M3, PPM))
    return [row for row in found if row is not None]


def _best(rows: list[SummaryRow]) -> SummaryRow:
    return max(rows, key=lambda r: (r.n, r.unit == MG_M3, r.imis))


def _convert(value: float, unit: str, molecular_weight: float, molar_volume: float) -> float:
    """mg/m^3 from a stored value: unchanged, or ppm * g/mol / (L/mol)."""
    return value if unit == MG_M3 else value * molecular_weight / molar_volume


def _unit_note(rows: list[SummaryRow], chosen: SummaryRow) -> str | None:
    if len(rows) < 2:
        return None
    others = ", ".join(f"{r.imis} in {r.unit}: {r.n} values" for r in rows if r is not chosen)
    return f"Used {chosen.imis} in {chosen.unit} ({chosen.n} values), the most values; {others}."


def _usable_weight(value: float | None) -> float | None:
    if value is None or isinstance(value, bool) or not math.isfinite(value) or value <= 0:
        return None
    return float(value)


def _level_note(naics: str, digits: int, first_digits: int) -> str | None:
    if digits == first_digits:
        return None
    return f"NAICS {naics} has too few values; the {digits}-digit prefix {naics[:digits]} was used."


def _statements(table: MonitoringTable, row: SummaryRow) -> tuple[str, ...]:
    years = f"Years covered: {row.first_year} to {row.last_year}"
    counts = f"{row.n} values, {row.n_nd} non-detects"
    return (*STATEMENTS, f"{years}; {counts}.", f"Summary window: {table.window}.")


def _converted(row: SummaryRow, weight: float, molar_volume: float) -> tuple[float | None, float]:
    """(median, 95th percentile) in mg/m^3; the median is None when mostly non-detects."""
    p95 = _convert(row.p95, row.unit, weight, molar_volume)
    if row.n_nd * 2 > row.n:
        return None, p95
    return _convert(row.median, row.unit, weight, molar_volume), p95


def _result(
    table: MonitoringTable,
    chosen: SummaryRow,
    rows: list[SummaryRow],
    level: tuple[int, str | None],
    values: tuple[float | None, float],
) -> MonitoringResult:
    """The result for ``chosen``; ``level`` is (digits used, note), ``values`` (median, p95)."""
    return MonitoringResult(
        available=True,
        reason=BELOW_DETECTION if values[0] is None else None,
        imis_code=chosen.imis,
        naics_level=chosen.naics_prefix,
        level_digits=level[0],
        level_note=level[1],
        n_values=chosen.n,
        n_nondetect=chosen.n_nd,
        median_mg_m3=values[0],
        p95_mg_m3=values[1],
        original_unit=chosen.unit,
        unit_note=_unit_note(rows, chosen),
        first_year=chosen.first_year,
        last_year=chosen.last_year,
        statements=_statements(table, chosen),
    )


def _none(reason: str, n_found: int | None = None) -> MonitoringResult:
    return MonitoringResult(
        available=False,
        reason=f"No monitoring data: {reason}.",
        n_found=n_found,
    )


def lookup(
    cas: str,
    naics: str,
    molecular_weight: float | None,
    settings: OshaCehdSettings,
    table: MonitoringTable | None = None,
) -> MonitoringResult:
    """Measured air concentrations of a chemical in a facility's industry.

    Args:
        cas: The chemical's CAS number; matched exactly to OSHA's crosswalk (never by name).
        naics: The facility's primary NAICS code (digits).
        molecular_weight: The chemical's molecular weight, g/mol (needed only for ppm rows).
        settings: The ``[osha_cehd]`` settings (prefix lengths, minimum values, molar volume).
        table: The loaded data; the configured bundled files when None.

    Returns:
        A ``MonitoringResult``: the level, values, non-detects, median and 95th percentile in
        mg/m^3, years and the limits of the data; or ``available=False`` with the reason.
    """
    loaded = table if table is not None else get_table(settings)
    codes = loaded.imis_by_cas.get(cas.strip())
    if not codes:
        return _none(f"OSHA's data has no substance with CAS number {cas.strip() or '(none)'}")
    digits = naics.strip()
    if not digits.isdigit():
        return _none("the facility has no NAICS code")
    return _by_level(loaded, codes, digits, molecular_weight, settings)


def _by_level(
    table: MonitoringTable,
    codes: tuple[str, ...],
    naics: str,
    molecular_weight: float | None,
    settings: OshaCehdSettings,
) -> MonitoringResult:
    lengths = settings.naics_prefix_lengths
    found = 0
    for digits in (n for n in lengths if len(naics) >= n):
        rows = _candidates(table, codes, naics[:digits])
        found = max([found, *(r.n for r in rows)])
        enough = [r for r in rows if r.n >= settings.min_values]
        if enough:
            note = _level_note(naics, digits, lengths[0])
            return _at_level(table, enough, (digits, note), molecular_weight, settings)
    return _none(
        f"{found} values found for NAICS {naics} down to {lengths[-1]} digits, "
        f"and at least {settings.min_values} are needed",
        found,
    )


def _at_level(
    table: MonitoringTable,
    rows: list[SummaryRow],
    level: tuple[int, str | None],
    molecular_weight: float | None,
    settings: OshaCehdSettings,
) -> MonitoringResult:
    chosen, weight = _best(rows), _usable_weight(molecular_weight)
    if chosen.unit == PPM and weight is None:
        return _none(
            "the monitoring values are in ppm and the molecular weight of the chemical is "
            "missing, so they cannot be converted to mg/m^3",
        )
    values = _converted(chosen, weight or 0.0, settings.molar_volume_l_per_mol)
    return _result(table, chosen, rows, level, values)
