"""Tests for the registry of pathways and the choice of the driving facility."""

from __future__ import annotations

import pytest

from tests.tools.assessment.helpers.scenarios.items import HIGH, LOW, assessed
from tools.assessment.helpers import scenarios
from tools.assessment.helpers.scenarios import drivers_of, scenarios_of, with_scenarios
from tools.schemas import FacilityAssessment, WorstCaseScenario


def test_every_registered_pathway_contributes() -> None:
    keys = {s["pathway_key"] for s in scenarios_of(assessed())}
    assert keys == {"community_inhalation", "worker_inhalation"}


def test_with_scenarios_attaches_them_without_changing_the_rest() -> None:
    item = assessed()
    attached = with_scenarios(item)
    assert attached.get("scenarios") == scenarios_of(item)
    assert {k: v for k, v in attached.items() if k != "scenarios"} == item


def test_a_new_pathway_reaches_the_output_in_the_same_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def dermal(item: FacilityAssessment) -> list[WorstCaseScenario]:
        return [
            WorstCaseScenario(
                pathway_key="dermal",
                pathway="Soil → Dermal → Child",
                quantity="hq",
                quantity_label="Hazard quotient",
                value=7.0,
                tier=None,
                benchmark=None,
                factors=[],
                receptors=[],
                receptors_note=None,
                notes=[],
            ),
        ]

    monkeypatch.setitem(scenarios.PATHWAYS, "dermal", dermal)
    item = with_scenarios(assessed())
    assert "dermal" in {s["pathway_key"] for s in item.get("scenarios", [])}
    drivers = {(d["pathway_key"], d["quantity"]) for d in drivers_of([item])}
    assert ("dermal", "hq") in drivers


def test_the_driver_is_the_facility_with_the_highest_value_per_pathway_and_quantity() -> None:
    weak = with_scenarios(assessed("F1", stacks=[HIGH], kg=10.0))
    strong = with_scenarios(assessed("F2", stacks=[LOW], kg=10_000.0))
    by_key = {(d["pathway_key"], d["quantity"]): d for d in drivers_of([weak, strong])}
    assert by_key[("community_inhalation", "hq")]["frs_id"] == "F2"
    assert by_key[("worker_inhalation", "oel_ratio")]["frs_id"] == "F2"
    assert by_key[("community_inhalation", "hq")]["stack_number"] == 1
    assert by_key[("worker_inhalation", "oel_ratio")]["stack_number"] is None


def test_drivers_can_differ_between_quantities() -> None:
    community = with_scenarios(assessed("C", stacks=[LOW], kg=1.0))
    workplace = with_scenarios(assessed("W", stacks=[HIGH], kg=10_000.0))
    by_key = {
        (d["pathway_key"], d["quantity"]): d["frs_id"] for d in drivers_of([community, workplace])
    }
    assert by_key[("community_inhalation", "hq")] == "C"
    assert by_key[("worker_inhalation", "oel_ratio")] == "W"


def test_a_tie_goes_to_the_first_facility() -> None:
    first, second = with_scenarios(assessed("A")), with_scenarios(assessed("B"))
    assert {d["frs_id"] for d in drivers_of([first, second])} == {"A"}


def test_a_facility_without_scenarios_drives_nothing() -> None:
    assert drivers_of([assessed()]) == []


def test_the_driver_names_the_facility() -> None:
    (driver, *_) = drivers_of([with_scenarios(assessed("F1"))])
    assert driver["facility_name"] == assessed("F1")["record"]["facility_name"]
