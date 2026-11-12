"""Section 4: the facilities, their reported releases and the conditions of use behind them."""

from __future__ import annotations

from docx.document import Document

from api.schemas.workspace import Facility, WorkspaceState
from api.services.report.document import (
    ReportContext,
    bullets,
    empty,
    facility_label,
    subheading,
    table,
)

_FACILITY_HEADER = ("FRS ID", "Name", "Location", "NAICS")
_RELEASE_HEADER = ("FRS ID", "Year", "Medium", "Total release", "Emission rate", "Operating hours")


def _location(facility: Facility, ctx: ReportContext) -> str:
    parts = (facility.address, facility.city, facility.county, facility.state, facility.zip_code)
    return ", ".join(part for part in parts if part) or ctx.fmt.absent()


def _naics(facility: Facility, ctx: ReportContext) -> str:
    industry = facility.industry
    if industry and industry.naics_code:
        return " ".join(p for p in (industry.naics_code, industry.naics_title) if p)
    if facility.naics_subsector:
        title = facility.naics_subsector_title
        return " ".join(p for p in (facility.naics_subsector, title) if p)
    return ctx.fmt.absent()


def _identity(facility: Facility, ctx: ReportContext) -> list[str]:
    name = ctx.fmt.text(facility.name)
    return [facility.frs_id, name, _location(facility, ctx), _naics(facility, ctx)]


def _release(facility: Facility, ctx: ReportContext) -> list[str]:
    fmt = ctx.fmt
    hours = fmt.reported(facility.operating_hours_per_year, "h/yr")
    if facility.operating_hours_source:
        hours = f"{hours} ({facility.operating_hours_source})"
    return [
        facility.frs_id,
        str(facility.reporting_year),
        ctx.fmt.text(facility.medium),
        fmt.reported(facility.total_release, facility.release_unit or ""),
        fmt.number(facility.emission_rate_g_s, "g/s"),
        hours,
    ]


def _conditions(facility: Facility, ctx: ReportContext) -> list[str]:
    label = facility_label(facility)
    if not facility.conditions_of_use:
        return [f"{label}: {ctx.fmt.text(facility.conditions_note)}"]
    return [
        f"{label}: {cou.cou_category} ({cou.lifecycle_stage}; TRI {cou.tri_activity})"
        for cou in facility.conditions_of_use
    ]


def write_releases(doc: Document, state: WorkspaceState, ctx: ReportContext) -> None:
    """Facility and release tables, then the conditions of use per facility."""
    facilities = state.facilities
    if not facilities:
        empty(doc, ctx)
        return
    table(doc, _FACILITY_HEADER, [_identity(f, ctx) for f in facilities])
    doc.add_paragraph()
    table(doc, _RELEASE_HEADER, [_release(f, ctx) for f in facilities])
    subheading(doc, "Conditions of use")
    bullets(doc, [line for f in facilities for line in _conditions(f, ctx)])
