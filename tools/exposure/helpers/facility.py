"""Screening exposure for every candidate stack of a facility, and the range over them.

Each stack goes through the unchanged single-stack ``assess_exposure``; this module only loops,
numbers the results and summarizes them, so the agent never has to fan out over stacks itself.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from config.exposure import ExposureSettings
from tools.exposure.helpers.assessment import assess_exposure
from tools.schemas import (
    ExposureRange,
    FacilityExposure,
    Meteorology,
    Population,
    RangeEntry,
    StackExposure,
    StackParameters,
    Toxicity,
)

_STACK_FIELDS = ("stack_height", "stack_diameter", "exit_velocity", "exit_temperature")
_RANGED = ("max_concentration", "hq", "cancer_risk")
_NO_STACK = (
    "no stack was given; pass every candidate stack of the facility (the NEI candidates, or the "
    "SCC-based stack when the NEI has none)"
)


def _stack_list(stacks: object) -> list[StackParameters]:
    """The stacks as a list of dicts; anything else in the list becomes an empty stack."""
    items = cast(list[object], stacks) if isinstance(stacks, list) else []
    return [
        cast(StackParameters, s) if isinstance(s, dict) else cast(StackParameters, {})
        for s in items
    ]


def _numbered(number: int, stack: StackParameters, result: object) -> StackExposure:
    values = {name: stack.get(name) for name in _STACK_FIELDS}
    return cast(
        StackExposure,
        {**cast(dict[str, object], result), "stack_number": number, **values},
    )


def _entry(rows: list[tuple[Mapping[str, object], int]], quantity: str) -> RangeEntry | None:
    """Lowest and highest ``quantity`` over (result, stack_number) rows, ignoring nulls."""
    found = [
        (float(cast(float, row[quantity])), number)
        for row, number in rows
        if row.get(quantity) is not None
    ]
    if not found:
        return None
    low, high = min(found), max(found)
    return RangeEntry(low=low[0], high=high[0], low_stack=low[1], high_stack=high[1])


def _range(results: list[StackExposure]) -> ExposureRange:
    worst = [(cast(Mapping[str, object], r), r["stack_number"]) for r in results]
    typical = [
        (cast(Mapping[str, object], r["representative"]), r["stack_number"]) for r in results
    ]
    entries: dict[str, object] = {q: _entry(worst, q) for q in _RANGED}
    entries["representative"] = {q: _entry(typical, q) for q in _RANGED}
    return cast(ExposureRange, entries)


def _facility_notes(given: int, evaluated: int) -> list[str]:
    if given == 0:
        return [_NO_STACK]
    if evaluated < given:
        return [
            f"{given - evaluated} of {given} stacks could not be evaluated; "
            "their results are null and their warnings say why",
        ]
    return []


def assess_facility(
    emission_rate: float,
    stacks: object,
    meteorology: Meteorology,
    population: Population,
    toxicity: Toxicity,
    settings: ExposureSettings,
) -> FacilityExposure:
    """Screening results for each stack of a facility and the range over them.

    Args:
        emission_rate: Facility emission rate, in grams per second (g/s); >= 0.
        stacks: Candidate stacks (m, m, m/s, K each); a stack with a missing value gets a null
            result with a warning and does not stop the others.
        meteorology: Representative weather (10 m wind speed in m/s, stability class, ambient
            temperature in K).
        population: Residents and age mix (percent per band).
        toxicity: RfC in mg/m^3 and IUR in (ug/m^3)^-1; either may be None.
        settings: Screening grid, distances, exposure factors, age-band rates and weights.

    Returns:
        One result per stack in the order given (numbered from 1), the range of the worst-case
        concentration (ug/m^3), hazard quotient and cancer risk with the stack behind each end
        (None when no stack could be evaluated), the counts and facility warnings.
    """
    listed = _stack_list(stacks)
    results = [
        _numbered(
            n,
            s,
            assess_exposure(emission_rate, s, meteorology, population, toxicity, settings),
        )
        for n, s in enumerate(listed, start=1)
    ]
    evaluated = sum(r["max_concentration"] is not None for r in results)
    return FacilityExposure(
        results=results,
        range=_range(results) if evaluated else None,
        stacks_given=len(listed),
        stacks_evaluated=evaluated,
        warnings=_facility_notes(len(listed), evaluated),
    )
