"""Tests for the community inhalation scenarios: stack choice, factors, tier and receptors."""

from __future__ import annotations

import pytest

from config.risk_bands import get_risk_bands
from tests.tools.assessment.helpers.scenarios.items import HIGH, LOW, RATE, assessed, tract
from tools.assessment.helpers.scenarios.community import community_inhalation
from tools.schemas import StackParameters, Toxicity, WorstCaseScenario


def _by(scenarios: list[WorstCaseScenario], quantity: str) -> WorstCaseScenario:
    return next(s for s in scenarios if s["quantity"] == quantity)


def _factor(scenario: WorstCaseScenario, key: str):  # noqa: ANN202
    return next(f for f in scenario["factors"] if f["key"] == key)


def test_the_scenario_names_the_stack_that_gave_the_highest_value() -> None:
    item = assessed()
    scenario = _by(community_inhalation(item), "hq")
    range_ = item["exposure"]["range"]
    assert range_ is not None and range_["hq"] is not None
    assert _factor(scenario, "stack_number")["value"] == range_["hq"]["high_stack"] == 1
    assert scenario["value"] == pytest.approx(range_["hq"]["high"])
    assert _factor(scenario, "stack_height")["value"] == LOW["stack_height"]
    assert scenario["pathway"] == "Outdoor Air → Inhalation → General Population"


def test_every_group_is_filled_from_tool_values() -> None:
    scenario = _by(community_inhalation(assessed()), "hq")
    groups = {f["group"] for f in scenario["factors"]}
    assert groups == {"source", "release", "conditions", "receptor_model"}
    result = assessed()["exposure"]["results"][0]
    assert _factor(scenario, "stability_class")["value"] == result["stability_class"]
    assert _factor(scenario, "distance")["value"] == result["distance_m"]
    assert _factor(scenario, "emission_rate")["value"] == RATE


def test_a_release_keeps_the_unit_it_was_reported_in() -> None:
    scenario = _by(community_inhalation(assessed()), "hq")
    release = _factor(scenario, "annual_release")
    assert (release["unit"], release["source"]) == ("Pounds", "TRI 2020")


def test_a_factor_nobody_reported_is_listed_with_its_reason() -> None:
    unsourced: StackParameters = {**HIGH, "source": None}
    scenario = _by(community_inhalation(assessed(stacks=[unsourced])), "hq")
    source = _factor(scenario, "stack_source")
    assert (source["value"], source["reason"]) == (None, "no source was named")


def test_no_cancer_risk_scenario_without_a_unit_risk() -> None:
    scenarios = community_inhalation(assessed(toxicity=Toxicity(rfc=1e-3, iur=None)))
    assert [s["quantity"] for s in scenarios] == ["hq"]
    assert {s["quantity"] for s in community_inhalation(assessed())} == {"hq", "cancer_risk"}


def test_the_tier_is_the_band_of_the_quantity_alone() -> None:
    high = community_inhalation(assessed(toxicity=Toxicity(rfc=1e-9, iur=None)))
    low = community_inhalation(assessed(toxicity=Toxicity(rfc=1e9, iur=None)))
    assert (high[0]["tier"], low[0]["tier"]) == ("high", "low")
    assert high[0]["benchmark"] == get_risk_bands().hq_upper


def test_a_worst_case_only_facility_has_a_scenario_without_receptors() -> None:
    scenario = _by(community_inhalation(assessed(level="worst")), "hq")
    assert scenario["receptors"] == []
    assert "worst case only" in (scenario["receptors_note"] or "")


def test_a_tract_at_the_maximums_distance_is_the_first_receptor_with_the_maximum() -> None:
    item = assessed()
    maximum = item["exposure"]["results"][0]
    near = tract("99001000100", maximum["distance_m"] or 0.0)
    item = assessed(tracts=[tract("99001000200", 9_000.0), near])
    scenario = _by(community_inhalation(item), "hq")
    first = scenario["receptors"][0]
    assert first["label"] == "99001000100"
    assert first["fraction_of_maximum"] == pytest.approx(1.0)
    assert first["concentration"] == pytest.approx(maximum["max_concentration"])
    assert (first["residents"], first["bearing_deg"]) == (100, 90.0)


def test_receptors_are_ranked_by_concentration_and_cut_at_the_fraction() -> None:
    item = assessed()
    top = item["exposure"]["results"][0]["distance_m"] or 0.0
    tracts = [tract("A", top * 1.2), tract("B", top), tract("C", 10_000.0)]
    scenario = _by(community_inhalation(assessed(tracts=tracts)), "hq")
    shown = [r["label"] for r in scenario["receptors"]]
    values = [r["concentration"] or 0.0 for r in scenario["receptors"]]
    assert shown[0] == "B" and values == sorted(values, reverse=True)
    assert "C" not in shown


def test_nobody_where_the_maximum_falls_is_said_not_left_empty() -> None:
    far = [tract("N1", 9_500.0), tract("N2", 9_900.0)]
    scenario = _by(community_inhalation(assessed(tracts=far)), "hq")
    assert scenario["receptors"] == []
    assert "no resident lives where the maximum falls" in (scenario["receptors_note"] or "")
    assert "N1" in (scenario["receptors_note"] or "")


def test_a_tract_closer_than_the_model_range_is_not_ranked_and_is_counted() -> None:
    scenario = _by(community_inhalation(assessed(tracts=[tract("T", 50.0)])), "hq")
    assert scenario["receptors"] == []
    assert "1 tracts lie outside" in (scenario["receptors_note"] or "")


def test_no_tracts_says_so() -> None:
    scenario = _by(community_inhalation(assessed(tracts=[])), "hq")
    assert "no census tract" in (scenario["receptors_note"] or "")


def test_the_cap_limits_the_receptors() -> None:
    item = assessed()
    top = item["exposure"]["results"][0]["distance_m"] or 0.0
    tracts = [tract(f"T{i}", top) for i in range(15)]
    scenario = _by(community_inhalation(assessed(tracts=tracts)), "hq")
    assert len(scenario["receptors"]) == 10


def test_a_scenario_never_words_a_regulatory_finding() -> None:
    text = str(community_inhalation(assessed(toxicity=Toxicity(rfc=1e-9, iur=1.0)))).lower()
    assert "unreasonable" not in text
