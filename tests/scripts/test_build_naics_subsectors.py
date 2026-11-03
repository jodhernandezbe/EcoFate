"""Tests for scripts.build_naics_subsectors (tiny synthetic workbooks, never Census data)."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from scripts.build_naics_subsectors import main, merge, read_workbook

SHEET = (
    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    "<sheetData>{rows}</sheetData></worksheet>"
)
STRINGS = '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">{items}</sst>'


def _workbook(path: Path, rows: list[tuple[str, ...]]) -> Path:
    """A workbook whose cells are all shared strings (the first row is the header)."""
    strings: list[str] = []
    xml_rows: list[str] = []
    for index, row in enumerate(rows, start=1):
        cells: list[str] = []
        for column, text in zip("ABCDE", row, strict=False):
            strings.append(text)
            cells.append(f'<c r="{column}{index}" t="s"><v>{len(strings) - 1}</v></c>')
        xml_rows.append(f'<row r="{index}">{"".join(cells)}</row>')
    with zipfile.ZipFile(path, "w") as book:
        book.writestr("xl/worksheets/sheet1.xml", SHEET.format(rows="".join(xml_rows)))
        items = "".join(f"<si><t>{s}</t></si>" for s in strings)
        book.writestr("xl/sharedStrings.xml", STRINGS.format(items=items))
    return path


def _header(year: int) -> tuple[str, ...]:
    return ("Seq. No.", f"{year} NAICS US   Code", f"{year} NAICS US Title")


def test_only_three_digit_rows_are_kept_and_columns_found_by_header(tmp_path: Path) -> None:
    book = _workbook(
        tmp_path / "2-6_digit_2022_Codes.xlsx",
        [
            _header(2022),
            ("", "", ""),
            ("1", "11", "Sector"),
            ("2", "111", " Synthetic  Crops "),
            ("3", "1111", "Industry group"),
            ("4", "11111", "Industry"),
            ("5", "111110", "National industry"),
            ("6", "31-33", "Range sector"),
            ("7", "12a", "Not digits"),
            ("8", "112", ""),
        ],
    )
    assert list(read_workbook(book)) == [("111", "Synthetic Crops")]


def test_the_leading_sequence_column_is_never_read_as_the_code(tmp_path: Path) -> None:
    book = _workbook(
        tmp_path / "2-6_digit_2022_Codes.xlsx",
        [_header(2022), ("123", "999", "Real code"), ("456", "4", "Seq look-alike")],
    )
    assert list(read_workbook(book)) == [("999", "Real code")]


def test_a_workbook_without_a_header_is_an_error(tmp_path: Path) -> None:
    book = _workbook(tmp_path / "2-6_digit_2022_Codes.xlsx", [("1", "111", "Crops")])
    with pytest.raises(ValueError, match="no header"):
        list(read_workbook(book))


def test_the_newest_vintage_wins_and_older_only_codes_are_kept(tmp_path: Path) -> None:
    old = _workbook(
        tmp_path / "2-6_digit_2017_Codes.xlsx",
        [_header(2017), ("1", "111", "Old title"), ("2", "222", "Only 2017")],
    )
    new = _workbook(
        tmp_path / "2-6_digit_2022_Codes.xlsx",
        [_header(2022), ("1", "111", "New title")],
    )
    assert merge([new, old]) == {"111": ("New title", 2022), "222": ("Only 2017", 2017)}


def test_main_writes_a_sorted_reproducible_file(tmp_path: Path) -> None:
    book = _workbook(
        tmp_path / "2-6_digit_2022_Codes.xlsx",
        [_header(2022), ("1", "325", "Chemical, Synthetic"), ("2", "111", "Crops")],
    )
    first, second = tmp_path / "a.csv", tmp_path / "b.csv"
    assert main([str(book), "-o", str(first)]) == 0
    assert main([str(book), "-o", str(second)]) == 0
    assert first.read_bytes() == second.read_bytes()
    assert first.read_text(encoding="utf-8") == (
        'naics_subsector,title,vintage\n111,Crops,2022\n325,"Chemical, Synthetic",2022\n'
    )
    assert b"\r" not in first.read_bytes()


def test_main_without_workbooks_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("scripts.build_naics_subsectors.RAW_DIR", tmp_path)
    assert main(["-o", str(tmp_path / "x.csv")]) == 1


def test_the_committed_table_is_three_digit_and_has_the_chemical_subsector() -> None:
    from config.industry import get_industry_settings

    lines = get_industry_settings().subsectors_path.read_text(encoding="utf-8").splitlines()
    codes = [line.split(",")[0] for line in lines[1:]]
    assert lines[0] == "naics_subsector,title,vintage"
    assert all(len(code) == 3 and code.isdigit() for code in codes) and codes == sorted(codes)
    assert "325,Chemical Manufacturing,2022" in lines
