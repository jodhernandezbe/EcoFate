"""Screening exposure and risk for one stack: worst case, representative case, doses, warnings."""

from __future__ import annotations

from collections.abc import Sequence

from config.exposure import STABILITY_CLASSES, ExposureSettings
from models.exposure.inhalation import (
    annual_from_one_hour,
    cancer_risk_from_iur,
    doses_by_age_band,
    exposure_concentration,
    hazard_quotient_from_rfc,
    highest_dose_band,
)
from models.transport.screening import Atmosphere, ScreeningResult, Stack, screening_maximum
from tools.exposure.helpers.inputs import is_number
from tools.schemas import (
    ExposureMetrics,
    Meteorology,
    Population,
    ScenarioResult,
    StackParameters,
    Toxicity,
)

DEFAULT_SOURCE = "screening default"
_STACK_FIELDS = ("stack_height", "stack_diameter", "exit_velocity", "exit_temperature")


def empty_scenario() -> ScenarioResult:
    """A scenario result with nothing computed."""
    return ScenarioResult(
        max_concentration=None,
        max_concentration_1h=None,
        distance_m=None,
        stability_class=None,
        wind_speed=None,
        effective_release_height=None,
        hq=None,
        cancer_risk=None,
    )


def _no_result(warnings: list[str], stack_source: str | None) -> ExposureMetrics:
    return ExposureMetrics(
        **empty_scenario(),
        stack_source=stack_source,
        add=None,
        add_band=None,
        add_by_band={},
        representative=empty_scenario(),
        warnings=warnings,
    )


def _stack(params: StackParameters) -> Stack | str:
    """Return the stack, or the reason it cannot be used."""
    values = {name: params.get(name) for name in _STACK_FIELDS}
    missing = [name for name, value in values.items() if value is None]
    if missing:
        return (
            f"the stack has no value for {', '.join(missing)}, "
            "so no concentration can be computed; "
            "stack values from another source are needed"
        )
    bad = [name for name, value in values.items() if not is_number(value) or float(value) <= 0]  # type: ignore[arg-type]
    if bad:
        return f"the stack value(s) {', '.join(bad)} are not positive numbers"
    return Stack(*(float(values[name]) for name in _STACK_FIELDS))  # type: ignore[arg-type]


def _input_problem(emission_rate: object, meteorology: Meteorology) -> str | None:
    if not is_number(emission_rate) or float(emission_rate) < 0:  # type: ignore[arg-type]
        return f"the emission rate {emission_rate!r} g/s is invalid: it must be a number >= 0"
    temperature = meteorology.get("ambient_temperature")
    if not is_number(temperature) or float(temperature) <= 0:  # type: ignore[arg-type]
        return "the ambient temperature is missing or invalid, which the plume rise needs"
    return None


def _representative(meteorology: Meteorology) -> tuple[str, float] | str:
    """Return the representative (class, 10 m wind speed), or the reason it cannot be used."""
    stability = str(meteorology.get("stability_class", "")).strip().upper()
    speed = meteorology.get("wind_speed")
    if stability not in STABILITY_CLASSES or not is_number(speed) or float(speed) <= 0:  # type: ignore[arg-type]
        return "the representative weather is invalid, so only the worst case is reported"
    return stability, float(speed)  # type: ignore[arg-type]


def _benchmark(value: object, *, positive: bool) -> float | None:
    if not is_number(value):
        return None
    number = float(value)  # type: ignore[arg-type]
    return number if (number > 0 if positive else number >= 0) else None


def _exposure_concentration(
    annual_ug_per_m3: float,
    settings: ExposureSettings,
    averaging_time_years: float,
) -> float:
    f = settings.factors
    return exposure_concentration(
        annual_ug_per_m3,
        f.exposure_time_hours_per_day,
        f.exposure_frequency_days_per_year,
        f.exposure_duration_years,
        averaging_time_years,
    )


