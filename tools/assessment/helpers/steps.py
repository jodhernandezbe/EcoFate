"""The steps the batch assessment runs for each facility, as injectable callables.

Each step has the contract of the single tool it stands for (and never raises on data or
network problems); the default steps are those tools themselves, built at the tool's edge.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from tools.schemas import (
    FacilityExposure,
    FacilityIndustry,
    Meteorology,
    NeiStackResult,
    Population,
    SccLookupResult,
    StackParameters,
    Toxicity,
)


@dataclass(frozen=True)
class Steps:
    """One facility's chain, step by step.

    Attributes:
        nei: (FRS ID, EIS IDs) -> the facility's NEI stack candidates.
        industry: TRI control number -> the submission's industry (code and title).
        scc: industry title -> matching SCCs, best first.
        pstk: SCC (or None) -> its PSTK stack, else the EPA global default.
        weather: (latitude, longitude, reporting year) -> representative meteorology.
        people: (latitude, longitude, radius km or None) -> residents and age mix.
        exposure: (emission rate g/s, stacks, meteorology, population, toxicity) -> result.
        prefetch: industry titles -> nothing; lets ``scc`` find them without a request each.
    """

    nei: Callable[[str, list[str]], NeiStackResult]
    industry: Callable[[str], FacilityIndustry]
    scc: Callable[[str], SccLookupResult]
    pstk: Callable[[str | None], StackParameters]
    weather: Callable[[float, float, int | None], Meteorology]
    people: Callable[[float, float, float | None], Population]
    exposure: Callable[
        [float, list[StackParameters], Meteorology, Population, Toxicity],
        FacilityExposure,
    ]
    prefetch: Callable[[Sequence[str]], None] = lambda titles: None
