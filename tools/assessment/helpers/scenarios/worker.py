"""Pathway: indoor air, inhalation, worker (fugitive release in the workplace, ChemSTEER box)."""

from __future__ import annotations

from typing import Literal

from config.occupational import get_occupational_settings
from config.scenario import ScenarioSettings, get_scenario_settings
from tools.assessment.helpers.scenarios.factors import factor
from tools.schemas import (
    FacilityAssessment,
    OccupationalExposure,
    ScenarioFactor,
    ScenarioReceptor,
    VentilationTier,
    WorstCaseScenario,
)

PATHWAY = "worker_inhalation"
Quantity = Literal["oel_ratio", "hq", "cancer_risk"]
QUANTITIES: tuple[Quantity, ...] = ("oel_ratio", "hq", "cancer_risk")


def _release(item: FacilityAssessment) -> list[ScenarioFactor]:
    work = item["occupational_exposure"]
    schedule = item["operational_profile"]["schedule_source"]
    year = work["fugitive_reporting_year"]
    return [
        factor("fugitive_release", work["fugitive_release_kg_per_year"], source=f"TRI {year}"),
        factor("worker_operating_days", work["operating_days_per_year"], source=schedule),
        factor("shift_hours", work["hours_per_day"], source=schedule),
    ]


def _conditions(tier: VentilationTier) -> list[ScenarioFactor]:
    label = tier["label"]
    return [
        factor("ventilation", tier["ventilation_m3_per_s"], source=label),
        factor("mixing_factor", tier["mixing_factor"], source=label),
        factor("workplace_concentration", tier["workplace_concentration_mg_m3"]),
        factor("twa_concentration", tier["twa_mg_m3"]),
    ]


def _worked_days(work: OccupationalExposure) -> float | None:
    days = work["operating_days_per_year"]
    return None if days is None else min(days, get_occupational_settings().worker_days_per_year)


def _model(work: OccupationalExposure) -> list[ScenarioFactor]:
    return [
        factor("occupational_limit", work["oel_twa_mg_m3"], source=work["oel_source"]),
        factor("worker_days_per_year", _worked_days(work)),
        factor("tenure_years", get_occupational_settings().tenure_years),
    ]


def _workers(work: OccupationalExposure) -> ScenarioReceptor:
    days, tenure = _worked_days(work), get_occupational_settings().tenure_years
    note = f"{work['hours_per_day']} h/day, {days} days/yr, {tenure:g} years of work"
    return ScenarioReceptor(
        kind="workers",
        label="Workers",
        residents=None,
        age_distribution={},
        distance_m=None,
        bearing_deg=None,
        latitude=None,
        longitude=None,
        concentration=work["worst_case"]["twa_mg_m3"],
        fraction_of_maximum=None,
        note=note,
    )


def _benchmark(quantity: Quantity) -> float:
    limits = get_occupational_settings().thresholds
    return {
        "oel_ratio": limits.exceedance_ratio,
        "hq": limits.exceedance_hq,
        "cancer_risk": limits.exceedance_cancer_risk,
    }[quantity]


def _scenario(
    item: FacilityAssessment,
    quantity: Quantity,
    settings: ScenarioSettings,
) -> WorstCaseScenario | None:
    work = item["occupational_exposure"]
    tier = work["worst_case"]
    value = tier[quantity]
    if value is None:
        return None
    return WorstCaseScenario(
        pathway_key=PATHWAY,
        pathway=settings.pathways[PATHWAY],
        quantity=quantity,
        quantity_label=settings.quantities[quantity],
        value=value,
        tier=tier["risk_tier"],
        benchmark=_benchmark(quantity),
        factors=[*_release(item), *_conditions(tier), *_model(work)],
        receptors=[_workers(work)],
        receptors_note=None,
        notes=list(work["warnings"]),
    )


def worker_inhalation(item: FacilityAssessment) -> list[WorstCaseScenario]:
    """The worst-case scenarios of the worker screening, at the worst-case ventilation tier."""
    settings = get_scenario_settings()
    built = [_scenario(item, quantity, settings) for quantity in QUANTITIES]
    return [scenario for scenario in built if scenario is not None]