def _risks(
    annual_ug_per_m3: float,
    toxicity: Toxicity,
    settings: ExposureSettings,
    notes: list[str],
) -> tuple[float | None, float | None]:
    rfc = _benchmark(toxicity.get("rfc"), positive=True)
    iur = _benchmark(toxicity.get("iur"), positive=False)
    hq = risk = None
    if rfc is None:
        notes.append("no usable RfC, so the hazard quotient is not computed")
    else:
        ec = _exposure_concentration(
            annual_ug_per_m3,
            settings,
            settings.factors.exposure_duration_years,
        )
        hq = hazard_quotient_from_rfc(ec, rfc)
    if iur is None:
        notes.append("no usable IUR, so the cancer risk is not computed")
    else:
        ec = _exposure_concentration(annual_ug_per_m3, settings, settings.factors.lifetime_years)
        risk = cancer_risk_from_iur(ec, iur)
    return hq, risk


def _scenario(
    emission_rate: float,
    stack: Stack,
    combinations: Sequence[tuple[str, float]],
    atmosphere: Atmosphere,
    toxicity: Toxicity,
    settings: ExposureSettings,
    notes: list[str],
) -> tuple[ScenarioResult, ScreeningResult]:
    found = screening_maximum(emission_rate, stack, combinations, settings.distances_m, atmosphere)
    annual = annual_from_one_hour(found.concentration_ug_per_m3, settings.annual_average_factor)
    hq, risk = _risks(annual, toxicity, settings, notes)
    result = ScenarioResult(
        max_concentration=annual,
        max_concentration_1h=found.concentration_ug_per_m3,
        distance_m=found.distance_m,
        stability_class=found.stability_class,
        wind_speed=found.wind_speed_10m_m_per_s,
        effective_release_height=found.effective_release_height_m,
        hq=hq,
        cancer_risk=risk,
    )
    return result, found


def _doses(
    annual_ug_per_m3: float,
    population: Population,
    settings: ExposureSettings,
    notes: list[str],
) -> dict[str, float]:
    rates = {b: v.inhalation_rate_m3_per_day for b, v in settings.age_bands.items()}
    weights = {b: v.body_weight_kg for b, v in settings.age_bands.items()}
    f = settings.factors
    try:
        doses = doses_by_age_band(
            annual_ug_per_m3,
            dict(population.get("age_distribution", {})),
            rates,
            weights,
            f.exposure_frequency_days_per_year,
            f.exposure_duration_years,
        )
    except ValueError as exc:
        notes.append(f"the age-band doses were not computed ({exc})")
        return {}
    if not doses:
        notes.append("no age band has residents, so no dose is reported")
    return doses


_GLOBAL_STACK = "AirToxScreen global default"
_PROCESS_STACK = "PSTK"


def _stack_notes(source: str | None) -> list[str]:
    """Say when the stack is not the facility's own: concentrations depend strongly on it."""
    if source == _GLOBAL_STACK:
        return [
            "the stack is the EPA global default (3 m high, 0.2 m wide, cold and slow), not this "
            "facility's own; a low, cold stack gives much higher concentrations than a real tall "
            "one, so these results are a generic worst-case-like screening value",
        ]
    if source == _PROCESS_STACK:
        return ["the stack is a default for this kind of process (PSTK), not the facility's own"]
    return []


def _standing_notes(
    meteorology: Meteorology,
    population: Population,
    found: ScreeningResult,
) -> list[str]:
    notes = [
        "the worst case is the screening maximum between 100 m and 10 km; "
        "it may fall where no one lives",
    ]
    if found.at_last_distance:
        notes.append(
            "the worst case is at the farthest distance evaluated, "
            "so the true maximum may lie farther away",
        )
    if meteorology.get("source") == DEFAULT_SOURCE:
        notes.append(
            "the meteorology is a screening default, "
            "so the representative result uses generic weather",
        )
    if population.get("source") == DEFAULT_SOURCE:
        notes.append("the population is a screening default, so the age mix is generic")
    return notes


