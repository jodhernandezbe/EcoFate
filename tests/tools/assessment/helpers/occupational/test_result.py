"""Tests for the worker screening of one facility (synthetic round numbers)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.tools.assessment.helpers.occupational.factories import (
    CAS,
    SECTOR,
    SETTINGS,
    TOX,
    monitoring,
    profile,
    release,
    row,
    sources,
    workplace,
)
from tools.assessment.helpers.occupational import (
    Sources,
    Workplace,
    occupational_exposure,
    unavailable,
)
from tools.schemas import OccupationalExposure, Toxicity

GOOD_ROWS = ["AAAA,325199,mg/m^3,10,1,2.0,9.0,2020,2021"]
ND_ROWS = ["AAAA,325199,mg/m^3,10,8,2.0,9.0,2020,2021"]
NO_ROWS = ["ZZZZ,325199,mg/m^3,10,1,2.0,9.0,2020,2021"]


def _run(
    *,
    stages: tuple[str, ...] = ("Manufacturing",),
    days: float | None = 250.0,
    kg: float | None = 1000.0,
    tox: Toxicity = TOX,
    place: Workplace | None = None,
    tables: Sources | None = None,
) -> OccupationalExposure:
    return occupational_exposure(
        release(kg),
        profile(stages, days=days),
        tox,
        place or workplace(),
        tables or sources(),
    )


def test_the_model_gives_a_baseline_and_a_worse_worst_case() -> None:
    result = _run()
    base, worst = result["baseline"], result["worst_case"]
    assert result["evidence"] == "activity_model"
    assert base["twa_mg_m3"] is not None and worst["twa_mg_m3"] is not None
    assert worst["twa_mg_m3"] >= base["twa_mg_m3"]
    assert base["oel_ratio"] == pytest.approx(base["twa_mg_m3"] / 5.0)
    assert result["risk_tier"] == base["risk_tier"]


def test_every_activity_is_listed_and_the_highest_worst_case_drives() -> None:
    result = _run()
    keys = list(SETTINGS.stage_activities["Manufacturing"])
    assert len(result["activities"]) == len(keys) == 4
    worst = [a["worst_case"]["twa_mg_m3"] for a in result["activities"]]
    assert worst == sorted(worst, reverse=True)
    driving = result["driving_activity"]
    assert driving is not None and driving["key"] == result["activities"][0]["key"]
    assert result["worst_case"]["twa_mg_m3"] == worst[0]


def test_the_case_carries_the_configuration_of_the_driving_activity() -> None:
    result = _run()
    case = result["worst_case"]
    assert case["setting"] in {"indoor", "outdoor"}
    assert case["estimator"] in {"mass_balance", "two_zone"}
    assert case["generation_g_per_s"] is not None and case["capped"] is not None
    assert result["molecular_weight"] == 100.0 and result["molecular_weight_source"] == "CompTox"
    assert result["vapor_pressure_mmhg"] == 10.0 and result["volatility"] == "within"


def test_the_fugitive_release_is_context_and_changes_no_value() -> None:
    small, large, none, zero = (_run(kg=kg) for kg in (1.0, 1.0e6, None, 0.0))
    for other in (large, none, zero):
        assert other["baseline"] == small["baseline"]
        assert other["worst_case"] == small["worst_case"]
        assert other["risk_tier"] == small["risk_tier"]
    assert large["fugitive_release_kg_per_year"] == 1.0e6
    assert large["fugitive_reporting_year"] == 2020
    assert "not used to compute any worker value" in large["fugitive_statement"]
    assert none["fugitive_release_kg_per_year"] is None


def test_no_activity_flag_and_no_monitoring_data_gives_nulls_and_both_reasons(
    tmp_path: Path,
) -> None:
    tables = sources(table=monitoring(tmp_path, NO_ROWS))
    result = _run(stages=(), place=workplace(cas=CAS), tables=tables)
    assert result["evidence"] is None and result["risk_tier"] is None
    assert result["activities"] == [] and result["driving_activity"] is None
    assert all(v is None for v in result["baseline"].values())
    assert result["worst_case"]["twa_mg_m3"] is None
    assert result["activity_reason"] == "the facility reported no activity"
    warnings = " ".join(result["warnings"])
    assert "reported no activity" in warnings and "No monitoring data" in warnings


def test_no_limit_gives_no_ratio_but_the_other_quantities() -> None:
    result = _run(place=workplace(oel=None))
    assert result["baseline"]["oel_ratio"] is None
    assert result["baseline"]["hq"] is not None and result["baseline"]["cancer_risk"] is not None
    assert any("limit" in w for w in result["warnings"])


def test_no_benchmarks_give_no_hq_or_risk() -> None:
    result = _run(tox=Toxicity(rfc=None, iur=None))
    assert result["baseline"]["hq"] is None and result["baseline"]["cancer_risk"] is None
    assert result["baseline"]["oel_ratio"] is not None


def test_no_schedule_keeps_the_twa_and_ratio_only() -> None:
    result = _run(days=None)
    base = result["baseline"]
    assert base["twa_mg_m3"] is not None and base["oel_ratio"] is not None
    assert base["hq"] is None and base["cancer_risk"] is None
    assert any("schedule" in w for w in result["warnings"])


def test_a_missing_molecular_weight_models_nothing_and_names_it() -> None:
    result = _run(place=workplace(weight=None))
    assert result["evidence"] is None and result["activities"] == []
    assert result["activity_reason"] is not None and "molecular weight" in result["activity_reason"]
    assert any("molecular weight" in w for w in result["warnings"])
    assert result["worst_case"]["twa_mg_m3"] is None


@pytest.mark.parametrize("pressure", [None, 0.0, -1.0, float("nan")])
def test_a_missing_or_unusable_vapor_pressure_models_nothing(pressure: float | None) -> None:
    result = _run(place=workplace(pressure=pressure))
    assert result["activities"] == [] and result["volatility"] is None
    assert any("vapor pressure" in w for w in result["warnings"])


def test_below_the_range_nothing_is_modelled_and_dust_is_not_either() -> None:
    result = _run(place=workplace(pressure=1e-6))
    assert result["volatility"] == "below" and result["activities"] == []
    assert result["activity_reason"] is not None
    assert (
        "too little volatile" in result["activity_reason"] and "dust" in result["activity_reason"]
    )


def test_above_the_range_each_activity_names_its_estimator() -> None:
    result = _run(place=workplace(pressure=95.0))
    assert result["volatility"] == "above"
    estimators = {a["typical"]["estimator"] for a in result["activities"]}
    assert estimators <= {"mass_balance", "two_zone", "ecetoc_tra"}


def test_monitoring_is_the_headline_and_the_modelled_activities_stay(tmp_path: Path) -> None:
    tables = sources(table=monitoring(tmp_path, GOOD_ROWS))
    result = _run(place=workplace(cas=CAS), tables=tables)
    assert result["evidence"] == "monitoring"
    assert result["baseline"]["twa_mg_m3"] == 2.0 and result["worst_case"]["twa_mg_m3"] == 9.0
    assert result["worst_case"]["estimator"] == "monitoring"
    assert result["worst_case"]["oel_ratio"] == pytest.approx(9.0 / 5.0)
    assert len(result["activities"]) == 4 and result["driving_activity"] is not None
    assert result["monitoring"] is not None and result["monitoring"]["n_values"] == 10
    assert result["monitoring_reason"] is None


def test_a_median_below_detection_takes_the_band_from_the_worst_case(tmp_path: Path) -> None:
    tables = sources(table=monitoring(tmp_path, ND_ROWS))
    result = _run(place=workplace(cas=CAS), tables=tables)
    assert result["evidence"] == "monitoring"
    assert result["baseline"]["twa_mg_m3"] is None and result["baseline"]["risk_tier"] is None
    assert result["worst_case"]["twa_mg_m3"] == 9.0
    assert result["risk_tier"] == result["worst_case"]["risk_tier"] is not None
    assert any("below detection" in w for w in result["warnings"])


def test_too_few_samples_fall_back_to_the_model(tmp_path: Path) -> None:
    few = ["AAAA,325199,mg/m^3,2,0,2.0,9.0,2020,2021"]
    tables = sources(table=monitoring(tmp_path, few))
    result = _run(place=workplace(cas=CAS), tables=tables)
    assert result["evidence"] == "activity_model" and result["monitoring"] is None
    assert result["monitoring_reason"] is not None


@pytest.mark.parametrize("cas", [None, "", "71-43-3", "not a cas"])
def test_an_invalid_cas_looks_up_no_monitoring(cas: str | None, tmp_path: Path) -> None:
    tables = sources(table=monitoring(tmp_path, GOOD_ROWS))
    result = _run(place=workplace(cas=cas), tables=tables)
    assert result["evidence"] == "activity_model" and result["monitoring"] is None
    assert result["monitoring_reason"] is not None and "CAS" in result["monitoring_reason"]


def test_the_routes_name_the_generic_operation_and_the_scenario() -> None:
    tables = sources((row("Manufacturing", "Synthetic ESD", "drum_unloading"),))
    result = occupational_exposure(release(), profile(sector=True), TOX, workplace(), tables)
    (route,) = result["routes"]
    assert route["stage"] == "Manufacturing"
    assert route["generic_operation"] == list(SETTINGS.stage_activities["Manufacturing"])
    assert route["scenarios"][0]["title"] == "Synthetic ESD"
    assert route["scenarios"][0]["source"] == "A source"
    assert SECTOR["code"] == "IS99"
    assert "drum_unloading" in {a["key"] for a in result["activities"]}


def test_the_assumptions_state_the_screening_and_the_model() -> None:
    text = " ".join(_run()["assumptions"])
    for phrase in (
        "not an OSHA compliance determination",
        "driving worker activity",
        "not observed at the facility",
        "pure chemical",
        "full 8-hour shift",
        "not this plant's",
        "no local exhaust ventilation or protective equipment",
        "Dermal exposure and particulate",
    ):
        assert phrase in text


def test_a_measured_headline_says_so_in_the_assumptions(tmp_path: Path) -> None:
    tables = sources(table=monitoring(tmp_path, GOOD_ROWS))
    text = " ".join(_run(place=workplace(cas=CAS), tables=tables)["assumptions"])
    assert "OSHA's measured personal air samples" in text


def test_unavailable_has_nothing_computed() -> None:
    result = unavailable("no workplace")
    assert result["evidence"] is None and result["risk_tier"] is None
    assert result["baseline"]["twa_mg_m3"] is None
    assert result["warnings"] == ["worker exposure not computed: no workplace"]
