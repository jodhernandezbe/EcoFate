"""Section 1: the highest risks across the assessed facilities and how many there are."""

from __future__ import annotations

from collections.abc import Callable

from docx.document import Document

from api.schemas.workspace import Extremum, RiskSummary, WorkspaceState
from api.services.report.document import ReportContext, chemical_label, paragraph, table

_HEADER = ("Quantity", "Highest value", "Status", "Facility", "Stack")
_RISKS: tuple[tuple[str, Callable[[RiskSummary], Extremum | None]], ...] = (
    ("Worst-case hazard quotient", lambda risk: risk.hq_worst),
    ("Worst-case lifetime cancer risk", lambda risk: risk.cancer_risk_worst),
    ("Representative hazard quotient", lambda risk: risk.hq_representative),
    ("Representative lifetime cancer risk", lambda risk: risk.cancer_risk_representative),
)
STATUS_LABELS = {"low": "Low", "moderate": "Moderate", "high": "High"}


def _row(
    label: str,
    extremum: Extremum | None,
    reason: str | None,
    ctx: ReportContext,
) -> list[str]:
    if extremum is None:
        return [label, ctx.fmt.absent(reason), "", "", ""]
    name = extremum.facility_name
    facility = f"{name} (FRS {extremum.frs_id})" if name else f"FRS {extremum.frs_id}"
    return [
        label,
        ctx.fmt.number(extremum.value),
        STATUS_LABELS[extremum.status],
        facility,
        str(extremum.stack_number),
    ]


def _uses(state: WorkspaceState, ctx: ReportContext) -> str:
    """The distinct life cycle stages and conditions of use the facilities reported, in order."""
    stages = dict.fromkeys(
        stage
        for f in state.facilities
        for stage in (*f.lifecycle_stages, *(c.lifecycle_stage for c in f.conditions_of_use))
    )
    uses = dict.fromkeys(
        f"{c.cou_category} ({c.lifecycle_stage})"
        for f in state.facilities
        for c in f.conditions_of_use
    )
    return (
        f"Life cycle stages: {'; '.join(stages) or ctx.fmt.absent()}. "
        f"Conditions of use: {'; '.join(uses) or ctx.fmt.absent()}."
    )


def _stack_count(state: WorkspaceState) -> int:
    """The facilities with a community result (the worker-only ones are counted apart)."""
    return sum(1 for f in state.facilities if not f.worker_only)


def _worker_only_count(state: WorkspaceState) -> str:
    count = len(state.facilities) - _stack_count(state)
    return f" Worker-only facilities (no stack release): {count}." if count else ""


def write_summary(doc: Document, state: WorkspaceState, ctx: ReportContext) -> None:
    """The chemical, the number of facilities, their life cycle stages and conditions of use,
    and the highest HQ and cancer risk."""
    paragraph(
        doc,
        f"Chemical: {chemical_label(state.chemical, ctx)}. "
        f"Facilities in this assessment: {_stack_count(state)}.{_worker_only_count(state)}",
    )
    if state.facilities:
        paragraph(doc, _uses(state, ctx))
    risk = state.risk
    rows = [_row(label, pick(risk), risk.reason, ctx) for label, pick in _RISKS]
    table(doc, _HEADER, rows)
