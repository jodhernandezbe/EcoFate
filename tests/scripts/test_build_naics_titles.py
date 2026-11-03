"""Tests for scripts.build_naics_titles (tiny synthetic workbooks, never Census data)."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from scripts.build_naics_titles import main, merge, read_workbook, vintage_of

SHEET = (
    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    "<sheetData>{rows}</sheetData></worksheet>"
)
STRINGS = '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">{items}</sst>'


def _workbook(path: Path, rows: list[tuple[str, str]]) -> Path:
    """A workbook whose first column holds inline numbers and the second shared strings."""
    strings = [title for _, title in rows]
    cells: list[str] = []
    for index, (code, _) in enumerate(rows, start=1):
        cells.append(
            f'<row r="{index}"><c r="A{index}"><v>{code}</v></c>'
            f'<c r="B{index}" t="s"><v>{index - 1}</v></c></row>',
        )
    with zipfile.ZipFile(path, "w") as book:
        book.writestr("xl/worksheets/sheet1.xml", SHEET.format(rows="".join(cells)))
        items = "".join(f"<si><t>{s}</t></si>" for s in strings)
        book.writestr("xl/sharedStrings.xml", STRINGS.format(items=items))
    return path


def test_reads_six_digit_codes_and_trims_titles(tmp_path: Path) -> None:
    book = _workbook(
        tmp_path / "6-digit_2022_Codes.xlsx",
        [
            ("2022 NAICS Code", "2022 NAICS Title"),
            ("111111", " Synthetic  Farming "),
            ("11", "Too short"),
        ],
    )
    assert list(read_workbook(book)) == [("111111", "Synthetic Farming")]


def test_the_newest_vintage_wins(tmp_path: Path) -> None:
    old = _workbook(tmp_path / "6-digit_2017_Codes.xlsx", [("111111", "Old"), ("222222", "Kept")])
    new = _workbook(tmp_path / "6-digit_2022_Codes.xlsx", [("111111", "New")])
    assert merge([new, old]) == {"111111": ("New", 2022), "222222": ("Kept", 2017)}


def test_a_workbook_without_a_vintage_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="vintage"):
        vintage_of(tmp_path / "codes.xlsx")


def test_main_writes_a_reproducible_table(tmp_path: Path) -> None:
    book = _workbook(tmp_path / "6-digit_2022_Codes.xlsx", [("111111", "Synthetic Farming")])
    out = tmp_path / "out" / "titles.csv"
    assert main([str(book), "-o", str(out)]) == 0
    assert (
        out.read_text(encoding="utf-8")
        == "naics_code,naics_title,vintage\n111111,Synthetic Farming,2022\n"
    )
    first = out.read_bytes()
    main([str(book), "-o", str(out)])
    assert out.read_bytes() == first
