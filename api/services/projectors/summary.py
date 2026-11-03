"""The executive summary: chemical, highest risk, selected facility and its context."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from functools import partial

from api.schemas.workspace import (
    NOT_COMPUTED,
    Chemical,
    ExposureRanges,
    Extreme,
    Extremum,
    Facility,
    ReadAcross,
    RiskSummary,
    ScenarioDriver,
    Status,
    VentilationTier,
    WorkerExtremum,
    WorkerRiskSummary,
    WorkerTierSummary,
    WorstCaseScenario,
)
from api.services.projectors.ledger import Ledger
from api.services.projectors.payloads import PropertiesPayload, ReadAcrossPayload
from api.services.projectors.rules import WorkspaceRules, cancer_status, hq_status

UNATTRIBUTED_EXPOSURE = "the exposure result could not be matched to one facility"


def _digits(cas: str | None) -> str:
    return "".join(c for c in cas or "" if c.isdigit())


def _read_across(payload: ReadAcrossPayload) -> ReadAcross:
    if payload.is_direct_tri_match:
        kind = "direct_tri_match"
    elif payload.resolution_method == "tri_category_member":
        kind = "tri_category_member"
    elif payload.resolution_method == "hybrid_read_across":
        kind = "read_across"
    else:
        kind = "unresolved"
    return ReadAcross(
        kind=kind,
        surrogate_cas=payload.surrogate_tri_cas,
        surrogate_name=payload.surrogate_name,
        hybrid_score=payload.hybrid_read_across_score,
        cosine_similarity=payload.moldeberta_cosine_sim,
        tanimoto_similarity=payload.morgan_tanimoto_sim,
        within_applicability_domain=payload.within_applicability_domain,
        warnings=list(payload.warnings),
    )


def _property_fields(props: PropertiesPayload) -> dict[str, object]:
    """The chemical's values and where each came from, as the properties tool gave them."""
    limits = props.occupational_limits
    sources = dict(props.sources)
    if limits is not None and limits.oel_source:
        sources.setdefault("oel_twa", limits.oel_source)
    return {
        "name": props.preferred_name,
        "molecular_weight_g_mol": props.molecular_weight,
        "vapor_pressure_mmhg": props.vapor_pressure,
        "density_g_cm3": props.density,
        "oel_twa_mg_m3": limits.oel_twa_mg_m3 if limits else None,
        "rfc_mg_m3": props.rfc,
        "iur_per_ug_m3": props.iur,
        "sources": sources,
        "warnings": list(props.warnings),
    }


def chemical(ledger: Ledger) -> Chemical:
    """The chemical last asked about, with the results that were for that CAS number only."""
    cas = ledger.cas
    result = Chemical(cas_number=cas)
    if ledger.properties and _digits(ledger.properties[0]) == _digits(cas):
        result = result.model_copy(update=_property_fields(ledger.properties[1]))
    if ledger.read_across and _digits(ledger.read_across[0]) == _digits(cas):
        result = result.model_copy(update={"read_across": _read_across(ledger.read_across[1])})
    return result


def _highest(
    facilities: Sequence[Facility],
    entry: Callable[[ExposureRanges], Extreme | None],
    grade: Callable[[float], Status],
) -> Extremum | None:
    best: Extremum | None = None
    for facility in facilities:
        found = entry(facility.exposure) if facility.exposure else None
        if found is not None and (best is None or found.high > best.value):
            best = Extremum(
                value=found.high,
                frs_id=facility.frs_id,
                facility_name=facility.name,
                stack_number=found.high_stack,
                status=grade(found.high),
            )
    return best


