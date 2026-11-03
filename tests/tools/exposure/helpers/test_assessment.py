"""Tests for tools.exposure.helpers.assessment (synthetic round-number inputs)."""

from __future__ import annotations

import math
from dataclasses import replace

import pytest

from config.exposure import load_exposure_settings
from models.transport.screening import Atmosphere, ScreeningResult, Stack, screening_maximum
from tools.exposure.helpers.assessment import (
    DEFAULT_SOURCE,
    _standing_notes,  # pyright: ignore[reportPrivateUsage]
    assess_exposure,
)
from tools.schemas import ExposureMetrics, Meteorology, Population, StackParameters, Toxicity

SETTINGS = load_exposure_settings()
Q = 0.5  # g/s


def _stack(**changes: float | None) -> StackParameters:
    base: dict[str, float | None] = {
        "stack_height": 30.0,
        "stack_diameter": 2.0,
        "exit_velocity": 10.0,
        "exit_temperature": 400.0,
    }
    base.update(changes)
    return StackParameters(**base, source="NEI", scc=None, warnings=[])  # type: ignore[typeddict-item]


def _met(**changes: object) -> Meteorology:
    base: dict[str, object] = {
        "wind_speed": 4.0,
        "wind_direction": 270.0,
        "stability_class": "D",
        "ambient_temperature": 288.0,
        "source": "Open-Meteo era5 reanalysis 2022",
        "warnings": [],
    }
    base.update(changes)
    return Meteorology(**base)  # type: ignore[typeddict-item]


def _pop(shares: dict[str, float] | None = None, source: str = "Census ACS 2023") -> Population:
    bands = {"0-4": 10.0, "5-17": 20.0, "18-64": 50.0, "65+": 20.0} if shares is None else shares
    return Population(total_population=1000, age_distribution=bands, source=source, warnings=[])


TOX = Toxicity(rfc=0.01, iur=1e-5)


def _run(
    q: float = Q,
    stack: StackParameters | None = None,
    met: Meteorology | None = None,
    pop: Population | None = None,
    tox: Toxicity | None = None,
) -> ExposureMetrics:
    return assess_exposure(q, stack or _stack(), met or _met(), pop or _pop(), tox or TOX, SETTINGS)


def _all_null(result: ExposureMetrics) -> bool:
    numbers = [
        v
        for k, v in result.items()
        if k not in ("warnings", "representative", "add_by_band", "stack_source")
    ]
    reps = list(result["representative"].values())
    return all(v is None for v in [*numbers, *reps]) and result["add_by_band"] == {}


def test_worst_case_is_the_screen3_search_times_the_annual_factor() -> None:
    result = _run()
    found = screening_maximum(
        Q,
        Stack(30.0, 2.0, 10.0, 400.0),
        SETTINGS.combinations,
        SETTINGS.distances_m,
        Atmosphere(SETTINGS.wind_exponent, SETTINGS.potential_temperature_gradient, 288.0, 0.0),
    )
    assert result["max_concentration_1h"] == pytest.approx(found.concentration_ug_per_m3)
    assert result["max_concentration"] == pytest.approx(found.concentration_ug_per_m3 * 0.08)
    assert (result["stability_class"], result["distance_m"]) == (
        found.stability_class,
        found.distance_m,
    )
    assert result["wind_speed"] == found.wind_speed_10m_m_per_s
    assert result["effective_release_height"] == pytest.approx(found.effective_release_height_m)


def test_hazard_quotient_and_cancer_risk_follow_the_resident_air_equations() -> None:
    result = _run()
    c = result["max_concentration"]
    assert c is not None
    ec_noncancer = c * (24 / 24) * (350 / 365) * (26 / 26)
    ec_cancer = c * (350 / 365) * (26 / 70)
    assert result["hq"] == pytest.approx(ec_noncancer / (0.01 * 1000))
    assert result["cancer_risk"] == pytest.approx(ec_cancer * 1e-5)


def test_the_representative_case_does_not_exceed_the_worst_case() -> None:
    result = _run()
    rep = result["representative"]
    assert rep["stability_class"] == "D"
    assert rep["wind_speed"] == 4.0
    assert rep["max_concentration"] is not None and result["max_concentration"] is not None
    assert rep["max_concentration"] <= result["max_concentration"]
    assert rep["hq"] is not None and rep["cancer_risk"] is not None


