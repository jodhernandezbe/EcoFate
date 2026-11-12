"""Building blocks of the Word report: title block, numbered headings, paragraphs and tables."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

import docx
from docx.document import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import nsdecls
from docx.oxml.parser import parse_xml
from docx.shared import Inches
from docx.text.paragraph import Paragraph

from api.schemas.workspace import Chemical, Facility
from api.services.report.values import ValueFormat
from config.report import ReportSettings
from config.risk_bands import RiskBands

_TABLE_STYLE = "Table Grid"
_DATE_FORMAT = "%Y-%m-%d %H:%M"
_LOGO_HEIGHT = Inches(0.4)
_PAGE_FIELDS = {"{page}": "PAGE", "{pages}": "NUMPAGES"}
_PAGE_PARTS = re.compile(r"(\{pages?\})")


@dataclass(frozen=True)
class ReportContext:
    """What every section needs besides the workspace: fixed text, formats and thresholds."""

    settings: ReportSettings
    fmt: ValueFormat
    thresholds: RiskBands


def new_document() -> Document:
    """An empty document on the default template."""
    return docx.Document()


def chemical_label(chemical: Chemical, ctx: ReportContext) -> str:
    """``Name (CAS n)``, the CAS number alone, or absent."""
    cas = f"CAS {chemical.cas_number}" if chemical.cas_number else None
    if chemical.name and cas:
        return f"{chemical.name} ({cas})"
    return chemical.name or cas or ctx.fmt.absent()


def facility_label(facility: Facility) -> str:
    """``Name (FRS id)``, or the FRS ID alone when the facility has no name."""
    return f"{facility.name} (FRS {facility.frs_id})" if facility.name else f"FRS {facility.frs_id}"


def page_header(doc: Document, ctx: ReportContext) -> None:
    """The header of every page: the app logo beside the app name."""
    line = doc.sections[0].header.paragraphs[0]
    line.add_run().add_picture(str(ctx.settings.logo), height=_LOGO_HEIGHT)
    line.add_run(f"  {ctx.settings.brand}").bold = True


def _field(line: Paragraph, instruction: str) -> None:
    """A Word field (``PAGE`` or ``NUMPAGES``) that Word fills in when it lays the pages out."""
    # ``instruction`` is one of the fixed values of _PAGE_FIELDS, never workspace text.
    field = parse_xml(
        f'<w:fldSimple {nsdecls("w")} w:instr="{instruction}">'
        "<w:r><w:t>1</w:t></w:r></w:fldSimple>",
    )
    line._p.append(field)  # pyright: ignore[reportPrivateUsage]  # python-docx has no field API


def page_footer(doc: Document, ctx: ReportContext) -> None:
    """The footer of every page: the configured label with the page number and the page count."""
    line = doc.sections[0].footer.paragraphs[0]
    line.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for part in _PAGE_PARTS.split(ctx.settings.page_label):
        if part in _PAGE_FIELDS:
            _field(line, _PAGE_FIELDS[part])
        elif part:
            line.add_run(part)


def title_block(doc: Document, ctx: ReportContext, chemical: Chemical, when: datetime) -> None:
    """Page header and footer, then title, chemical, generation time and the disclaimer."""
    page_header(doc, ctx)
    page_footer(doc, ctx)
    doc.add_heading(ctx.settings.title, level=0)
    doc.add_paragraph().add_run(chemical_label(chemical, ctx)).bold = True
    doc.add_paragraph(f"Generated {when.strftime(_DATE_FORMAT)}")
    doc.add_paragraph().add_run(ctx.settings.disclaimer).italic = True


def heading(doc: Document, number: int, text: str) -> None:
    """A numbered section heading, e.g. ``2. Chemical identity and properties``."""
    doc.add_heading(f"{number}. {text}", level=1)


def subheading(doc: Document, text: str) -> None:
    """A heading inside a section (one facility, one topic)."""
    doc.add_heading(text, level=2)


def paragraph(doc: Document, text: str, *, italic: bool = False) -> None:
    """One paragraph of plain text."""
    doc.add_paragraph().add_run(text).italic = italic


def bullets(doc: Document, items: Sequence[str]) -> None:
    """A bulleted list, one item per entry."""
    for item in items:
        doc.add_paragraph(item, style="List Bullet")


def empty(doc: Document, ctx: ReportContext) -> None:
    """The configured sentence of a section with no data."""
    paragraph(doc, ctx.settings.empty_section, italic=True)


def table(doc: Document, header: Sequence[str], rows: Sequence[Sequence[str]]) -> None:
    """A grid table with a bold header row and one row per entry of ``rows``."""
    grid = doc.add_table(rows=1, cols=len(header))
    grid.style = _TABLE_STYLE
    for cell, text in zip(grid.rows[0].cells, header, strict=True):
        cell.paragraphs[0].add_run(text).bold = True
    for row in rows:
        for cell, text in zip(grid.add_row().cells, row, strict=True):
            cell.text = text
