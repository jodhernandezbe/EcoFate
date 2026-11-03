"""Tier 2 stack parameters: EPA PSTK defaults by SCC, then the AirToxScreen global default."""

from __future__ import annotations

import csv
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from config.stack import PstkSettings, StackSettings
from tools.digits import digit_string
from tools.emissions.helpers.stack.stack_values import (
    StackRow,
    check_units_convertible,
    stack_values,
)
from tools.schemas import StackParameters, StackSource

GLOBAL_DEFAULT: StackSource = "AirToxScreen global default"
# ASCII digits only: in Python, \d also matches other scripts' digits, which no SCC uses.


@dataclass(frozen=True)
class PstkTable:
    """National PSTK rows keyed by normalized SCC.

    Attributes:
        rows: Normalized SCC -> first national row listed for it.
        duplicates: Normalized SCC -> number of further national rows that were ignored.
    """

    rows: Mapping[str, StackRow]
    duplicates: Mapping[str, int]


# The last table read, keyed by file, modification time and the settings that shape it.
_TABLES: dict[tuple[object, ...], PstkTable] = {}


def normalize_scc(code: str | int) -> str | None:
    """Return the SCC as a digit string, or None if it is not one.

    SCCs have a fixed length (8 digits for point sources), so a code with an extra leading
    zero is a different, unknown code (see ``digit_string``).
    """
    return digit_string(code)


def _is_national(row: StackRow, pstk: PstkSettings) -> bool:
    if pstk.fips_column is None:
        return True
    fips = (row.get(pstk.fips_column) or "").strip()
    return fips == "" or fips in pstk.national_fips


def _check_header(header: list[str] | None, pstk: PstkSettings) -> None:
    """Raise ``ValueError`` when the file lacks a configured column (a setup error)."""
    wanted = [pstk.scc_column, *pstk.columns.values()]
    wanted += [pstk.fips_column] if pstk.fips_column else []
    missing = [column for column in wanted if column not in (header or [])]
    if missing:
        raise ValueError(f"PSTK file {pstk.path} lacks configured columns: {', '.join(missing)}")


def _index_rows(reader: csv.DictReader[str], pstk: PstkSettings) -> PstkTable:
    rows: dict[str, StackRow] = {}
    duplicates: dict[str, int] = {}
    for row in reader:
        scc = normalize_scc(row.get(pstk.scc_column) or "")
        if scc is None or set(scc) == {"0"} or not _is_national(row, pstk):
            continue  # the all-zero row is the file's own global default, not an SCC
        if scc in rows:
            duplicates[scc] = duplicates.get(scc, 0) + 1
        else:
            rows[scc] = MappingProxyType(dict(row))
    return PstkTable(rows=MappingProxyType(rows), duplicates=MappingProxyType(duplicates))


def _read_table(pstk: PstkSettings) -> PstkTable:
    """Read and index the file; raises OSError, csv.Error or UnicodeDecodeError."""
    with pstk.path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        _check_header(list(reader.fieldnames or []), pstk)
        return _index_rows(reader, pstk)


def _cache_key(pstk: PstkSettings, modified_ns: int) -> tuple[object, ...]:
    columns = tuple(pstk.columns.items())
    return (pstk.path, modified_ns, pstk.scc_column, pstk.fips_column, pstk.national_fips, columns)


def _cached_table(pstk: PstkSettings) -> PstkTable:
    """Return the indexed file, read again only when the file or the settings change."""
    key = _cache_key(pstk, pstk.path.stat().st_mtime_ns)
    if key not in _TABLES:
        _TABLES.clear()
        _TABLES[key] = _read_table(pstk)
    return _TABLES[key]


def read_pstk(pstk: PstkSettings) -> tuple[PstkTable | None, str | None]:
    """Return ``(table, None)``, or ``(None, reason)`` when the file is missing or unreadable."""
    try:
        return _cached_table(pstk), None
    except (OSError, csv.Error, UnicodeDecodeError) as exc:
        return None, f"PSTK file {pstk.path} could not be read ({exc.__class__.__name__})"


def _result(
    values: Mapping[str, float],
    source: StackSource,
    scc: str | None,
    warnings: list[str],
) -> StackParameters:
    return StackParameters(
        stack_height=values["stack_height"],
        stack_diameter=values["stack_diameter"],
        exit_velocity=values["exit_velocity"],
        exit_temperature=values["exit_temperature"],
        source=source,
        scc=scc,
        warnings=warnings,
    )


def _fallback(settings: StackSettings, reason: str) -> StackParameters:
    warning = f"{reason}; using the {GLOBAL_DEFAULT} (generic, not facility-specific)"
    return _result(settings.global_fallback, GLOBAL_DEFAULT, None, [warning])


def _duplicate_warning(table: PstkTable, scc: str) -> list[str]:
    extra = table.duplicates.get(scc, 0)
    if not extra:
        return []
    return [f"PSTK lists {extra + 1} national rows for SCC {scc}; the first one was used"]


def _from_pstk(
    scc: str,
    settings: StackSettings,
    aliases: Mapping[str, str] | None,
) -> StackParameters:
    table, problem = read_pstk(settings.pstk)
    if table is None:
        return _fallback(settings, problem or "PSTK file could not be read")
    row = table.rows.get(scc)
    if row is None:
        return _fallback(settings, f"SCC {scc} was not found in PSTK")
    pstk = settings.pstk
    values, problems = stack_values(row, pstk.columns, pstk.units, settings, aliases)
    if values is None:
        return _fallback(settings, f"PSTK row for SCC {scc} is unusable: {'; '.join(problems)}")
    return _result(values, "PSTK", scc, _duplicate_warning(table, scc))


def scc_stack_parameters(
    scc_code: str | int | None,
    settings: StackSettings,
    aliases: Mapping[str, str] | None,
) -> StackParameters:
    """Look up default stack parameters for an SCC, falling back to the global default.

    Args:
        scc_code: Source Classification Code, digits only (surrounding whitespace allowed),
            as text or as an integer; None when no SCC is known, which gives the global
            default without reading PSTK. The code must match a PSTK code exactly.
        settings: PSTK location, columns, units, plausible ranges and the global default.
        aliases: Unit spelling -> Pint-parsable unit string.

    Returns:
        PSTK values (m, m, m/s, K) with ``source`` "PSTK" and the matched ``scc``; otherwise
        the AirToxScreen global default with a warning saying why PSTK was not used. Values
        from the two sources are never mixed.

    Raises:
        ValueError: If the configuration is unusable (unconvertible unit, missing column).
    """
    check_units_convertible(settings.pstk.units, settings, aliases)
    if scc_code is None:
        return _fallback(settings, "no SCC was given")
    scc = normalize_scc(scc_code)
    if scc is None:
        return _fallback(settings, f"SCC {scc_code!r} is invalid (expected digits only)")
    return _from_pstk(scc, settings, aliases)