def assess_exposure(
    emission_rate: float,
    stack_params: StackParameters,
    meteorology: Meteorology,
    population: Population,
    toxicity: Toxicity,
    settings: ExposureSettings,
) -> ExposureMetrics:
    """Screening concentration, dose and risks for one stack.

    Args:
        emission_rate: Source emission rate, in grams per second (g/s); >= 0.
        stack_params: One stack (m, m, m/s, K); any value may be None.
        meteorology: Representative weather (10 m wind speed in m/s, stability class, ambient
            temperature in K).
        population: Residents and age mix (percent per band).
        toxicity: RfC in mg/m^3 and IUR in (ug/m^3)^-1; either may be None.
        settings: Screening grid, distances, exposure factors, age-band rates and weights.

    Returns:
        The EPA SCREEN3-style worst case, the representative-weather case, the age-band doses
        and warnings. Anything that cannot be computed is None with a warning; no value is
        ever defaulted.
    """
    problem = _input_problem(emission_rate, meteorology)
    stack = _stack(stack_params)
    if problem is not None or isinstance(stack, str):
        return _no_result([problem or str(stack)], stack_params.get("source"))
    return _assess(
        emission_rate,
        stack,
        stack_params.get("source"),
        meteorology,
        population,
        toxicity,
        settings,
    )


def _atmosphere(meteorology: Meteorology, settings: ExposureSettings) -> Atmosphere:
    return Atmosphere(
        settings.wind_exponent,
        settings.potential_temperature_gradient,
        float(meteorology["ambient_temperature"]),
        settings.receptor_height_m,
    )


def _assess(
    emission_rate: float,
    stack: Stack,
    stack_source: str | None,
    meteorology: Meteorology,
    population: Population,
    toxicity: Toxicity,
    settings: ExposureSettings,
) -> ExposureMetrics:
    notes: list[str] = []
    worst, found, typical = _cases(emission_rate, stack, meteorology, toxicity, settings, notes)
    doses = _doses(float(worst["max_concentration"] or 0.0), population, settings, notes)
    top = highest_dose_band(doses)
    return ExposureMetrics(
        **worst,
        stack_source=stack_source,
        add=top[1] if top else None,
        add_band=top[0] if top else None,
        add_by_band=doses,
        representative=typical,
        warnings=_all_notes(notes, stack_source, meteorology, population, found),
    )


def _cases(
    emission_rate: float,
    stack: Stack,
    meteorology: Meteorology,
    toxicity: Toxicity,
    settings: ExposureSettings,
    notes: list[str],
) -> tuple[ScenarioResult, ScreeningResult, ScenarioResult]:
    """The worst case over the settings' grid, its screening search, and the typical case."""
    atmosphere = _atmosphere(meteorology, settings)
    grid = settings.combinations
    worst, found = _scenario(emission_rate, stack, grid, atmosphere, toxicity, settings, notes)
    typical = _representative_result(
        emission_rate,
        stack,
        meteorology,
        atmosphere,
        toxicity,
        settings,
        notes,
    )
    return worst, found, typical


def _all_notes(
    notes: list[str],
    stack_source: str | None,
    meteorology: Meteorology,
    population: Population,
    found: ScreeningResult,
) -> list[str]:
    return [
        *dict.fromkeys(notes),
        *_stack_notes(stack_source),
        *_standing_notes(meteorology, population, found),
    ]


def _representative_result(
    emission_rate: float,
    stack: Stack,
    meteorology: Meteorology,
    atmosphere: Atmosphere,
    toxicity: Toxicity,
    settings: ExposureSettings,
    notes: list[str],
) -> ScenarioResult:
    chosen = _representative(meteorology)
    if isinstance(chosen, str):
        notes.append(chosen)
        return empty_scenario()
    result, _ = _scenario(emission_rate, stack, [chosen], atmosphere, toxicity, settings, notes)
    return result
