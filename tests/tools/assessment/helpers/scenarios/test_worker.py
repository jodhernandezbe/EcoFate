"""Tests for the worker inhalation scenarios: the driving activity or the measured samples."""

from __future__ import annotations

from config.occupational import get_occupational_settings
from config.risk_bands import get_risk_bands
from tests.tools.assessment.helpers.scenarios.items import assessed
from tools.assessment.helpers.scenarios.worker import worker_inhalation
from tools.schemas import (
    FacilityAssessment,
    MonitoringSummary,
    Toxicity,
    WorkerCase,
    WorstCaseScenario,
)


def _by(scenarios: list[WorstCaseScenario], quantity: str) -> WorstCaseScenario:
    return next(s for s in scenarios if s["quantity"] == quantity)


def _factor(scenario: WorstCaseScenario, key: str):  # noqa: ANN202
    return next(f for f in scenario["factors"] if f["key"] == key)


def _measured(item: FacilityAssessment) -> FacilityAssessment:
    """The same facility with its headline resting on synthetic monitoring values."""
    work = item["occupational_exposure"]
    found = MonitoringSummary(
        imis_code="0000",
        naics_level="3251",
        level_note=None,
        n_values=40,
        n_nondetect=5,
        median_mg_m3=1.0,
        p95_mg_m3=9.0,
        original_unit="mg/m^3",
        unit_note=None,
        first_year=2016,
        last_year=2025,
        reason=None,
        source="OSHA CEHD",
        statements=[],
    )
    worst: WorkerCase = {**work["worst_case"], "estimator": "monitoring", "twa_mg_m3": 9.0}
    return {
        **item,
        "occupational_exposure": {
            **work,
            "evidence": "monitoring",
            "monitoring": found,
            "worst_case": worst,
        },
    }


def test_the_scenario_is_the_worst_case_of_the_driving_activity() -> None:
    item = assessed()
    scenario = _by(worker_inhalation(item), "oel_ratio")
    work = item["occupational_exposure"]
    case, driving = work["worst_case"], work["driving_activity"]
    assert driving is not None
    assert scenario["value"] == case["oel_ratio"]
    assert _factor(scenario, "worker_activity")["value"] == driving["label"]
    assert _factor(scenario, "activity_hours")["value"] == driving["hours"]
    assert _factor(scenario, "generation_rate")["value"] == case["generation_g_per_s"]
    assert scenario["pathway"] == "Indoor Air → Inhalation → Worker"


def test_the_chemical_and_the_ventilation_are_factors_with_their_sources() -> None:
    item = assessed(vapor_pressure=10.0)
    scenario = _by(worker_inhalation(item), "oel_ratio")
    case = item["occupational_exposure"]["worst_case"]
    assert (
        _factor(scenario, "vapor_pressure")["value"],
        _factor(scenario, "vapor_pressure")["source"],
    ) == (10.0, "test")
    assert _factor(scenario, "molecular_weight")["value"] == 100.0
    assert _factor(scenario, "ventilation")["value"] == case["airflow_m3_per_s"]
    assert _factor(scenario, "mixing_factor")["value"] == case["mixing_factor"] == 0.1
    assert _factor(scenario, "saturation_cap")["value"] in {"applied", "not applied"}
    limit = _factor(scenario, "occupational_limit")
    assert (limit["value"], limit["source"]) == (5.0, "OSHA PEL-TWA (PubChem)")


def test_the_fugitive_release_is_not_a_factor() -> None:
    keys = {f["key"] for f in _by(worker_inhalation(assessed()), "oel_ratio")["factors"]}
    assert not {"fugitive_release", "shift_hours", "worker_operating_days"} & keys


def test_the_workers_are_the_receptors_with_the_activity_and_schedule_used() -> None:
    item = assessed()
    scenario = _by(worker_inhalation(item), "hq")
    (workers,) = scenario["receptors"]
    assert workers["kind"] == "workers" and workers["residents"] is None
    driving = item["occupational_exposure"]["driving_activity"]
    assert driving is not None
    tenure = get_occupational_settings().tenure_years
    expected = (
        f"{driving['label']}, {driving['hours']:g} h/day, 250.0 days/yr, {tenure:g} years of work"
    )
    assert workers["note"] == expected
    assert _factor(scenario, "worker_days_per_year")["value"] == 250.0


def test_a_measured_headline_lists_the_evidence_not_the_model() -> None:
    scenario = _by(worker_inhalation(_measured(assessed())), "oel_ratio")
    keys = {f["key"] for f in scenario["factors"]}
    assert _factor(scenario, "worker_evidence")["value"] == "OSHA monitoring data"
    assert _factor(scenario, "monitoring_level")["value"] == "3251"
    assert _factor(scenario, "monitoring_samples")["value"] == 40
    assert _factor(scenario, "monitoring_nondetects")["value"] == 5
    assert _factor(scenario, "monitoring_years")["value"] == "2016 to 2025"
    assert _factor(scenario, "monitoring_p95")["value"] == 9.0
    assert not {"generation_rate", "worker_activity", "ventilation"} & keys
    assert "sampled in the industry" in (scenario["receptors"][0]["note"] or "")


def test_the_benchmark_is_the_upper_band_boundary_of_the_quantity() -> None:
    bands = get_risk_bands()
    scenarios = worker_inhalation(assessed())
    assert _by(scenarios, "oel_ratio")["benchmark"] == bands.oel_ratio_upper
    assert _by(scenarios, "hq")["benchmark"] == bands.hq_upper
    assert _by(scenarios, "cancer_risk")["benchmark"] == bands.cancer_risk_upper


def test_each_scenario_tier_is_the_band_of_its_own_quantity() -> None:
    for scenario in worker_inhalation(assessed()):
        lower, upper = get_risk_bands().boundaries(scenario["quantity"])  # type: ignore[arg-type]
        expected = "high" if scenario["value"] >= upper else "moderate"
        assert scenario["tier"] == (expected if scenario["value"] >= lower else "low")


def test_without_a_limit_there_is_no_ratio_scenario() -> None:
    scenarios = worker_inhalation(assessed(oel=None))
    assert "oel_ratio" not in {s["quantity"] for s in scenarios}
    assert {"hq", "cancer_risk"} <= {s["quantity"] for s in scenarios}


def test_without_values_there_is_no_scenario() -> None:
    item = assessed(oel=None, toxicity=Toxicity(rfc=None, iur=None))
    assert worker_inhalation(item) == []


def test_a_higher_vapor_pressure_gives_a_larger_ratio() -> None:
    small = _by(worker_inhalation(assessed(vapor_pressure=1.0)), "oel_ratio")["value"]
    large = _by(worker_inhalation(assessed(vapor_pressure=10.0)), "oel_ratio")["value"]
    assert large > small
