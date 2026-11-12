"""The words of the worker result: assumptions, the fugitive release statement and warnings."""

from __future__ import annotations

from tools.schemas import Evidence

FUGITIVE_STATEMENT = (
    "The TRI fugitive air release is the mass released from the site to air other than through "
    "stacks. It is shown as context and is not used to compute any worker value."
)
SCREENING = (
    "The result is a screening indicator of worker exposure, not an OSHA compliance determination "
    "and not a finding: the high, moderate and low bands are a screening priority for follow-up."
)
NOT_MODELLED = "Dermal exposure and particulate (dust) exposure are not modelled."
EVIDENCE_TEXT: dict[Evidence | None, str] = {
    "monitoring": (
        "The headline rests on OSHA's measured personal air samples of this industry (the median "
        "as the baseline and the 95th percentile as the worst case), not on this facility. Each "
        "sample's result, averaged over its sampling time, is taken as the 8-hour average."
    ),
    "activity_model": (
        "The headline rests on the driving worker activity, modelled (typical case as the "
        "baseline, worst case as the worst case)."
    ),
    None: "No measured data and no modelled activity were available, so nothing is computed.",
}
MODEL_ASSUMPTIONS = (
    "The activities are those of the generic scenario of the facility's industry and life cycle "
    "stage (or of ChemSTEER's generic operation of the stage), not observed at the facility.",
    "The pure chemical is assumed because TRI does not report its concentration in the material "
    "handled.",
    "A container activity, whose hours depend on a throughput TRI does not report, is taken as "
    "lasting the full 8-hour shift.",
    "The ventilation is EPA ChemSTEER's default (well-mixed room tiers or two-zone rooms), not "
    "this plant's; no local exhaust ventilation or protective equipment is assumed.",
)


def assumptions(evidence: Evidence | None, modelled: bool) -> list[str]:
    """The statements every result carries, plus the model's when activities were modelled."""
    model = list(MODEL_ASSUMPTIONS) if modelled else []
    return [SCREENING, EVIDENCE_TEXT[evidence], *model, NOT_MODELLED]


def benchmark_warnings(
    oel: float | None,
    rfc: float | None,
    iur: float | None,
    days: float | None,
) -> list[str]:
    """What is not computed because a benchmark or the schedule is missing."""
    notes: list[str] = []
    if oel is None:
        notes.append(
            "no 8-hour occupational limit is available, so the limit ratio is not computed",
        )
    if rfc is None:
        notes.append("no RfC, so the worker hazard quotient is not computed")
    if iur is None:
        notes.append("no IUR, so the worker cancer risk is not computed")
    if days is None:
        notes.append(
            "the plant's operating schedule could not be derived, so the worker hazard quotient "
            "and cancer risk are not computed",
        )
    return notes
