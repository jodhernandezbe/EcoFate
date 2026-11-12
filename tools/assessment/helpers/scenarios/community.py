"""Pathway: outdoor air, inhalation, general population (the stack plume and its residents)."""

from __future__ import annotations

from typing import Literal

from config.exposure import ExposureSettings, get_exposure_settings
from config.scenario import ScenarioSettings, get_scenario_settings
from models.transport.screening import Atmosphere, Stack
from tools.assessment.helpers.scenarios.factors import banded, factor
from tools.assessment.helpers.scenarios.receptors import Ranked, Weather, rank_tracts, stack_of
from tools.schemas import FacilityAssessment, ScenarioFactor, StackExposure, WorstCaseScenario

PATHWAY = "community_inhalation"
Quantity = Literal["hq", "cancer_risk"]
QUANTITIES: tuple[Quantity, ...] = ("hq", "cancer_risk")
_NO_STACK = "the stack has no value for this, so no concentration was computed from it"
_WORST_ONLY = "receptors were not evaluated: the facility was kept at its worst case only"


def _top(item: FacilityAssessment, quantity: Quantity) -> StackExposure | None:
    """The evaluated stack with the highest value of the quantity (the first on a tie)."""
    found = [r for r in item["exposure"]["results"] if r[quantity] is not None]
    return max(found, key=lambda r: r[quantity] or 0.0, default=None)


def _source(result: StackExposure) -> list[ScenarioFactor]:
    return [
        factor("stack_number", result["stack_number"]),
        factor("stack_source", result["stack_source"], reason="no source was named"),
        factor("stack_height", result["stack_height"], reason=_NO_STACK),
        factor("stack_diameter", result["stack_diameter"], reason=_NO_STACK),
        factor("exit_velocity", result["exit_velocity"], reason=_NO_STACK),
        factor("exit_temperature", result["exit_temperature"], reason=_NO_STACK),
    ]


def _release(item: FacilityAssessment) -> list[ScenarioFactor]:
    record = item["record"]
    year = f"TRI {record['reporting_year']}"
    return [
        factor("annual_release", record["total_release"], unit=record["unit"], source=year),
        factor("emission_rate", record["emission_rate"], source=f"{year} release over the hours"),
        factor(
            "operating_hours",
            record["operating_hours_per_year"],
            source=record["operating_hours_source"],
        ),
    ]


def _conditions(result: StackExposure) -> list[ScenarioFactor]:
    source = "worst case of the screening weather and distances"
    return [
        factor("stability_class", result["stability_class"], source=source),
        factor("wind_speed", result["wind_speed"], source=source),
        factor("distance", result["distance_m"], source=source),
        factor("effective_release_height", result["effective_release_height"], source=source),
    ]


def _model(settings: ExposureSettings) -> list[ScenarioFactor]:
    f = settings.factors
    return [
        factor("exposure_hours_per_day", f.exposure_time_hours_per_day),
        factor("exposure_days_per_year", f.exposure_frequency_days_per_year),
        factor("exposure_years", f.exposure_duration_years),
    ]


def _air(ambient_k: float) -> Atmosphere:
    exposure = get_exposure_settings()
    return Atmosphere(
        exposure.wind_exponent,
        exposure.potential_temperature_gradient,
        ambient_k,
        exposure.receptor_height_m,
    )


def _weather(result: StackExposure) -> Weather | None:
    maximum, stability, wind = (
        result["max_concentration"],
        result["stability_class"],
        result["wind_speed"],
    )
    if not maximum or stability is None or wind is None:
        return None
    return Weather(stability, wind, maximum, get_exposure_settings().annual_average_factor)


def _stack_at(item: FacilityAssessment, number: int) -> Stack | None:
    stacks = item["stacks"]
    return stack_of(stacks[number - 1]) if 0 < number <= len(stacks) else None


def _receptors(item: FacilityAssessment, result: StackExposure) -> Ranked:
    """The residents most affected under the scenario, or why there are none to name."""
    meteorology, population = item["meteorology"], item["population"]
    if item["level"] != "full" or meteorology is None or population is None:
        return Ranked([], _WORST_ONLY)
    stack, weather = _stack_at(item, result["stack_number"]), _weather(result)
    if stack is None or weather is None:
        return Ranked(
            [],
            "receptors were not evaluated: the scenario's stack or weather is missing",
        )
    settings = get_scenario_settings()
    limits = (settings.receptor_fraction, settings.max_receptors)
    air = _air(meteorology["ambient_temperature"])
    rate = item["record"]["emission_rate"]
    return rank_tracts(population.get("tracts", []), rate, stack, weather, air, limits)


def _factors(item: FacilityAssessment, result: StackExposure) -> list[ScenarioFactor]:
    model = _model(get_exposure_settings())
    return [*_source(result), *_release(item), *_conditions(result), *model]


def _scenario(
    item: FacilityAssessment,
    quantity: Quantity,
    settings: ScenarioSettings,
) -> WorstCaseScenario | None:
    result = _top(item, quantity)
    if result is None or (value := result[quantity]) is None:
        return None
    ranked = _receptors(item, result)
    tier, benchmark = banded(quantity, value)
    return WorstCaseScenario(
        pathway_key=PATHWAY,
        pathway=settings.pathways[PATHWAY],
        quantity=quantity,
        quantity_label=settings.quantities[quantity],
        value=value,
        tier=tier,
        benchmark=benchmark,
        factors=_factors(item, result),
        receptors=ranked.listed,
        receptors_note=ranked.note,
        notes=list(result["warnings"]),
    )


def community_inhalation(item: FacilityAssessment) -> list[WorstCaseScenario]:
    """The worst-case scenarios of the stack plume's hazard quotient and cancer risk."""
    settings = get_scenario_settings()
    built = [_scenario(item, quantity, settings) for quantity in QUANTITIES]
    return [scenario for scenario in built if scenario is not None]
