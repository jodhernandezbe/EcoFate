"""The workers of the facilities the community screen left out: screened all the same.

The community screen bounds what a stack release can do to the neighbours; it says nothing of
what workers breathe inside the plant, which comes from the plant's tasks or from monitoring in
its industry. So every screened-out facility keeps its operational profile and worker
screening, and the model is told how they fall in the bands and which one is highest.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from tools.assessment.helpers.occupational import Workplace, occupational_exposure
from tools.assessment.helpers.worker_only import worker_rank
from tools.emissions.profile import operational_profile
from tools.schemas import ScreenedOut, ScreenedOutWorkerSummary, Toxicity

NOT_COMPUTED = "not computed"


def with_workers(
    out: Sequence[ScreenedOut],
    toxicity: Toxicity,
    workplace: Workplace,
) -> list[ScreenedOut]:
    """Each screened-out facility with its operational profile and worker screening."""
    return [_one(item, toxicity, workplace) for item in out]


def _one(item: ScreenedOut, toxicity: Toxicity, workplace: Workplace) -> ScreenedOut:
    record = item["record"]
    profile = operational_profile(record)
    worker = occupational_exposure(record, profile, toxicity, workplace)
    return {**item, "occupational_exposure": worker, "operational_profile": profile}


def worker_bands(out: Sequence[ScreenedOut]) -> dict[str, int]:
    """How many screened-out facilities fall in each worker band ("not computed" included)."""
    tiers = Counter(_tier(item) for item in out)
    return dict(tiers)


def _tier(item: ScreenedOut) -> str:
    worker = item.get("occupational_exposure")
    tier = worker["risk_tier"] if worker is not None else None
    return tier if tier is not None else NOT_COMPUTED


def highest_worker(out: Sequence[ScreenedOut]) -> ScreenedOutWorkerSummary | None:
    """The screened-out facility with the highest worker value; None when none has a result."""
    screened = [item for item in out if "occupational_exposure" in item]
    if not screened:
        return None
    best = max(screened, key=lambda item: worker_rank(item["occupational_exposure"]))
    record, worker = best["record"], best["occupational_exposure"]
    return ScreenedOutWorkerSummary(
        frs_id=record["frs_id"],
        facility_name=record["facility_name"],
        city=record["city"],
        state=record["state"],
        worker_risk_tier=worker["risk_tier"],
        worker_twa_worst_mg_m3=worker["worst_case"]["twa_mg_m3"],
    )


def sentence(out: Sequence[ScreenedOut]) -> str | None:
    """One sentence for the model: the screened-out workers by band, and the highest."""
    top = highest_worker(out)
    if top is None:
        return None
    bands = worker_bands(out)
    counts = ", ".join(
        f"{bands[b]} {b}" for b in ("high", "moderate", "low", NOT_COMPUTED) if b in bands
    )
    tier = top["worker_risk_tier"] or NOT_COMPUTED
    return (
        "The community screen does not apply to workers, so the screened-out facilities' workers "
        f"were still screened ({counts}); the highest worker value is "
        f"{top['facility_name'] or top['frs_id']} ({top['frs_id']}, worker band: {tier})."
    )
