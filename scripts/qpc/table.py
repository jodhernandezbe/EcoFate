"""Find the hours column of the requested quarter in the utilization sheet and read its rows."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from config.qpc import QpcSettings
from scripts.qpc.codes import clean_cell, four_digit_codes, parse_codes
from scripts.qpc.errors import QpcDataError, QpcLayoutError, RowSkipped
from scripts.qpc.release import Release
from scripts.qpc.workbook import Cell, Row

QUARTER_LABEL = re.compile(r"quarter\s*([1-4])")
YEAR_RANGE = range(1900, 2200)
WITHHELD = "D"


@dataclass(frozen=True)
class Entry:
    """A kept row: the hours (h/week) of every four-digit code the published row covers."""

    source_naics: str
    source_title: str
    hours: float
    codes: tuple[str, ...]


@dataclass(frozen=True)
class Skipped:
    """A row left out of the baseline, and why."""

    source_naics: str
    source_title: str
    reason: str


@dataclass(frozen=True)
class Extraction:
    """What was read: kept rows and skipped rows, both in sheet order."""

    entries: tuple[Entry, ...]
    skipped: tuple[Skipped, ...]


def norm(cell: Cell) -> str:
    """A label with whitespace collapsed and case ignored; empty for a non-text cell."""
    return " ".join(cell.split()).casefold() if isinstance(cell, str) else ""


def _cell(row: Row, index: int) -> Cell:
    return row[index] if 0 <= index < len(row) else None


def check_title(rows: Sequence[Row], release: Release, settings: QpcSettings) -> None:
    """The sheet's title cell must name the requested year and quarter."""
    text = next((c for row in rows[:3] for c in row if isinstance(c, str) and c.strip()), None)
    found = settings.title_pattern.search(text) if text else None
    if found is None:
        raise QpcLayoutError(f"sheet title {text!r} does not name a year and quarter")
    got = (int(found.group("year")), int(found.group("quarter")))
    if got != (release.year, release.quarter):
        raise QpcLayoutError(f"asked for {release.label} but the sheet is {got[0]}Q{got[1]}")


def check_edition(rows: Sequence[Row], settings: QpcSettings) -> None:
    """The introduction must state the configured NAICS edition."""
    for row in rows:
        for cell in row:
            found = settings.naics_edition_pattern.search(cell) if isinstance(cell, str) else None
            if found:
                _same_edition(int(found.group("edition")), settings.naics_edition)
                return
    raise QpcLayoutError(f"the {settings.intro_sheet_name!r} sheet does not state a NAICS edition")


def _same_edition(stated: int, wanted: int) -> None:
    if stated != wanted:
        raise QpcLayoutError(f"workbook uses NAICS {stated}, expected {wanted}; codes differ")


def find_header(rows: Sequence[Row], settings: QpcSettings) -> tuple[int, int]:
    """(row index, column index) of the code header within the first configured rows."""
    wanted = norm(settings.code_header)
    for index, row in enumerate(rows[: settings.header_search_rows]):
        for column, cell in enumerate(row):
            if norm(cell) == wanted:
                return index, column
    raise QpcLayoutError(f"header {settings.code_header!r} not found in the first rows")


def _quarter_labels(row: Row) -> dict[int, int]:
    labels: dict[int, int] = {}
    for column, cell in enumerate(row):
        found = QUARTER_LABEL.fullmatch(norm(cell))
        if found:
            labels[column] = int(found.group(1))
    return labels


def _block(rows: Sequence[Row], header: int, release: Release) -> tuple[int, int | None]:
    """(first column, column after the last) of the requested quarter's block."""
    for index in range(header - 1, -1, -1):
        labels = _quarter_labels(rows[index])
        if labels:
            return _pick(rows, index, labels, release)
    raise QpcLayoutError("no 'Quarter N' row above the header")


def _pick(
    rows: Sequence[Row],
    at: int,
    labels: Mapping[int, int],
    release: Release,
) -> tuple[int, int | None]:
    starts = sorted(labels)
    mine = [c for c in starts if labels[c] == release.quarter]
    if len(mine) != 1:
        raise QpcLayoutError(
            f"{release.label}: quarters in the sheet are {sorted(labels.values())}",
        )
    years = {
        c for row in rows[:at] if isinstance(c := _cell(row, mine[0]), int) and c in YEAR_RANGE
    }
    if years != {release.year}:
        raise QpcLayoutError(f"{release.label}: the block is headed by year {sorted(years)}")
    later = [c for c in starts if c > mine[0]]
    return mine[0], (later[0] if later else None)


