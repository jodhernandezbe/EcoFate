"""Build the NAICS subsector title table from the Census Bureau's 2-6 digit code lists.

The Census Bureau publishes one workbook per NAICS vintage (``2-6 digit_2022_Codes.xlsx``,
``2-6 digit_2017_Codes.xlsx``, from https://www.census.gov/naics/) listing every level of the
classification, with a leading sequence-number column, so the code and title columns are found by
their header text. Only three-digit codes (subsectors, e.g. 325 Chemical Manufacturing) are kept.
TRI submissions carry codes of whichever vintage was current when they were filed, so the lists
are merged into one table, one row per code; the newest vintage's title wins and the row says
which vintage it came from.

Usage: ``uv run python -m scripts.build_naics_subsectors [workbook ...] [-o output]``
Defaults: every ``2-6_digit_*.xlsx`` in ``data/raw/naics`` -> ``[industry].subsectors_path``.
"""

from __future__ import annotations

import argparse
import csv
import sys
import zipfile
from collections.abc import Iterable, Iterator
from pathlib import Path
from xml.etree import ElementTree

from config.industry import get_industry_settings
from scripts.build_naics_titles import NS, RAW_DIR, row_cells, shared_strings, vintage_of
from tools.digits import digit_string

SUBSECTOR_LENGTH = 3


def _header_columns(cells: list[str]) -> tuple[int, int] | None:
    """(code column, title column) if the row is the header: words "code" and "title"."""
    words = [" ".join(cell.split()).casefold() for cell in cells]
    code = next((i for i, w in enumerate(words) if "naics" in w and w.endswith("code")), None)
    title = next((i for i, w in enumerate(words) if "naics" in w and w.endswith("title")), None)
    return (code, title) if code is not None and title is not None else None


def read_workbook(path: Path) -> Iterator[tuple[str, str]]:
    """Yield (code, title) of the three-digit rows of the first sheet.

    Raises:
        ValueError: If no header row names a NAICS code column and a NAICS title column.
    """
    with zipfile.ZipFile(path) as book:
        strings = shared_strings(book)
        sheet = ElementTree.fromstring(book.read("xl/worksheets/sheet1.xml"))  # noqa: S314  # trusted local file
    columns: tuple[int, int] | None = None
    for row in sheet.iter(f"{{{NS['m']}}}row"):
        cells = row_cells(row, strings)
        columns = columns or _header_columns(cells)
        if columns is not None and max(columns) < len(cells):
            yield from _subsector(cells[columns[0]], cells[columns[1]])
    if columns is None:
        raise ValueError(f"{path.name} has no header naming a NAICS code and a NAICS title column")


def _subsector(raw_code: str, raw_title: str) -> Iterator[tuple[str, str]]:
    code, title = raw_code.strip(), " ".join(raw_title.split())
    if title and digit_string(code) == code and code.isascii() and len(code) == SUBSECTOR_LENGTH:
        yield code, title


def merge(books: Iterable[Path]) -> dict[str, tuple[str, int]]:
    """Code -> (title, vintage), the newest vintage winning; sorted by code."""
    titles: dict[str, tuple[str, int]] = {}
    for path in sorted(books, key=vintage_of):
        year = vintage_of(path)
        for code, title in read_workbook(path):
            titles[code] = (title, year)
    return dict(sorted(titles.items()))


def write_table(titles: dict[str, tuple[str, int]], output: Path, columns: tuple[str, str]) -> None:
    """Write the table as UTF-8 CSV with Unix line endings (byte-for-byte reproducible)."""
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow([columns[0], columns[1], "vintage"])
        for code, (title, year) in titles.items():
            writer.writerow([code, title, year])


def main(argv: list[str] | None = None) -> int:
    settings = get_industry_settings()
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("workbooks", nargs="*", type=Path, help="Census 2-6 digit code workbooks")
    parser.add_argument("-o", "--output", type=Path, default=settings.subsectors_path)
    args = parser.parse_args(argv)
    books = args.workbooks or sorted(RAW_DIR.glob("2-6_digit_*.xlsx"))
    if not books:
        print(f"no workbooks given and none found in {RAW_DIR}", file=sys.stderr)
        return 1
    titles = merge(books)
    write_table(
        titles,
        args.output,
        (settings.subsectors_code_column, settings.subsectors_title_column),
    )
    print(f"wrote {len(titles)} subsectors from {len(books)} workbook(s) to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
