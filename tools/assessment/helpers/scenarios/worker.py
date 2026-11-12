"""Pathway: indoor air, inhalation, worker (the activity model or OSHA's measured samples)."""

from __future__ import annotations

from typing import Literal

from config.occupational import get_occupational_settings
from config.scenario import ScenarioSettings, get_scenario_settings
from tools.assessment.helpers.scenarios.factors import banded, factor
from tools.schemas import (
    FacilityAssessment,
    MonitoringSummary,
    OccupationalExposure,
    ScenarioFactor,
    ScenarioReceptor,
    WorkerCase,
    WorstCaseScenario,
)

PATHWAY = "worker_inhalation"
Quantity = Literal["oel_ratio", "hq", "cancer_risk"]
QUANTITIES: tuple[Quantity, ...] = ("oel_ratio", "hq", "cancer_risk")
MODEL_NAMES = {
    "ap42_loading": "AP-42 loading model",
    "penetration": "Penetration model",
    "mass_transfer": "Mass transfer coefficient model",
}
BAND_ESTIMATE = "the ECETOC TRA band estimate gives the 8-hour average directly"


def _cap(case: WorkerCase) -> str | None:
    if case["capped"] is None:
        return None
    return "applied" if case["capped"] else "not applied"


def _vapor(work: OccupationalExposure, case: WorkerCase) -> list[ScenarioFactor]:
    skipped = BAND_ESTIMATE if case["estimator"] == "ecetoc_tra" else None
    return [
        factor("generation_rate", case["generation_g_per_s"], reason=skipped),
        factor("vapor_pressure", work["vapor_pressure_mmhg"], source=work["vapor_pressure_source"]),
        factor(
            "molecular_weight",
            work["molecular_weight"],
            source=work["molecular_weight_source"],
        ),
    ]


def _activity(work: OccupationalExposure, case: WorkerCase) -> list[ScenarioFactor]:
    driving = work["driving_activity"]
    if driving is None:
        return [factor("worker_activity", None, reason=work["activity_reason"])]
    return [
        factor("worker_evidence", "Activity model"),
        factor("worker_activity", driving["label"], source=case["estimator"]),
        factor("activity_hours", driving["hours"]),
        factor("generation_model", MODEL_NAMES.get(driving["model"], driving["model"])),
        *_vapor(work, case),
    ]


def _ventilation(case: WorkerCase) -> list[ScenarioFactor]:
    return [
        factor("ventilation", case["airflow_m3_per_s"], reason="the two-zone model has no airflow"),
        factor("mixing_factor", case["mixing_factor"]),
        factor("room_volume", case["room_m3"]),
        factor("air_exchange", case["air_exchange_per_h"]),
        factor("saturation_cap", _cap(case)),
    ]


def _conditions(case: WorkerCase) -> list[ScenarioFactor]:
    return [
        *_ventilation(case),
        factor("workplace_concentration", case["workplace_concentration_mg_m3"]),
        factor("twa_concentration", case["twa_mg_m3"]),
    ]


def _years(found: MonitoringSummary) -> str:
    return f"{found['first_year']} to {found['last_year']}"


def _measured(found: MonitoringSummary, case: WorkerCase) -> list[ScenarioFactor]:
    source = found["source"]
    return [
        factor("worker_evidence", "OSHA monitoring data", source=source),
        factor("monitoring_level", found["level_note"] or found["naics_level"], source=source),
        factor("monitoring_samples", found["n_values"], source=source),
        factor("monitoring_nondetects", found["n_nondetect"], source=source),
        factor("monitoring_years", _years(found), source=source),
        factor("monitoring_p95", found["p95_mg_m3"], source=source),
        factor("twa_concentration", case["twa_mg_m3"], source=source),
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


def _factors(work: OccupationalExposure) -> list[ScenarioFactor]:
    case, found = work["worst_case"], work["monitoring"]
    if work["evidence"] == "monitoring" and found is not None:
        return [*_measured(found, case), *_model(work)]
    return [*_activity(work, case), *_conditions(case), *_model(work)]


def _schedule_note(work: OccupationalExposure) -> str:
    days, tenure = _worked_days(work), get_occupational_settings().tenure_years
    driving = work["driving_activity"]
    if work["evidence"] == "monitoring" or driving is None:
        return f"workers sampled in the industry, {days} days/yr, {tenure:g} years of work"
    task = f"{driving['label']}, {driving['hours']:g} h/day"
    return f"{task}, {days} days/yr, {tenure:g} years of work"


def _workers(work: OccupationalExposure) -> ScenarioReceptor:
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
        note=_schedule_note(work),
    )


def _scenario(
    item: FacilityAssessment,
    quantity: Quantity,
    settings: ScenarioSettings,
) -> WorstCaseScenario | None:
    work = item["occupational_exposure"]
    if (value := work["worst_case"][quantity]) is None:
        return None
    band, benchmark = banded(quantity, value)
    return WorstCaseScenario(
        pathway_key=PATHWAY,
        pathway=settings.pathways[PATHWAY],
        quantity=quantity,
        quantity_label=settings.quantities[quantity],
        value=value,
        tier=band,
        benchmark=benchmark,
        factors=_factors(work),
        receptors=[_workers(work)],
        receptors_note=None,
        notes=list(work["warnings"]),
    )


def worker_inhalation(item: FacilityAssessment) -> list[WorstCaseScenario]:
    """The worst-case scenarios of the worker screening, for the worst case of the headline."""
    settings = get_scenario_settings()
    built = [_scenario(item, quantity, settings) for quantity in QUANTITIES]
    return [scenario for scenario in built if scenario is not None]