def test_doses_are_reported_for_the_bands_present_and_the_highest_is_named() -> None:
    result = _run()
    assert set(result["add_by_band"]) == {"0-4", "5-17", "18-64", "65+"}
    assert result["add"] == max(result["add_by_band"].values())
    assert result["add_band"] == "0-4"  # the child band breathes the most per kilogram


def test_an_absent_band_gets_no_dose() -> None:
    result = _run(pop=_pop({"0-4": 0.0, "5-17": 0.0, "18-64": 100.0, "65+": 0.0}))
    assert set(result["add_by_band"]) == {"18-64"}
    assert result["add_band"] == "18-64"


def _ratio(a: float | None, b: float | None) -> float:
    assert a is not None and b is not None
    return a / b


def test_doubling_the_emission_doubles_every_concentration() -> None:
    one, two = _run(q=Q), _run(q=2 * Q)
    assert _ratio(two["max_concentration"], one["max_concentration"]) == pytest.approx(2.0)
    rep_one, rep_two = one["representative"], two["representative"]
    assert _ratio(rep_two["max_concentration"], rep_one["max_concentration"]) == pytest.approx(2.0)
    assert _ratio(two["hq"], one["hq"]) == pytest.approx(2.0)
    assert (two["distance_m"], two["stability_class"]) == (
        one["distance_m"],
        one["stability_class"],
    )


def test_zero_emission_gives_zeros_not_an_error() -> None:
    result = _run(q=0.0)
    assert result["max_concentration"] == 0.0
    assert result["hq"] == 0.0 and result["cancer_risk"] == 0.0
    assert result["add"] == 0.0


def test_no_iur_nulls_only_the_cancer_risk() -> None:
    result = _run(tox=Toxicity(rfc=0.01, iur=None))
    assert result["cancer_risk"] is None and result["hq"] is not None
    assert result["representative"]["cancer_risk"] is None
    assert any("IUR" in w for w in result["warnings"])


def test_no_rfc_nulls_only_the_hazard_quotient() -> None:
    result = _run(tox=Toxicity(rfc=None, iur=1e-5))
    assert result["hq"] is None and result["cancer_risk"] is not None
    assert any("RfC" in w for w in result["warnings"])


@pytest.mark.parametrize("rfc", [0.0, -1.0, math.nan])
def test_an_unusable_rfc_is_treated_as_missing(rfc: float) -> None:
    assert _run(tox=Toxicity(rfc=rfc, iur=1e-5))["hq"] is None


@pytest.mark.parametrize("iur", [-1e-5, math.nan])
def test_an_unusable_iur_is_treated_as_missing(iur: float) -> None:
    assert _run(tox=Toxicity(rfc=0.01, iur=iur))["cancer_risk"] is None


def test_a_zero_iur_is_a_real_value() -> None:
    assert _run(tox=Toxicity(rfc=0.01, iur=0.0))["cancer_risk"] == 0.0


def test_both_benchmarks_missing_still_gives_concentrations() -> None:
    result = _run(tox=Toxicity(rfc=None, iur=None))
    assert result["hq"] is None and result["cancer_risk"] is None
    assert result["max_concentration"] is not None and result["add"] is not None


@pytest.mark.parametrize(
    "field",
    ["stack_height", "stack_diameter", "exit_velocity", "exit_temperature"],
)
def test_a_stack_with_a_missing_value_gives_nulls_and_a_warning(field: str) -> None:
    result = _run(stack=_stack(**{field: None}))
    assert _all_null(result)
    assert field in result["warnings"][0]
    assert "another source" in result["warnings"][0]


@pytest.mark.parametrize("value", [0.0, -5.0, math.nan])
def test_a_non_positive_stack_value_gives_nulls(value: float) -> None:
    result = _run(stack=_stack(exit_velocity=value))
    assert _all_null(result)
    assert "exit_velocity" in result["warnings"][0]


@pytest.mark.parametrize("rate", [-1.0, math.nan, math.inf, True, None, "5"])
def test_an_invalid_emission_rate_gives_nulls(rate: object) -> None:
    result = assess_exposure(rate, _stack(), _met(), _pop(), TOX, SETTINGS)  # type: ignore[arg-type]
    assert _all_null(result)
    assert "emission rate" in result["warnings"][0]


@pytest.mark.parametrize("temperature", [None, 0.0, -5.0, math.nan, "cold"])
def test_a_missing_ambient_temperature_gives_nulls_not_a_default(temperature: object) -> None:
    result = _run(met=_met(ambient_temperature=temperature))
    assert _all_null(result)
    assert "ambient temperature" in result["warnings"][0]


