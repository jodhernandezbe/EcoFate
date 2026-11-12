"""The worker screening of one facility, from the evidence hierarchy down to the warnings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict

from tools.assessment.helpers.activities.select import Selection, select_activities
from tools.assessment.helpers.activities.select import StageRoute as Route
from tools.assessment.helpers.monitoring.cehd import MonitoringResult
from tools.assessment.helpers.occupational import evidence, text
from tools.assessment.helpers.occupational.dosimetry import Benchmarks, empty_case
from tools.assessment.helpers.occupational.headline import Headline, headline
from tools.assessment.helpers.occupational.modelled import (
    Modelled,
    activity_view,
    driving_view,
    level_of,
    model_activities,
)
from tools.assessment.helpers.occupational.workplace import Sources, Workplace, default_sources
from tools.schemas import (
    DrivingActivity,
    FacilityRecord,
    MonitoringSummary,
    OccupationalExposure,
    OperationalProfile,
    ScenarioRoute,
    StageRoute,
    Toxicity,
    Volatility,
    WorkerActivity,
)


class _Inputs(TypedDict):
    molecular_weight: float | None
    molecular_weight_source: str | None
    vapor_pressure_mmhg: float | None
    vapor_pressure_source: str | None
    volatility: Volatility | None
    operating_days_per_year: float | None
    hours_per_day: float | None
    oel_twa_mg_m3: float | None
    oel_source: str | None
    rfc: float | None
    iur: float | None
    fugitive_release_kg_per_year: float | None
    fugitive_reporting_year: int | None
    fugitive_statement: str


class _Activities(TypedDict):
    driving_activity: DrivingActivity | None
    activities: list[WorkerActivity]
    activity_reason: str | None
    routes: list[StageRoute]


class _Measured(TypedDict):
    monitoring: MonitoringSummary | None
    monitoring_reason: str | None


def _inputs(
    record: FacilityRecord,
    profile: OperationalProfile,
    toxicity: Toxicity,
    workplace: Workplace,
) -> _Inputs:
    limits = workplace.limits
    return _Inputs(
        molecular_weight=workplace.molecular_weight,
        molecular_weight_source=workplace.molecular_weight_source,
        vapor_pressure_mmhg=workplace.vapor_pressure_mmhg,
        vapor_pressure_source=workplace.vapor_pressure_source,
        volatility=level_of(workplace, workplace.settings),
        operating_days_per_year=profile["operating_days_per_year"],
        hours_per_day=profile["hours_per_day"],
        oel_twa_mg_m3=limits["oel_twa_mg_m3"],
        oel_source=limits["oel_source"],
        rfc=toxicity.get("rfc"),
        iur=toxicity.get("iur"),
        fugitive_release_kg_per_year=record["fugitive_release_kg_per_year"],
        fugitive_reporting_year=record["fugitive_reporting_year"],
        fugitive_statement=text.FUGITIVE_STATEMENT,
    )


def _route(route: Route) -> StageRoute:
    scenarios = [
        ScenarioRoute(
            title=row.scenario,
            category=row.category,
            pages=row.pages,
            source=row.source,
            activities=list(row.activities),
        )
        for row in route.scenarios
    ]
    return StageRoute(
        stage=route.stage,
        generic_operation=list(route.generic_activities),
        scenarios=scenarios,
        note=route.note,
    )


def _activities(selection: Selection, modelled: Modelled) -> _Activities:
    results = modelled.results
    return _Activities(
        driving_activity=driving_view(results[0]) if results else None,
        activities=[activity_view(r) for r in results],
        activity_reason=modelled.reason,
        routes=[_route(r) for r in selection.routes],
    )


def _measured(found: MonitoringResult) -> _Measured:
    return _Measured(
        monitoring=evidence.summary_of(found),
        monitoring_reason=None if found.available else found.reason,
    )


def _warnings(
    selection: Selection,
    modelled: Modelled,
    found: MonitoringResult,
    head: Headline,
    b: Benchmarks,
) -> list[str]:
    reason = [f"worker activities not modelled: {modelled.reason}"] if modelled.reason else []
    no_data = [] if found.available or found.reason is None else [found.reason]
    return [
        *reason,
        *modelled.warnings,
        *selection.notes,
        *no_data,
        *head.warnings,
        *text.benchmark_warnings(b.oel, b.rfc, b.iur, b.days),
    ]


@dataclass(frozen=True)
class _Screened:
    selection: Selection
    modelled: Modelled
    found: MonitoringResult
    bench: Benchmarks
    head: Headline


def _screen(
    profile: OperationalProfile,
    toxicity: Toxicity,
    workplace: Workplace,
    tables: Sources,
) -> _Screened:
    sector = profile["cdr_sector"]
    code = sector["code"] if sector else None
    stages = profile["life_cycle_stage"]
    selection = select_activities(stages, code, workplace.settings, tables.crosswalk)
    modelled = model_activities(selection, workplace, tables)
    found = evidence.look_up(workplace, profile, tables)
    limit, days = workplace.limits["oel_twa_mg_m3"], profile["operating_days_per_year"]
    bench = Benchmarks(limit, toxicity.get("rfc"), toxicity.get("iur"), days)
    head = headline(modelled, found, bench, workplace.settings)
    return _Screened(selection, modelled, found, bench, head)


def occupational_exposure(
    record: FacilityRecord,
    profile: OperationalProfile,
    toxicity: Toxicity,
    workplace: Workplace,
    sources: Sources | None = None,
) -> OccupationalExposure:
    """The worker screening of ``record``: baseline and worst case, with every activity.

    Args:
        record: The inventory record; its fugitive release is carried as context only.
        profile: Its life cycle stages, CDR sector, NAICS code and operating schedule.
        toxicity: RfC (mg/m^3) and IUR ((ug/m^3)^-1) used for the community result too.
        workplace: The chemical's CAS number, properties and limits, and the settings.
        sources: The crosswalk and monitoring tables; the bundled ones when None.

    Returns:
        The evidence, the driving activity and every activity, the monitoring summary, the
        baseline and worst-case values and the warnings; a missing input gives None, never zero.
    """
    done = _screen(profile, toxicity, workplace, sources or default_sources())
    head = done.head
    return OccupationalExposure(
        **_inputs(record, profile, toxicity, workplace),
        **_activities(done.selection, done.modelled),
        **_measured(done.found),
        evidence=head.evidence,
        baseline=head.baseline,
        worst_case=head.worst_case,
        risk_tier=head.tier,
        assumptions=text.assumptions(head.evidence, bool(done.modelled.results)),
        warnings=_warnings(done.selection, done.modelled, done.found, head, done.bench),
    )


def _blank_inputs() -> _Inputs:
    return _Inputs(
        molecular_weight=None,
        molecular_weight_source=None,
        vapor_pressure_mmhg=None,
        vapor_pressure_source=None,
        volatility=None,
        operating_days_per_year=None,
        hours_per_day=None,
        oel_twa_mg_m3=None,
        oel_source=None,
        rfc=None,
        iur=None,
        fugitive_release_kg_per_year=None,
        fugitive_reporting_year=None,
        fugitive_statement=text.FUGITIVE_STATEMENT,
    )


def unavailable(reason: str) -> OccupationalExposure:
    """A worker result with nothing computed, for a caller that has no workplace information."""
    blank_activities = _Activities(
        driving_activity=None,
        activities=[],
        activity_reason=reason,
        routes=[],
    )
    return OccupationalExposure(
        **_blank_inputs(),
        **blank_activities,
        **_Measured(monitoring=None, monitoring_reason=reason),
        evidence=None,
        baseline=empty_case(),
        worst_case=empty_case(),
        risk_tier=None,
        assumptions=text.assumptions(None, False),
        warnings=[f"worker exposure not computed: {reason}"],
    )
