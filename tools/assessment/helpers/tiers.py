"""Which facilities go on at each tier: screened out on a bound, refined, then fully assessed.

A facility is left out only when its screening value is below both thresholds; facilities
that go on are ordered by how far they exceed a threshold, not by how much they emit. Without
any benchmark nothing can be screened out, and the order is the emission rate. Every facility
that reaches a threshold is refined; ``max_refined`` is only a safety bound, and what it
leaves over is reported.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from config.assessment import AssessmentSettings, ScreeningSettings
from tools.assessment.helpers.chain import Refined
from tools.assessment.helpers.screening import Worst, exceedance, reaches, scaled
from tools.assessment.helpers.stacks import GLOBAL_DEFAULT
from tools.schemas import EmissionRecord, NotAssessed, ScreenedOut, ScreeningBound

Candidate = tuple[EmissionRecord, ScreeningBound | None]


@dataclass(frozen=True)
class Screen:
    """The outcome of the bound: facilities to refine, left out, and past the safety bound."""

    candidates: list[Candidate]
    screened_out: list[ScreenedOut]
    over: list[NotAssessed]


@dataclass(frozen=True)
class Split:
    """The outcome of refining: fully assessed, kept at worst case, and left out."""

    full: list[Refined]
    worst_only: list[Refined]
    screened_out: list[ScreenedOut]


def _limits(thresholds: ScreeningSettings) -> str:
    return f"HQ {thresholds.hq:g} and cancer risk {thresholds.cancer_risk:g}"


def _value(hq: float | None, risk: float | None) -> str:
    parts = [
        f"HQ {hq:.2g}" if hq is not None else "",
        f"risk {risk:.2g}" if risk is not None else "",
    ]
    return " and ".join(p for p in parts if p)


def _out_at_bound(
    record: EmissionRecord,
    bound: ScreeningBound,
    t: ScreeningSettings,
) -> ScreenedOut:
    return ScreenedOut(
        record=record,
        stage="bound",
        hq=bound["hq"],
        cancer_risk=bound["cancer_risk"],
        stacks=[],
        stack_tier=GLOBAL_DEFAULT,
        reason=(
            "screened out: even with the EPA AirToxScreen global default stack (generic, short, "
            "cold) and EPA SCREEN3 worst-case weather, the bound "
            f"({_value(bound['hq'], bound['cancer_risk'])}) is below {_limits(t)}"
        ),
    )


def _over(kept: Sequence[Candidate], cap: int) -> list[NotAssessed]:
    reason = f"more than {cap} facilities reach a threshold; refining them all was not attempted"
    return [NotAssessed(frs_id=record["frs_id"], reason=reason) for record, _ in kept[cap:]]


def screen(
    records: Sequence[EmissionRecord],
    unit: Worst | None,
    settings: AssessmentSettings,
) -> Screen:
    """Tier 1: the bound of every facility; the ones reaching a threshold all go on, largest first.

    ``unit`` is the unit-rate worst case of the generic stack, or None when nothing can be
    screened (no benchmark): then every facility goes on, by emission rate.
    """
    t = settings.screening
    kept: list[Candidate] = []
    out: list[ScreenedOut] = []
    for record in records:
        bound = scaled(unit, record["emission_rate"]) if unit is not None else None
        if bound is None or reaches(bound["hq"], bound["cancer_risk"], t):
            kept.append((record, bound))
        else:
            out.append(_out_at_bound(record, bound, t))
    kept.sort(key=lambda c: c[0]["emission_rate"], reverse=True)  # = largest bound first
    cap = settings.max_refined
    return Screen(kept[:cap], out, _over(kept, cap))


def _out_with_own(item: Refined, t: ScreeningSettings) -> ScreenedOut:
    worst = item.worst
    return ScreenedOut(
        record=item.record,
        stage="own stacks",
        hq=worst.hq,
        cancer_risk=worst.cancer_risk,
        stacks=item.choice.stacks,
        stack_tier=item.choice.tier,
        reason=(
            f"screened out: with its own stacks ({item.choice.tier}) under EPA SCREEN3 "
            f"worst-case weather, the worst case ({_value(worst.hq, worst.cancer_risk)}) is "
            f"below {_limits(t)}"
        ),
    )


def split(items: Sequence[Refined], possible: bool, settings: AssessmentSettings) -> Split:
    """Tier 2 to 3: the highest worst-case risks go on to the full chain, up to the cap."""
    t = settings.screening
    if possible:
        going = [i for i in items if reaches(i.worst.hq, i.worst.cancer_risk, t)]
        out = [
            _out_with_own(i, t) for i in items if not reaches(i.worst.hq, i.worst.cancer_risk, t)
        ]
        going.sort(key=lambda i: exceedance(i.worst.hq, i.worst.cancer_risk, t), reverse=True)
    else:
        going, out = list(items), []
    cap = settings.max_facilities
    return Split(going[:cap], going[cap:], out)