@pytest.mark.parametrize(
    "changes",
    [{"stability_class": "G"}, {"stability_class": ""}, {"wind_speed": 0.0}, {"wind_speed": None}],
)
def test_invalid_representative_weather_nulls_only_the_representative_case(
    changes: dict[str, object],
) -> None:
    result = _run(met=_met(**changes))
    assert result["max_concentration"] is not None
    assert all(v is None for v in result["representative"].values())
    assert any("representative weather is invalid" in w for w in result["warnings"])


def test_the_stability_class_letter_is_case_insensitive() -> None:
    assert _run(met=_met(stability_class=" d "))["representative"]["stability_class"] == "D"


def test_a_default_meteorology_is_called_out() -> None:
    result = _run(met=_met(source=DEFAULT_SOURCE))
    assert any("meteorology is a screening default" in w for w in result["warnings"])


def test_a_default_population_is_called_out() -> None:
    result = _run(pop=_pop(source=DEFAULT_SOURCE))
    assert any("population is a screening default" in w for w in result["warnings"])


def test_real_inputs_do_not_trigger_default_warnings() -> None:
    assert not any("screening default" in w for w in _run()["warnings"])


def test_the_worst_case_may_be_where_nobody_lives_is_always_said() -> None:
    assert any("no one lives" in w for w in _run()["warnings"])


def test_the_edge_of_the_range_is_flagged() -> None:
    far = ScreeningResult(1.0, 10_000.0, "F", 1.0, 1.0, 100.0, True)
    near = replace(far, at_last_distance=False)
    assert any("farther away" in w for w in _standing_notes(_met(), _pop(), far))
    assert not any("farther away" in w for w in _standing_notes(_met(), _pop(), near))


def test_no_band_with_residents_is_reported() -> None:
    result = _run(pop=_pop({"0-4": 0.0, "5-17": 0.0, "18-64": 0.0, "65+": 0.0}))
    assert result["add"] is None and result["add_by_band"] == {}
    assert any("no age band has residents" in w for w in result["warnings"])


def test_an_unknown_age_band_nulls_the_doses_with_a_warning() -> None:
    result = _run(pop=_pop({"teens": 100.0}))
    assert result["add"] is None
    assert any("not computed" in w for w in result["warnings"])
    assert result["max_concentration"] is not None


def test_it_is_deterministic() -> None:
    assert _run() == _run()


def test_warnings_are_not_repeated() -> None:
    warnings = _run(tox=Toxicity(rfc=None, iur=None))["warnings"]
    assert len(warnings) == len(set(warnings))


def _sourced(source: str | None, **changes: float | None) -> StackParameters:
    return StackParameters(**{**_stack(**changes), "source": source})  # type: ignore[typeddict-item]


def test_the_stack_source_is_echoed() -> None:
    for source in ("NEI", "PSTK", None):
        assert _run(stack=_sourced(source))["stack_source"] == source


def test_the_global_default_stack_is_called_out_as_generic() -> None:
    result = _run(stack=_sourced("AirToxScreen global default"))
    assert result["stack_source"] == "AirToxScreen global default"
    assert any(
        "EPA global default" in w and "not this facility's own" in w for w in result["warnings"]
    )


def test_a_process_default_stack_is_called_out() -> None:
    result = _run(stack=_sourced("PSTK"))
    assert any("this kind of process (PSTK)" in w for w in result["warnings"])


def test_the_facilitys_own_stack_needs_no_stack_warning() -> None:
    warnings = _run(stack=_sourced("NEI"))["warnings"]
    assert not any("global default" in w or "PSTK" in w for w in warnings)


def test_the_source_is_kept_even_when_nothing_can_be_computed() -> None:
    result = _run(stack=_sourced("PSTK", exit_temperature=None))
    assert result["max_concentration"] is None and result["stack_source"] == "PSTK"


def test_the_generic_stack_gives_much_higher_concentrations_than_a_tall_hot_one() -> None:
    generic = _sourced(
        "AirToxScreen global default",
        stack_height=3.0,
        stack_diameter=0.2,
        exit_velocity=4.0,
        exit_temperature=295.4,
    )
    own = _run()["max_concentration"]
    low = _run(stack=generic)["max_concentration"]
    assert own is not None and low is not None and low > 100 * own