def find_hours_column(rows: Sequence[Row], header: int, release: Release, wanted: str) -> int:
    """The column of the hours header inside the requested quarter's block."""
    first, stop = _block(rows, header, release)
    row = rows[header]
    matches = [
        c for c in range(first, len(row) if stop is None else stop) if norm(row[c]) == norm(wanted)
    ]
    if len(matches) != 1:
        raise QpcLayoutError(
            f"{wanted!r} appears {len(matches)} times in the {release.label} block",
        )
    return matches[0]


def valid_hours(value: Cell, settings: QpcSettings) -> float:
    """The hours (h/week) if plausible.

    Raises:
        RowSkipped: If the value is withheld, not a finite number, or outside the bounds.
    """
    if isinstance(value, str) and value.strip() == WITHHELD:
        raise RowSkipped("estimate withheld (D)")
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise RowSkipped(f"hours are not a finite number: {value!r}")
    if not settings.min_hours < value <= settings.max_hours_per_week:
        raise RowSkipped(
            f"hours {value} outside ({settings.min_hours}, {settings.max_hours_per_week}]",
        )
    return float(value)


def _title(row: Row, column: int) -> str:
    text = _cell(row, column)
    return " ".join(text.split()) if isinstance(text, str) else ""


def _classify(
    row: Row,
    columns: tuple[int, int],
    settings: QpcSettings,
    children: Mapping[str, tuple[str, ...]],
) -> Entry | Skipped | None:
    """A kept entry, a skipped row, or None for a footnote or blank line."""
    code_col, hours_col = columns
    cell, title = _cell(row, code_col), _title(row, code_col + 1)
    hours = _cell(row, hours_col)
    if cell is None or isinstance(cell, bool):
        return Skipped("", title, "no NAICS code") if hours is not None else None
    source = clean_cell(cell)
    try:
        codes = parse_codes(cell)
    except ValueError as error:
        return Skipped(source, title, str(error)) if (title or hours is not None) else None
    if not title:
        raise QpcDataError(f"code {source!r} has no description; the layout may have changed")
    return _entry(source, title, codes, (hours, settings, children))


def _entry(
    source: str,
    title: str,
    codes: tuple[str, ...],
    context: tuple[Cell, QpcSettings, Mapping[str, tuple[str, ...]]],
) -> Entry | Skipped:
    hours, settings, children = context
    try:
        covered = four_digit_codes(codes, children)
        return Entry(source, title, valid_hours(hours, settings), covered)
    except RowSkipped as skip:
        return Skipped(source, title, skip.reason)


def drop_overlaps(entries: Sequence[Entry]) -> tuple[list[Entry], list[Skipped]]:
    """Remove every row that shares a four-digit code with another row."""
    owners: dict[str, list[int]] = {}
    for index, entry in enumerate(entries):
        for code in entry.codes:
            owners.setdefault(code, []).append(index)
    clash = {i for ids in owners.values() if len(ids) > 1 for i in ids}
    kept = [e for i, e in enumerate(entries) if i not in clash]
    lost = [
        Skipped(e.source_naics, e.source_title, "overlaps another row")
        for i, e in enumerate(entries)
        if i in clash
    ]
    return kept, lost


def extract(
    rows: Sequence[Row],
    release: Release,
    settings: QpcSettings,
    children: Mapping[str, tuple[str, ...]],
) -> Extraction:
    """Read the sheet's rows into kept and skipped rows.

    Raises:
        QpcLayoutError: If the title, header, quarter block or hours column is not as asked.
        QpcDataError: If no data row is found, a code has no description, or fewer than
            ``min_codes`` four-digit codes remain.
    """
    check_title(rows, release, settings)
    header, code_col = find_header(rows, settings)
    hours_col = find_hours_column(rows, header, release, settings.hours_header)
    seen = [_classify(r, (code_col, hours_col), settings, children) for r in rows[header + 1 :]]
    entries = [x for x in seen if isinstance(x, Entry)]
    skipped = [x for x in seen if isinstance(x, Skipped)]
    if not entries and not skipped:
        raise QpcDataError("no data rows found under the header")
    kept, lost = drop_overlaps(entries)
    result = Extraction(tuple(kept), tuple(skipped + lost))
    _enough(result, settings)
    return result


def _enough(result: Extraction, settings: QpcSettings) -> None:
    count = sum(len(e.codes) for e in result.entries)
    if count < settings.min_codes:
        raise QpcDataError(
            f"only {count} four-digit codes found; at least {settings.min_codes} expected",
        )
