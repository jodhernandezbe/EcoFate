"""CDR industrial sector of a facility from its NAICS code, most specific prefix first."""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from functools import lru_cache
from types import MappingProxyType

from commons.prefix import longest_prefix
from config.cdr_sector import CdrSectorSettings
from tools.digits import digit_string
from tools.schemas import CdrSector

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SectorTable:
    """The validated crosswalk: NAICS prefix -> (sector code, sector name, NAICS edition)."""

    rows: MappingProxyType[str, tuple[str, str, str]]
    warnings: tuple[str, ...]


def _row(
    raw: dict[str, str],
    settings: CdrSectorSettings,
) -> tuple[str, tuple[str, str, str]] | None:
    prefix = (raw.get(settings.prefix_column) or "").strip()
    code = (raw.get(settings.code_column) or "").strip()
    name = (raw.get(settings.title_column) or "").strip()
    edition = (raw.get(settings.edition_column) or "").strip()
    valid = prefix.isascii() and prefix.isdigit()
    if not valid or not settings.min_digits <= len(prefix) <= settings.max_digits:
        return None
    if not (code.startswith("IS") and code[2:].isdigit() and name and edition):
        return None
    return prefix, (code, name, edition)


def load_sector_table(settings: CdrSectorSettings) -> SectorTable:
    """Read and validate the crosswalk file.

    A missing or unreadable file, or one without the configured columns, gives an empty table and
    one warning. A row with a bad prefix, code or name, and every row of a repeated prefix, is
    ignored and counted in one warning.
    """
    path = settings.crosswalk_path
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            wanted = {settings.prefix_column, settings.code_column, settings.title_column}
            if not wanted <= set(reader.fieldnames or ()):
                return SectorTable(MappingProxyType({}), (f"{path.name}: missing columns",))
            records = list(reader)
    except (OSError, csv.Error, UnicodeDecodeError) as error:
        return SectorTable(MappingProxyType({}), (f"{path.name} cannot be read: {error}",))
    return _table(records, settings, path.name)


def _table(records: list[dict[str, str]], settings: CdrSectorSettings, name: str) -> SectorTable:
    seen: dict[str, int] = {}
    rows: dict[str, tuple[str, str, str]] = {}
    for raw in records:
        parsed = _row(raw, settings)
        if parsed is not None:
            seen[parsed[0]] = seen.get(parsed[0], 0) + 1
            rows[parsed[0]] = parsed[1]
    kept = {k: v for k, v in rows.items() if seen[k] == 1}
    ignored = len(records) - len(kept)
    note = (f"{name}: ignored {ignored} unusable rows",) if ignored else ()
    return SectorTable(MappingProxyType(kept), note)


@lru_cache(maxsize=4)
def get_sector_table(settings: CdrSectorSettings) -> SectorTable:
    """The table for ``settings``, read once per process; problems are logged once."""
    table = load_sector_table(settings)
    for message in table.warnings:
        logger.warning("CDR sector crosswalk: %s", message)
    return table


def sector_for(
    naics_code: str | None,
    table: SectorTable,
    settings: CdrSectorSettings,
) -> tuple[CdrSector | None, str | None]:
    """The sector of ``naics_code`` and None, or None and why there is none; never raises."""
    code = digit_string(naics_code) if naics_code is not None else None
    if code is None or not 2 <= len(code) <= settings.max_digits:
        return None, "no usable NAICS code"
    if not table.rows:
        return None, "CDR sector crosswalk unavailable"
    hit = longest_prefix(table.rows, code, min_length=settings.min_digits)
    if hit is None:
        return None, f"EPA's crosswalk has no industrial sector for NAICS {code}"
    prefix, (sector, name, edition) = hit
    return CdrSector(
        code=sector,
        name=name,
        matched_naics_prefix=prefix,
        naics_edition=edition,
    ), None
