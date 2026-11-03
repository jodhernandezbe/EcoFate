"""Synthetic QPC workbooks for tests: tiny, with obviously fake numbers, built in memory."""

from __future__ import annotations

import io
import zipfile
from xml.sax.saxutils import escape

from scripts.qpc.workbook import Cell, Row

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
TITLE = "TABLE 1. Synthetic plant table: 2026 Quarter 2"
INTRO = (
    "Synthetic introduction. Based on the 2022 edition of the "
    "North American Industry Classification System."
)
HOURS = "Average plant hours per week in operation  "
HEADER_ROWS: list[Row] = [
    (TITLE,),
    (),
    (None, None, None, 2026, None, None, None, 2026, None, None),
    (None, None, None, "Quarter 2", None, None, None, "Quarter 1", None, None),
    (
        "NAICS Code(s)",
        "Description",
        None,
        "Utilization rate ",
        "SE ",
        HOURS,
        "SE",
        "Utilization rate ",
        "SE ",
        HOURS,
    ),
]


def _letters(index: int) -> str:
    return chr(ord("A") + index)


def _cell(ref: str, value: Cell, strings: list[str]) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return f'<c r="{ref}" t="b"><v>{int(value)}</v></c>'
    if isinstance(value, int | float):
        return f'<c r="{ref}"><v>{value!r}</v></c>'
    strings.append(value)
    return f'<c r="{ref}" t="s"><v>{len(strings) - 1}</v></c>'


def _sheet(rows: list[Row], strings: list[str]) -> str:
    body = ""
    for number, row in enumerate(rows, start=1):
        cells = "".join(_cell(f"{_letters(i)}{number}", v, strings) for i, v in enumerate(row))
        body += f'<row r="{number}">{cells}</row>'
    return f'<worksheet xmlns="{MAIN}"><sheetData>{body}</sheetData></worksheet>'


def workbook(sheets: dict[str, list[Row]]) -> bytes:
    """An xlsx whose sheets hold ``rows`` (None cells are omitted, as Excel does)."""
    strings: list[str] = []
    parts = {
        f"xl/worksheets/sheet{i}.xml": _sheet(r, strings) for i, r in enumerate(sheets.values(), 1)
    }
    names = "".join(
        f'<sheet name="{escape(n)}" sheetId="{i}" r:id="rId{i}"/>' for i, n in enumerate(sheets, 1)
    )
    rels = "".join(
        f'<Relationship Id="rId{i}" Target="worksheets/sheet{i}.xml"/>'
        for i in range(1, len(sheets) + 1)
    )
    items = "".join(f"<si><t>{escape(s)}</t></si>" for s in strings)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as book:
        book.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns="{MAIN}" xmlns:r="{REL}"><sheets>{names}</sheets></workbook>',
        )
        book.writestr(
            "xl/_rels/workbook.xml.rels",
            f'<Relationships xmlns="{PKG}">{rels}</Relationships>',
        )
        book.writestr("xl/sharedStrings.xml", f'<sst xmlns="{MAIN}">{items}</sst>')
        for name, xml in parts.items():
            book.writestr(name, xml)
    return buffer.getvalue()


def data_row(code: Cell, title: str | None, hours: Cell, previous: Cell = 5.5) -> Row:
    """A data row: code, description, a flag, then the two quarters' hours at F and J."""
    return (code, title, "c", 1.0, 1.0, hours, 1.0, 1.0, 1.0, previous)


def sheet_rows(*data: Row) -> list[Row]:
    """The header rows followed by ``data`` rows."""
    return [*HEADER_ROWS, (), *data]
