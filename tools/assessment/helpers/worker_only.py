"""Fugitive-only facilities: a worker result and no community result.

A facility with a fugitive air release and no stack release has nothing to disperse, so no stack,
dispersion, screening bound, weather or population is asked for it: only its operational profile
and its worker screening, which need no community step.
"""

from __future__ import annotations

from collections.abc import Sequence

from tools.assessment.helpers.occupational import Workplace, occupational_exposure
from tools.emissions.profile import operational_profile
from tools.schemas import (
    OccupationalExposure,
    Toxicity,
    WorkerOnlyAssessment,
    WorkerOnlyFacility,
    WorkerOnlySummary,
)

COMMUNITY_REASON = "the facility reports no stack release"
_RANK = {"high": 2, "moderate": 1, "low": 0}


def assess_worker_only(
    facilities: Sequence[WorkerOnlyFacility],
    toxicity: Toxicity,
    workplace: Workplace,
) -> list[WorkerOnlyAssessment]:
    """The profile and worker screening of each facility, highest worker value first."""
    found = [_one(facility, toxicity, workplace) for facility in facilities]
    return sorted(found, key=_value, reverse=True)


def _one(
    facility: WorkerOnlyFacility,
    toxicity: Toxicity,
    workplace: Workplace,
) -> WorkerOnlyAssessment:
    profile = operational_profile(facility)
    return WorkerOnlyAssessment(
        facility=facility,
        operational_profile=profile,
        occupational_exposure=occupational_exposure(facility, profile, toxicity, workplace),
        community_reason=COMMUNITY_REASON,
    )


def _value(item: WorkerOnlyAssessment) -> tuple[int, float]:
    return worker_rank(item["occupational_exposure"])


def worker_rank(worker: OccupationalExposure) -> tuple[int, float]:
    """The worker band, then the worst-case 8-hour average; nothing computed ranks last."""
    band = worker["risk_tier"]
    twa = worker["worst_case"]["twa_mg_m3"]
    return (_RANK[band] if band is not None else -1, twa if twa is not None else -1.0)


def highest(items: Sequence[WorkerOnlyAssessment]) -> WorkerOnlySummary | None:
    """The facility with the highest worker value, as the model reads it; None without any."""
    if not items:
        return None
    best = max(items, key=_value)
    facility, worker = best["facility"], best["occupational_exposure"]
    return WorkerOnlySummary(
        frs_id=facility["frs_id"],
        facility_name=facility["facility_name"],
        city=facility["city"],
        state=facility["state"],
        fugitive_release_kg_per_year=facility["fugitive_release_kg_per_year"],
        worker_risk_tier=worker["risk_tier"],
        worker_twa_worst_mg_m3=worker["worst_case"]["twa_mg_m3"],
    )


def sentence(
    count: int,
    left_out: int,
    top: WorkerOnlySummary | None,
) -> str | None:
    """One sentence for the model: how many, the highest, and how many were left out."""
    if count == 0 or top is None:
        return None
    tier = top["worker_risk_tier"] or "not computed"
    who = "facility reports" if count == 1 else "facilities report"
    text = (
        f"{count} {who} only a fugitive air release (no stack release): worker result only, no "
        "community result, and not among the screened or assessed facilities; the highest "
        f"worker value is {top['facility_name'] or top['frs_id']} "
        f"({top['frs_id']}, worker band: {tier})."
    )
    return text if not left_out else f"{text} {left_out} more were left out by the cap."
