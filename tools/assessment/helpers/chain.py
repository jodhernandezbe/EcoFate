"""Run the chain per facility: own stacks and worst case (refine), then weather and residents.

Refining needs no site weather (see ``screening``); the full assessment reuses the refined
stacks, shares one weather request per reanalysis grid cell and year, and counts residents.
"""

from __future__ import annotations

import contextvars
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from config.assessment import AssessmentSettings
from config.occupational import get_occupational_settings
from tools.assessment.helpers.occupational import Workplace, occupational_exposure, unavailable
from tools.assessment.helpers.scenarios import with_scenarios
from tools.assessment.helpers.screening import Worst, worst_case
from tools.assessment.helpers.stacks import StackChoice, choose_stacks
from tools.assessment.helpers.steps import Steps
from tools.emissions.profile import operational_profile
from tools.schemas import (
    EmissionRecord,
    FacilityAssessment,
    Meteorology,
    OccupationalExposure,
    OperationalProfile,
    ScreeningBound,
    Toxicity,
)

Cell = tuple[int, int, int | None]


@dataclass(frozen=True)
class Refined:
    """A facility with its chosen stacks and their worst case (no site weather)."""

    record: EmissionRecord
    choice: StackChoice
    worst: Worst
    bound: ScreeningBound | None


def in_pool[T, R](work: Callable[[T], R], items: Sequence[T], workers: int) -> list[R]:
    """``work`` over the items, ``workers`` at a time, in order, each in the caller's context.

    The keys of this run are held in context variables, so each task runs in a copy of the
    caller's context. An error that is not a data or network problem is raised, not hidden.
    """
    if not items:
        return []
    size = max(1, min(workers, len(items)))
    with ThreadPoolExecutor(max_workers=size) as pool:
        futures = [pool.submit(contextvars.copy_context().run, work, item) for item in items]
        return [future.result() for future in futures]


def refine_one(
    record: EmissionRecord,
    bound: ScreeningBound | None,
    toxicity: Toxicity,
    steps: Steps,
    settings: AssessmentSettings,
) -> Refined:
    """The facility's best stacks and their worst case over the screening temperatures."""
    choice = choose_stacks(record, steps, settings)
    temperatures = settings.screening.ambient_temperatures_k
    worst = worst_case(record["emission_rate"], choice.stacks, toxicity, steps, temperatures)
    return Refined(record, choice, worst, bound)


def refine_all(
    records: Sequence[tuple[EmissionRecord, ScreeningBound | None]],
    toxicity: Toxicity,
    steps: Steps,
    settings: AssessmentSettings,
) -> list[Refined]:
    """Every facility refined, ``max_workers`` at a time, in the order given."""

    def one(item: tuple[EmissionRecord, ScreeningBound | None]) -> Refined:
        return refine_one(item[0], item[1], toxicity, steps, settings)

    return in_pool(one, records, settings.max_workers)


def cell(record: EmissionRecord, size_deg: float) -> Cell:
    """The reanalysis grid cell (nearest grid point) and year of a facility."""
    return (
        round(record["latitude"] / size_deg),
        round(record["longitude"] / size_deg),
        record["reporting_year"],
    )


def _shared_weather(
    items: Sequence[Refined],
    steps: Steps,
    settings: AssessmentSettings,
) -> dict[Cell, Meteorology]:
    """One weather request per grid cell and year (any point of a cell gives its series)."""
    first: dict[Cell, EmissionRecord] = {}
    for item in items:
        first.setdefault(cell(item.record, settings.weather_cell_deg), item.record)

    def fetch(record: EmissionRecord) -> Meteorology:
        return steps.weather(record["latitude"], record["longitude"], record["reporting_year"])

    found = in_pool(fetch, list(first.values()), settings.max_workers)
    return dict(zip(first, found, strict=True))


def _worker_view(
    item: Refined,
    toxicity: Toxicity,
    workplace: Workplace | None,
) -> tuple[OccupationalExposure, OperationalProfile]:
    """The worker screening and operational profile of a facility (if given a workplace)."""
    profile = operational_profile(item.record)
    if workplace is None:
        reason = "the chemical's workplace information was not given"
        return unavailable(get_occupational_settings(), reason), profile
    return occupational_exposure(item.record, profile, toxicity, workplace), profile


def _own_stack_assessment(
    item: Refined,
    radius_km: float | None,
    worker: OccupationalExposure,
    profile: OperationalProfile,
) -> FacilityAssessment:
    return FacilityAssessment(
        record=item.record,
        level="worst case only",
        bound=item.bound,
        stacks=item.choice.stacks,
        stack_tier=item.choice.tier,
        scc_matches=item.choice.scc_matches,
        industry=item.choice.industry,
        meteorology=None,
        population=None,
        radius_km=radius_km,
        exposure=item.worst.exposure,
        occupational_exposure=worker,
        operational_profile=profile,
        notes=item.choice.notes,
    )


def worst_case_only(
    item: Refined,
    radius_km: float | None,
    workplace: Workplace | None = None,
    toxicity: Toxicity | None = None,
) -> FacilityAssessment:
    """A refined facility kept at its own-stack worst case (no weather or residents)."""
    worker, profile = _worker_view(item, toxicity or Toxicity(rfc=None, iur=None), workplace)
    return with_scenarios(_own_stack_assessment(item, radius_km, worker, profile))


def assess_all(
    items: Sequence[Refined],
    toxicity: Toxicity,
    radius_km: float | None,
    steps: Steps,
    settings: AssessmentSettings,
    workplace: Workplace | None = None,
) -> list[FacilityAssessment]:
    """The full chain for each refined facility, in the order given."""
    weather = _shared_weather(items, steps, settings)

    def one(item: Refined) -> FacilityAssessment:
        record = item.record
        here = weather[cell(record, settings.weather_cell_deg)]
        people = steps.people(record["latitude"], record["longitude"], radius_km)
        rate, stacks = record["emission_rate"], item.choice.stacks
        exposure = steps.exposure(rate, stacks, here, people, toxicity)
        partial = worst_case_only(item, radius_km, workplace, toxicity)
        return with_scenarios(
            {
                **partial,
                "level": "full",
                "meteorology": here,
                "population": people,
                "exposure": exposure,
            },
        )

    return in_pool(one, items, settings.max_workers)
