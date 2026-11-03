"""Choose a facility's stacks: its own (NEI), else process-typical (PSTK by SCC), else generic.

The order is the evidence order of the assessment: facility-specific beats process-typical,
which beats the EPA global default. Every fall-back says why the better source was not used.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from config.assessment import AssessmentSettings
from tools.assessment.helpers.steps import Steps
from tools.schemas import (
    EmissionRecord,
    FacilityIndustry,
    SccMatch,
    StackParameters,
    StackSource,
)

GLOBAL_DEFAULT: StackSource = "AirToxScreen global default"
Values = tuple[float | None, float | None, float | None, float | None]


@dataclass(frozen=True)
class StackChoice:
    """The stacks to evaluate, where they come from, and why that source was chosen."""

    stacks: list[StackParameters]
    tier: StackSource
    scc_matches: list[SccMatch] = field(default_factory=list[SccMatch])
    industry: FacilityIndustry | None = None
    notes: list[str] = field(default_factory=list[str])


def _values(stack: StackParameters) -> Values:
    return (
        stack["stack_height"],
        stack["stack_diameter"],
        stack["exit_velocity"],
        stack["exit_temperature"],
    )


def _nei(record: EmissionRecord, steps: Steps, notes: list[str]) -> StackChoice | None:
    """The facility's own NEI stacks, or None (with the reason noted)."""
    eis_ids = record["eis_ids"]
    if not eis_ids:
        notes.append(record["eis_note"] or f"FRS ID {record['frs_id']} has no EIS registration")
        return None
    result = steps.nei(record["frs_id"], eis_ids)
    if result["candidates"]:
        return StackChoice(result["candidates"], "NEI", notes=list(result["warnings"]))
    notes.append(f"the NEI has no usable stack for EIS ID {', '.join(eis_ids)}")
    return None


def _title(
    record: EmissionRecord,
    steps: Steps,
    notes: list[str],
) -> tuple[str | None, FacilityIndustry | None]:
    """The industry in words: from the inventory, else from TRI's tables, else None."""
    if record["naics_title"]:
        return record["naics_title"], None
    doc = record["doc_ctrl_num"]
    industry = steps.industry(doc) if doc else None
    title = industry["naics_title"] if industry else None
    if title is None:
        notes.append("the facility's industry is unknown, so no process-typical stack applies")
    return title, industry


def _pstk(
    title: str,
    steps: Steps,
    settings: AssessmentSettings,
    notes: list[str],
) -> tuple[list[StackParameters], list[SccMatch]]:
    """Distinct PSTK stacks of the best SCC matches above the score floor."""
    lookup = steps.scc(title)
    notes.extend(lookup["warnings"])
    good = [m for m in lookup["matches"] if m["score"] >= settings.scc_min_score]
    stacks: list[StackParameters] = []
    used: list[SccMatch] = []
    for match in good:
        stack = steps.pstk(match["scc"])
        if stack["source"] != "PSTK" or _values(stack) in {_values(s) for s in stacks}:
            continue
        stacks.append(stack)
        used.append(match)
        if len(stacks) == settings.max_scc_stacks:
            break
    if not stacks:
        notes.append(_no_pstk(title, lookup["matches"], good, settings))
    return stacks, used


def _no_pstk(
    title: str,
    matches: list[SccMatch],
    good: list[SccMatch],
    settings: AssessmentSettings,
) -> str:
    if not matches:
        return f"no SCC process matched the industry {title!r}"
    if not good:
        best = max(m["score"] for m in matches)
        return (
            f"no SCC process matched the industry {title!r} closely enough "
            f"(best similarity {best:.2f}, at least {settings.scc_min_score:.2f} needed)"
        )
    return f"none of the {len(good)} SCC processes matching {title!r} has a PSTK stack"


def choose_stacks(
    record: EmissionRecord,
    steps: Steps,
    settings: AssessmentSettings,
) -> StackChoice:
    """The best available stacks of a facility; never empty (the global default is last)."""
    notes: list[str] = []
    own = _nei(record, steps, notes)
    if own is not None:
        return own
    title, industry = _title(record, steps, notes)
    if title is not None:
        stacks, used = _pstk(title, steps, settings, notes)
        if stacks:
            return StackChoice(stacks, "PSTK", used, industry, notes)
    default = steps.pstk(None)
    notes.append("the EPA global default stack is used: it is generic, so results are uncertain")
    return StackChoice([default], GLOBAL_DEFAULT, [], industry, notes)
