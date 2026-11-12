"""Section 6: risk by TSCA life cycle stage and condition of use, then per facility risk ranges,
status and screening outcome, with the thresholds used."""

from __future__ import annotations

from docx.document import Document

from api.schemas.workspace import ConditionOfUse, Extreme, Facility, Screening, WorkspaceState
from api.services.report.document import (
    ReportContext,
    empty,
    facility_label,
    paragraph,
    subheading,
    table,
)
from api.services.report.summary import STATUS_LABELS

_COU_HEADER = (
    "Life cycle stage",
    "Condition of use",
    "TRI activity",
    "Facility",
    "Hazard quotient, worst case",
    "Cancer risk, worst case",
    "Status",
)
_COU_NOTE = (
    "Risk is estimated per facility, not per condition of use: a facility that reports several "
    "conditions of use appears under each with the same values."
)
_RISK_HEADER = (
    "Facility",
    "Hazard quotient, worst case",
    "Cancer risk, worst case",
    "Hazard quotient, representative",
    "Cancer risk, representative",
    "Status",
)
_SCREENING_HEADER = ("Facility", "Outcome", "Screening HQ", "Screening cancer risk", "Reason")
_OUTCOMES = {
    "full": "Fully assessed",
    "worst_case_only": "Worst case only",
    "screened_out_at_bound": "Screened out at the conservative bound",
    "screened_out_with_own_stacks": "Screened out with its own stacks",
    "not_assessed": "Not assessed",
}


def _thresholds(ctx: ReportContext) -> str:
    t, number = ctx.thresholds, ctx.fmt.number
    return (
        "Screening priority bands, not findings. Hazard quotient: low below "
        f"{number(t.hq_lower)}, moderate from {number(t.hq_lower)}, high from "
        f"{number(t.hq_upper)}. Lifetime cancer risk: low below {number(t.cancer_risk_lower)}, "
        f"moderate from {number(t.cancer_risk_lower)}, high from {number(t.cancer_risk_upper)}."
    )


def _span(extreme: Extreme | None, ctx: ReportContext) -> str:
    return ctx.fmt.absent() if extreme is None else ctx.fmt.span(extreme.low, extreme.high)


def _status(facility: Facility, ctx: ReportContext) -> str:
    return STATUS_LABELS[facility.status] if facility.status else ctx.fmt.absent()


def _risk(facility: Facility, ctx: ReportContext) -> list[str]:
    exposure = facility.exposure
    spans = (
        [ctx.fmt.absent()] * 4
        if exposure is None
        else [
            _span(exposure.hq_worst, ctx),
            _span(exposure.cancer_risk_worst, ctx),
            _span(exposure.hq_representative, ctx),
            _span(exposure.cancer_risk_representative, ctx),
        ]
    )
    return [facility_label(facility), *spans, _status(facility, ctx)]


def _cou(facility: Facility, cou: ConditionOfUse | None, ctx: ReportContext) -> list[str]:
    """One row: a condition of use of ``facility`` (or why it has none) with its worst-case risk."""
    exposure, absent = facility.exposure, ctx.fmt.absent()
    if cou is None:
        use = [absent, ctx.fmt.text(facility.conditions_note), absent]
    else:
        use = [cou.lifecycle_stage, cou.cou_category, cou.tri_activity]
    worst = (
        [absent, absent]
        if exposure is None
        else [_span(exposure.hq_worst, ctx), _span(exposure.cancer_risk_worst, ctx)]
    )
    return [*use, facility_label(facility), *worst, _status(facility, ctx)]


def _cou_rows(facilities: list[Facility], ctx: ReportContext) -> list[list[str]]:
    """Rows grouped by life cycle stage, then condition of use (facilities without one last)."""
    rows = [_cou(f, cou, ctx) for f in facilities for cou in (f.conditions_of_use or [None])]
    known = sorted((r for r in rows if r[0] != ctx.fmt.absent()), key=lambda r: (r[0], r[1]))
    return known + [r for r in rows if r[0] == ctx.fmt.absent()]


def _write_by_use(doc: Document, facilities: list[Facility], ctx: ReportContext) -> None:
    subheading(doc, "Risk by life cycle stage and condition of use")
    paragraph(doc, _COU_NOTE, italic=True)
    table(doc, _COU_HEADER, _cou_rows(facilities, ctx))
    subheading(doc, "Risk by facility")


def _screening(facility: Facility, screening: Screening, ctx: ReportContext) -> list[str]:
    fmt = ctx.fmt
    return [
        facility_label(facility),
        _OUTCOMES[screening.outcome],
        fmt.number(screening.value_hq),
        fmt.number(screening.value_cancer_risk),
        screening.reason or "",
    ]


def write_risk(doc: Document, state: WorkspaceState, ctx: ReportContext) -> None:
    """Thresholds, risk by life cycle stage and condition of use, the per facility risk table and,
    when the batch screened facilities, the screening table."""
    if not state.facilities:
        empty(doc, ctx)
        return
    paragraph(doc, _thresholds(ctx))
    _write_by_use(doc, state.facilities, ctx)
    table(doc, _RISK_HEADER, [_risk(f, ctx) for f in state.facilities])
    screened = [(f, f.screening) for f in state.facilities if f.screening]
    if screened:
        subheading(doc, "Screening")
        table(doc, _SCREENING_HEADER, [_screening(f, s, ctx) for f, s in screened])
