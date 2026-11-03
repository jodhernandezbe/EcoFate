"""Stacks of a facility: NEI candidates and evaluated stacks, each with its provenance tier."""

from __future__ import annotations

import math
from collections.abc import Mapping

from api.schemas.workspace import Dose, Scenario, Stack, Tier
from api.services.projectors.ledger import Ledger
from api.services.projectors.payloads import (
    ExposurePayload,
    SccMatchPayload,
    ScenarioPayload,
    StackExposurePayload,
    StackPayload,
)

# Tier numbers and labels follow from a stack's reported source and nothing else.
TIERS: Mapping[str, tuple[Tier, str]] = {
    "NEI": (1, "Tier 1: Empirical NEI"),
    "PSTK": (2, "Tier 2: PSTK by SCC"),
    "AirToxScreen global default": (3, "Tier 3: EPA global default"),
}


def _equal(first: float | None, second: float | None) -> bool:
    if first is None or second is None:
        return first is second
    return math.isclose(first, second, rel_tol=1e-9, abs_tol=0.0)


def _same(stack: StackPayload, echoed: StackExposurePayload) -> bool:
    """The four stack values of a result equal those of a stack (so it is that stack)."""
    return (
        _equal(stack.stack_height, echoed.stack_height)
        and _equal(stack.stack_diameter, echoed.stack_diameter)
        and _equal(stack.exit_velocity, echoed.exit_velocity)
        and _equal(stack.exit_temperature, echoed.exit_temperature)
    )


def _scenario(result: ScenarioPayload) -> Scenario:
    return Scenario(
        max_concentration_ug_m3=result.max_concentration,
        distance_m=result.distance_m,
        hq=result.hq,
        cancer_risk=result.cancer_risk,
    )


def dose_of(result: StackExposurePayload) -> Dose | None:
    """The dose the tool reported for a stack; None when it reported none."""
    if not result.add_by_band:
        return None
    return Dose(
        highest_mg_kg_day=result.add,
        highest_band=result.add_band,
        by_band=dict(result.add_by_band),
    )


def _provenance(
    source: str | None,
    scc: str | None,
    lookups: Mapping[str, SccMatchPayload],
) -> dict[str, object]:
    tier = TIERS.get(source or "")
    match = lookups.get(scc) if scc else None
    return {
        "source": source,
        "tier": tier[0] if tier else None,
        "tier_label": tier[1] if tier else None,
        "scc": scc,
        "scc_description": match.level_four if match else None,
        "scc_score": match.score if match else None,
    }


def _from_candidate(
    candidate: StackPayload,
    result: StackExposurePayload | None,
    ledger: Ledger,
) -> Stack:
    stack = Stack(
        height_m=candidate.stack_height,
        diameter_m=candidate.stack_diameter,
        exit_velocity_m_s=candidate.exit_velocity,
        exit_temperature_k=candidate.exit_temperature,
        warnings=list(candidate.warnings),
    )
    stack = stack.model_copy(
        update=_provenance(candidate.source, candidate.scc, ledger.scc_matches),
    )
    return stack if result is None else _with_result(stack, result)


def _with_result(stack: Stack, result: StackExposurePayload) -> Stack:
    return stack.model_copy(
        update={
            "stack_number": result.stack_number,
            "worst_case": _scenario(result),
            "representative": _scenario(result.representative),
            "dose": dose_of(result),
            "warnings": [*stack.warnings, *result.warnings],
        },
    )


def _scc_of(result: StackExposurePayload, ledger: Ledger) -> str | None:
    """The SCC of a PSTK stack: that of the latest SCC stack result whose values equal it."""
    hits = [s.scc for s in ledger.scc_stacks if s.scc and _same(s, result)]
    return hits[-1] if hits else None


def _from_result(result: StackExposurePayload, ledger: Ledger) -> Stack:
    candidate = StackPayload(
        stack_height=result.stack_height,
        stack_diameter=result.stack_diameter,
        exit_velocity=result.exit_velocity,
        exit_temperature=result.exit_temperature,
        source=result.stack_source,
        scc=_scc_of(result, ledger),
    )
    return _from_candidate(candidate, result, ledger)


def facility_stacks(
    candidates: list[StackPayload],
    exposure: ExposurePayload | None,
    ledger: Ledger,
) -> list[Stack]:
    """NEI candidates first (with their results when evaluated), then other evaluated stacks."""
    results = list(exposure.results) if exposure else []
    stacks: list[Stack] = []
    for candidate in candidates:
        hit = next((r for r in results if _same(candidate, r)), None)
        if hit is not None:
            results.remove(hit)
        stacks.append(_from_candidate(candidate, hit, ledger))
    return [*stacks, *(_from_result(r, ledger) for r in results)]