def risk_summary(
    facilities: Sequence[Facility],
    rules: WorkspaceRules,
    exposure_seen: bool,
) -> RiskSummary:
    """The highest worst-case and representative HQ and cancer risk over the facilities."""
    hq = partial(hq_status, thresholds=rules.thresholds)
    risk = partial(cancer_status, thresholds=rules.thresholds)
    summary = RiskSummary(
        hq_worst=_highest(facilities, lambda r: r.hq_worst, hq),
        cancer_risk_worst=_highest(facilities, lambda r: r.cancer_risk_worst, risk),
        hq_representative=_highest(facilities, lambda r: r.hq_representative, hq),
        cancer_risk_representative=_highest(
            facilities,
            lambda r: r.cancer_risk_representative,
            risk,
        ),
    )
    if any(f.exposure for f in facilities):
        return summary
    return summary.model_copy(
        update={"reason": UNATTRIBUTED_EXPOSURE if exposure_seen else NOT_COMPUTED},
    )


NO_WORKER_RESULT = "no facility has a worker screening result yet"


def _worst_worker(
    facilities: Sequence[Facility],
    pick: Callable[[Facility], float | None],
) -> WorkerExtremum | None:
    """The facility with the highest value of one worker quantity (a selection, never a sum)."""
    best: WorkerExtremum | None = None
    for facility in facilities:
        value = pick(facility)
        if value is not None and (best is None or value > best.value):
            tier = (
                facility.occupational_exposure.risk_tier if facility.occupational_exposure else None
            )
            best = WorkerExtremum(
                value=value,
                frs_id=facility.frs_id,
                facility_name=facility.name,
                risk_tier=tier,
            )
    return best


def _tier_summary(
    facilities: Sequence[Facility],
    tier: Callable[[Facility], VentilationTier | None],
) -> WorkerTierSummary:
    def of(field: Callable[[VentilationTier], float | None]) -> WorkerExtremum | None:
        return _worst_worker(facilities, lambda f: _field(tier(f), field))

    return WorkerTierSummary(
        oel_ratio=of(lambda t: t.oel_ratio),
        hq=of(lambda t: t.hq),
        cancer_risk=of(lambda t: t.cancer_risk),
    )


def _field(
    tier: VentilationTier | None,
    field: Callable[[VentilationTier], float | None],
) -> float | None:
    return field(tier) if tier is not None else None


def worker_summary(facilities: Sequence[Facility]) -> WorkerRiskSummary:
    """The highest worker limit ratio, hazard quotient and cancer risk, for both tiers."""
    summary = WorkerRiskSummary(
        baseline=_tier_summary(
            facilities,
            lambda f: f.occupational_exposure.baseline if f.occupational_exposure else None,
        ),
        worst_case=_tier_summary(
            facilities,
            lambda f: f.occupational_exposure.worst_case if f.occupational_exposure else None,
        ),
    )
    if any(f.occupational_exposure for f in facilities):
        return summary
    return summary.model_copy(update={"reason": NO_WORKER_RESULT})


def select(facilities: Sequence[Facility], summary: RiskSummary) -> Facility | None:
    """The facility the ribbon follows: the highest risk one, else the latest with receptors,
    else the only one."""
    leading = summary.hq_worst or summary.cancer_risk_worst
    if leading is not None:
        return next(f for f in facilities if f.frs_id == leading.frs_id)
    with_receptors = [f for f in facilities if f.receptors]
    if with_receptors:
        return with_receptors[-1]
    return facilities[0] if len(facilities) == 1 else None


def scenario_drivers(facilities: Sequence[Facility]) -> list[ScenarioDriver]:
    """For each pathway and quantity, the facility with the highest value (a selection).

    The first facility wins a tie. Nothing is computed: each driver is one facility's own
    scenario value.
    """
    best: dict[tuple[str, str], ScenarioDriver] = {}
    for facility in facilities:
        for scenario in facility.scenarios:
            key = (scenario.pathway_key, scenario.quantity)
            held = best.get(key)
            if held is None or scenario.value > held.value:
                best[key] = _driver(facility, scenario)
    return list(best.values())


def _driver(facility: Facility, scenario: WorstCaseScenario) -> ScenarioDriver:
    stack = next((f.value for f in scenario.factors if f.key == "stack_number"), None)
    return ScenarioDriver(
        pathway_key=scenario.pathway_key,
        quantity=scenario.quantity,
        frs_id=facility.frs_id,
        facility_name=facility.name,
        stack_number=int(stack) if isinstance(stack, int | float) else None,
        value=scenario.value,
    )
