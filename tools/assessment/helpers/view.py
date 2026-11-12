"""What the model is told about a batch assessment: compact, ranked, with provenance."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TypedDict

from commons.bands import Band
from config.assessment import ScreeningSettings
from tools.assessment.helpers.scenarios import drivers_of
from tools.assessment.helpers.screened_workers import highest_worker, worker_bands
from tools.assessment.helpers.screened_workers import sentence as screened_sentence
from tools.assessment.helpers.screening import exceedance
from tools.assessment.helpers.worker_only import highest, sentence
from tools.schemas import (
    AssessmentResult,
    FacilityAssessment,
    FacilityRanges,
    FacilitySummary,
    NotAssessed,
    ScreenedOut,
    ScreenedOutSummary,
    ScreeningSummary,
    Toxicity,
    WorkerOnlyAssessment,
    WorkerOnlySummary,
    WorstCaseSummary,
)

# The model reads up to this many notes per facility; the rest are counted.
MAX_NOTES = 6


@dataclass(frozen=True)
class Findings:
    """Everything one call found, before it is cut down for the model.

    Attributes:
        cas: The CAS number assessed (None when it was invalid).
        toxicity: The benchmarks used, and where they come from ("given" or "CompTox").
        found: Facilities in the inventory (for the place).
        full: Fully assessed facilities.
        worst_only: Facilities kept at their own-stack worst case.
        screened_out: Facilities left out, with their screening values.
        thresholds: The screen's thresholds; None when facilities were asked for by ID.
        possible: Whether a benchmark allowed screening at all.
        skipped: Facilities not assessed (not found, or over a cap), with the reason.
        warnings: Benchmark warnings.
        worker_only: Fugitive-only facilities, with a worker result and no community one.
        worker_only_left_out: Fugitive-only facilities beyond the inventory's cap.
    """

    cas: str | None
    toxicity: tuple[Toxicity, str]
    found: int
    full: Sequence[FacilityAssessment]
    worst_only: Sequence[FacilityAssessment]
    screened_out: Sequence[ScreenedOut]
    thresholds: ScreeningSettings | None
    possible: bool
    skipped: list[NotAssessed]
    warnings: list[str]
    worker_only: Sequence[WorkerOnlyAssessment] = ()
    worker_only_left_out: int = 0


def _notes(item: FacilityAssessment) -> list[str]:
    """The choice notes, facility-level and per-stack warnings, deduplicated and capped."""
    exposure = item["exposure"]
    every = [
        *item["notes"],
        *exposure["warnings"],
        *(w for result in exposure["results"] for w in result["warnings"]),
        *(item["meteorology"] or {}).get("warnings", []),
        *(item["population"] or {}).get("warnings", []),
    ]
    unique = list(dict.fromkeys(note for note in every if note))
    if len(unique) <= MAX_NOTES:
        return unique
    return [*unique[:MAX_NOTES], f"(+{len(unique) - MAX_NOTES} more notes)"]


def _worst_hq(summary: FacilitySummary) -> float:
    entry = summary["hq_worst"]
    return entry["high"] if entry else -1.0


def _ranges(item: FacilityAssessment) -> FacilityRanges:
    """The worst-case and representative ranges over the stacks; None where not computable."""
    ranges = item["exposure"]["range"]
    typical = ranges["representative"] if ranges else None
    return FacilityRanges(
        concentration_worst=ranges["max_concentration"] if ranges else None,
        concentration_representative=typical["max_concentration"] if typical else None,
        hq_worst=ranges["hq"] if ranges else None,
        hq_representative=typical["hq"] if typical else None,
        cancer_risk_worst=ranges["cancer_risk"] if ranges else None,
        cancer_risk_representative=typical["cancer_risk"] if typical else None,
    )


class _Setting(TypedDict):
    """Where the facility was assessed and what the workers face (the summary's context fields)."""

    weather_source: str
    residents: int
    radius_km: float | None
    worker_risk_tier: Band | None
    worker_oel_ratio: float | None


def _setting(item: FacilityAssessment) -> _Setting:
    weather, people = item["meteorology"], item["population"]
    worker = item["occupational_exposure"]
    return _Setting(
        weather_source=weather["source"] if weather else "not requested (worst case only)",
        residents=people["total_population"] if people else 0,
        radius_km=item["radius_km"],
        worker_risk_tier=worker["risk_tier"],
        worker_oel_ratio=worker["baseline"]["oel_ratio"],
    )


def summarize(item: FacilityAssessment) -> FacilitySummary:
    """One fully assessed facility as the model reads it."""
    record = item["record"]
    return FacilitySummary(
        **_ranges(item),
        **_setting(item),
        frs_id=record["frs_id"],
        facility_name=record["facility_name"],
        city=record["city"],
        state=record["state"],
        emission_rate=record["emission_rate"],
        stack_tier=item["stack_tier"],
        stacks_evaluated=item["exposure"]["stacks_evaluated"],
        sccs=[match["scc"] for match in item["scc_matches"]],
        industry=record["naics_title"] or (item["industry"] or {}).get("naics_title"),
        notes=_notes(item),
    )


def worst_summary(item: FacilityAssessment) -> WorstCaseSummary:
    """One worst-case-only facility as the model reads it."""
    record, ranges = item["record"], item["exposure"]["range"]
    return WorstCaseSummary(
        frs_id=record["frs_id"],
        facility_name=record["facility_name"],
        city=record["city"],
        state=record["state"],
        emission_rate=record["emission_rate"],
        stack_tier=item["stack_tier"],
        hq_worst=ranges["hq"] if ranges else None,
        cancer_risk_worst=ranges["cancer_risk"] if ranges else None,
    )


def _screened_summary(out: ScreenedOut) -> ScreenedOutSummary:
    record, worker = out["record"], out.get("occupational_exposure")
    return ScreenedOutSummary(
        frs_id=record["frs_id"],
        facility_name=record["facility_name"],
        city=record["city"],
        state=record["state"],
        emission_rate=record["emission_rate"],
        stage=out["stage"],
        hq=out["hq"],
        cancer_risk=out["cancer_risk"],
        worker_risk_tier=worker["risk_tier"] if worker is not None else None,
    )


def _closest(
    out: Sequence[ScreenedOut],
    t: ScreeningSettings,
    limit: int,
) -> list[ScreenedOutSummary]:
    """The screened-out facilities closest to a threshold, closest first, at most ``limit``."""
    ranked = sorted(out, key=lambda o: exceedance(o["hq"], o["cancer_risk"], t), reverse=True)
    return [_screened_summary(o) for o in ranked[:limit]]


def _screening(f: Findings, max_listed: int) -> ScreeningSummary | None:
    t = f.thresholds
    if t is None:
        return None
    stages = Counter(o["stage"] for o in f.screened_out)
    return ScreeningSummary(
        possible=f.possible,
        hq_threshold=t.hq,
        cancer_risk_threshold=t.cancer_risk,
        screened_out_at_bound=stages["bound"],
        screened_out_with_own_stacks=stages["own stacks"],
        closest_screened_out=_closest(f.screened_out, t, max_listed),
        screened_out_worker_bands=worker_bands(f.screened_out),
        screened_out_worker_highest=highest_worker(f.screened_out),
    )


def _note(f: Findings) -> str | None:
    """What was left out, in one sentence the report can repeat."""
    if f.thresholds is None:
        return None
    if not f.possible:
        return (
            f"The chemical has no RfC or IUR, so none of the {f.found} facilities could be "
            "screened out; facilities were taken by emission rate."
        )
    return (
        f"All {f.found} facilities were screened: {len(f.screened_out)} cannot reach "
        f"HQ {f.thresholds.hq:g} or cancer risk {f.thresholds.cancer_risk:g} even in the worst "
        "case (emission rate from TRI; EPA AirToxScreen global default stack; EPA SCREEN3 "
        "worst-case weather over its 54 stability and wind combinations; a person at the "
        f"maximum) and were left out; {len(f.full)} were fully assessed and "
        f"{len(f.worst_only)} kept at the worst case with their own stacks."
    )


class _Workers(TypedDict):
    """The fugitive-only facilities as the model reads them, with the note that says so."""

    worker_only_count: int
    worker_only_left_out: int
    worker_only_highest: WorkerOnlySummary | None
    note: str | None


def _workers(f: Findings) -> _Workers:
    top = highest(f.worker_only)
    count, left_out = len(f.worker_only), f.worker_only_left_out
    return _Workers(
        worker_only_count=count,
        worker_only_left_out=left_out,
        worker_only_highest=top,
        note=_joined(_note(f), screened_sentence(f.screened_out), sentence(count, left_out, top)),
    )


def _joined(*texts: str | None) -> str | None:
    parts = [part for part in texts if part]
    return " ".join(parts) if parts else None


def _risk_first(items: Sequence[FacilityAssessment]) -> list[WorstCaseSummary]:
    rows = [worst_summary(item) for item in items]
    return sorted(
        rows,
        key=lambda r: r["hq_worst"]["high"] if r["hq_worst"] else -1.0,
        reverse=True,
    )


def assessment_view(
    f: Findings,
    max_worst_listed: int,
    max_screened_listed: int,
) -> AssessmentResult:
    """The model's view: the fully assessed (highest worst-case HQ first), the rest counted."""
    facilities = sorted((summarize(item) for item in f.full), key=_worst_hq, reverse=True)
    worst = _risk_first(f.worst_only)
    return AssessmentResult(
        cas_number=f.cas,
        toxicity=f.toxicity[0],
        toxicity_source=f.toxicity[1],
        facilities_found=f.found,
        screening=_screening(f, max_screened_listed),
        assessed=len(facilities),
        stack_tiers=dict(Counter(item["stack_tier"] for item in f.full)),
        facilities=facilities,
        worst_case_only_count=len(worst),
        worst_case_only=worst[:max_worst_listed],
        not_assessed=f.skipped,
        **_workers(f),
        warnings=f.warnings,
        drivers=drivers_of([*f.full, *f.worst_only]),
    )
