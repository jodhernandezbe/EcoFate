"""The worst-case scenarios of the batch assessment reach the workspace as the tool gave them."""

from __future__ import annotations

import math

from langchain_core.messages import BaseMessage

from api.schemas.workspace import WorkspaceState
from api.services.state_serializer import build_workspace
from tests.api.services.projectors.factories import (
    RULES,
    exchange,
    record,
    stack,
    stack_result,
)

SCENARIO: dict[str, object] = {"max_concentration": 4.0, "distance_m": 500.0, "hq": 2.0}
WEATHER: dict[str, object] = {
    "wind_speed": 3.0,
    "wind_direction": 270.0,
    "stability_class": "D",
    "ambient_temperature": 290.0,
    "source": "synthetic 2020",
    "warnings": [],
}
PEOPLE: dict[str, object] = {
    "total_population": 1000,
    "age_distribution": {"18-64": 100.0},
    "source": "synthetic ACS",
    "warnings": [],
}


def _factor(key: str, value: object, **over: object) -> dict[str, object]:
    return {
        "key": key,
        "group": "source",
        "label": key,
        "value": value,
        "unit": "m",
        "source": None,
        "reason": None,
        **over,
    }


def _scenario(value: float = 2.0, quantity: str = "hq", **over: object) -> dict[str, object]:
    return {
        "pathway_key": "community_inhalation",
        "pathway": "Outdoor Air → Inhalation → General Population",
        "quantity": quantity,
        "quantity_label": "Hazard quotient",
        "value": value,
        "tier": "at or above threshold",
        "benchmark": 0.1,
        "factors": [_factor("stack_number", 2), _factor("stack_height", 30.0)],
        "receptors": [
            {
                "kind": "tract",
                "label": "99001000100",
                "residents": 500,
                "age_distribution": {"0-4": 10.0, "65+": 90.0},
                "distance_m": 480.0,
                "bearing_deg": 90.0,
                "latitude": 41.5,
                "longitude": -71.19,
                "concentration": 0.9,
                "fraction_of_maximum": 1.0,
                "note": None,
            },
        ],
        "receptors_note": None,
        "notes": [],
        **over,
    }


def _item(frs_id: str, scenarios: list[object]) -> dict[str, object]:
    entry = {"low": 0.5, "high": 2.0, "low_stack": 1, "high_stack": 1}
    stacks = [stack(10.0)]
    return {
        "record": record(frs_id, rate=1.0),
        "stacks": stacks,
        "stack_tier": "NEI",
        "scc_matches": [],
        "industry": None,
        "meteorology": WEATHER,
        "population": PEOPLE,
        "radius_km": None,
        "exposure": {
            "results": [stack_result(1, stacks[0], SCENARIO, SCENARIO)],
            "range": {
                "max_concentration": None,
                "hq": entry,
                "cancer_risk": None,
                "representative": {"max_concentration": None, "hq": entry, "cancer_risk": None},
            },
            "stacks_given": 1,
            "stacks_evaluated": 1,
            "warnings": [],
        },
        "notes": [],
        "scenarios": scenarios,
    }


def _build(*items: dict[str, object]) -> WorkspaceState:
    messages: list[BaseMessage] = exchange(
        "assess_facilities",
        {"cas_number": "1-1-1"},
        {"assessed": len(items)},
        artifact=list(items),
    )
    return build_workspace(messages, RULES)


def test_the_scenarios_reach_their_own_facility_as_the_tool_gave_them() -> None:
    state = _build(_item("F1", [_scenario(2.0)]), _item("F2", []))
    by_id = {f.frs_id: f for f in state.facilities}
    (scenario,) = by_id["F1"].scenarios
    assert by_id["F2"].scenarios == []
    assert scenario.value == 2.0 and scenario.tier == "at or above threshold"
    assert [f.key for f in scenario.factors] == ["stack_number", "stack_height"]
    assert scenario.factors[1].value == 30.0 and scenario.factors[1].unit == "m"
    receptor = scenario.receptors[0]
    assert (receptor.label, receptor.residents, receptor.distance_m) == ("99001000100", 500, 480.0)
    assert (receptor.latitude, receptor.longitude) == (41.5, -71.19)


def test_an_absent_factor_keeps_its_reason() -> None:
    absent = _factor("stack_diameter", None, unit="", reason="the stack has no value for this")
    state = _build(_item("F1", [_scenario(factors=[absent])]))
    (factor,) = state.facilities[0].scenarios[0].factors
    assert factor.value is None and factor.reason == "the stack has no value for this"


def test_a_text_factor_is_kept_as_text() -> None:
    text = _factor("stability_class", "D", unit="", group="conditions")
    state = _build(_item("F1", [_scenario(factors=[text])]))
    assert state.facilities[0].scenarios[0].factors[0].value == "D"


def test_an_invalid_scenario_leaves_out_only_itself_with_a_warning() -> None:
    bad = _scenario(math.nan, quantity="cancer_risk")
    state = _build(_item("F1", [_scenario(1.0), bad]))
    assert [s.quantity for s in state.facilities[0].scenarios] == ["hq"]
    assert any("worst-case scenario of facility F1" in w for w in state.warnings)


def test_a_scenario_with_an_invalid_receptor_is_left_out_whole() -> None:
    broken = _scenario(receptors=[{"kind": "tract", "label": "T", "residents": "many"}])
    state = _build(_item("F1", [broken, _scenario(3.0, "cancer_risk")]))
    assert [s.quantity for s in state.facilities[0].scenarios] == ["cancer_risk"]
    assert state.facilities[0].exposure is not None  # the rest of the facility is kept


def test_an_older_tool_result_without_scenarios_still_projects() -> None:
    item = _item("F1", [])
    del item["scenarios"]
    state = _build(item)
    assert state.facilities[0].scenarios == [] and state.scenario_drivers == []


def test_the_driver_of_each_quantity_is_the_facility_with_the_highest_value() -> None:
    first = _item("F1", [_scenario(2.0), _scenario(5.0, "cancer_risk")])
    second = _item("F2", [_scenario(3.0), _scenario(1.0, "cancer_risk")])
    state = _build(first, second)
    by_quantity = {d.quantity: d for d in state.scenario_drivers}
    assert by_quantity["hq"].frs_id == "F2" and by_quantity["hq"].value == 3.0
    assert by_quantity["cancer_risk"].frs_id == "F1"
    assert by_quantity["hq"].stack_number == 2


def test_a_tie_goes_to_the_first_facility() -> None:
    state = _build(_item("F1", [_scenario(2.0)]), _item("F2", [_scenario(2.0)]))
    assert [d.frs_id for d in state.scenario_drivers] == ["F1"]


def test_no_scenario_means_no_driver() -> None:
    assert _build(_item("F1", [])).scenario_drivers == []
