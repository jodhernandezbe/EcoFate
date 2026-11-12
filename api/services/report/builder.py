"""Assemble the Word report of a workspace: title block, then sections 1 to 8 in order."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime
from io import BytesIO

from docx.document import Document

from api.schemas.workspace import WorkspaceState
from api.services.report.assessor import write_assessor
from api.services.report.chemical import write_chemical
from api.services.report.document import ReportContext, heading, new_document, title_block
from api.services.report.exposure import write_exposure
from api.services.report.releases import write_releases
from api.services.report.risk import write_risk
from api.services.report.sources import write_sources
from api.services.report.summary import write_summary
from api.services.report.uncertainties import write_uncertainties
from api.services.report.values import ValueFormat
from config.risk_bands import get_risk_bands
from config.ui import UiSettings

Section = Callable[[Document, WorkspaceState, ReportContext], None]

MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
# Sections 1 to 7, built only from the workspace; section 8 is the assistant's answer.
_SECTIONS: tuple[Section, ...] = (
    write_summary,
    write_chemical,
    write_sources,
    write_releases,
    write_exposure,
    write_risk,
    write_uncertainties,
)
_CAS = re.compile(r"^\d{2,7}-\d{2}-\d$")
_NO_CAS = "chemical"


def report_context(settings: UiSettings) -> ReportContext:
    """The report's fixed text, value format and thresholds from the UI settings."""
    report = settings.report
    return ReportContext(
        settings=report,
        fmt=ValueFormat(settings.display.significant_digits, report.not_reported),
        thresholds=get_risk_bands(),
    )


def has_findings(state: WorkspaceState) -> bool:
    """Whether the workspace holds a chemical result or a facility (anything to report)."""
    return state.chemical.cas_number is not None or bool(state.facilities)


def file_name(state: WorkspaceState, ctx: ReportContext, when: datetime) -> str:
    """The attachment name: the configured pattern with a well-formed CAS number and the date."""
    cas = state.chemical.cas_number or ""
    safe = cas if _CAS.match(cas) else _NO_CAS
    return ctx.settings.file_name.format(cas=safe, date=when.date().isoformat())


def build_report(
    state: WorkspaceState,
    answer: str | None,
    ctx: ReportContext,
    when: datetime,
) -> bytes:
    """The ``.docx`` bytes of the report of ``state`` and the assistant's last ``answer``."""
    doc = new_document()
    title_block(doc, ctx, state.chemical, when)
    headings = ctx.settings.headings.ordered()
    for number, (title, write) in enumerate(zip(headings, _SECTIONS, strict=False), start=1):
        heading(doc, number, title)
        write(doc, state, ctx)
    heading(doc, len(_SECTIONS) + 1, headings[len(_SECTIONS)])
    write_assessor(doc, answer, ctx)
    buffer = BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
