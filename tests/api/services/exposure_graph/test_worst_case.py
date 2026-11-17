"""The run-wide worst-case chain: one lane per pathway, from its driver, naming no facility."""

from __future__ import annotations

from api.schemas.exposure_graph import ExposureGraph, GraphNode
from api.schemas.workspace import Chemical, Facility, ScenarioDriver
from api.services.exposure_graph.worst_case import build_worst_case_chain
from tests.api.services.exposure_graph.factories import (
    EXPOSURE,
    PEOPLE,
    TEXT,
    WORKER,
    facility,
    stack_dict,
    value,
)

CHEMICAL = Chemical(cas_number="71-43-2", name="Benzene")


def _driver(
    frs_id: str,
    quantity: str,
    pathway: str = "community_inhalation",
    stack: int | None = None,
) -> ScenarioDriver:
    return ScenarioDriver(
        pathway_key=pathway,
        quantity=quantity,
        frs_id=frs_id,
        stack_number=stack,
        value=1.0,
    )


def _plant(frs_id: str, rate: float, **over: object) -> Facility:
    base: dict[str, object] = {
        "frs_id": frs_id,
        "emission_rate_g_s": rate,
        "stacks": [stack_dict(1, 3.0), stack_dict(2, 4.0)],
        "exposure": EXPOSURE,
        "receptors": PEOPLE,
        "occupational_exposure": WORKER,
    }
    return facility(**{**base, **over})


def _chain(facilities: list[Facility], drivers: list[ScenarioDriver]) -> ExposureGraph:
    return build_worst_case_chain(facilities, drivers, TEXT, CHEMICAL)


def node(graph: ExposureGraph, node_id: str) -> GraphNode:
    return next(n for n in graph.nodes if n.id == node_id)


def _rate(graph: ExposureGraph, node_id: str) -> float | None:
    return value(node(graph, node_id), "emission_rate").value


def test_each_lane_comes_from_the_facility_driving_its_headline_quantity() -> None:
    facilities = [_plant("A", 11.0), _plant("B", 22.0)]
    worker = "worker_inhalation"
    drivers = [_driver("A", "hq", stack=2), _driver("B", "oel_ratio", worker)]
    chain = _chain(facilities, drivers)
    assert [lane.id for lane in chain.lanes] == ["community", "worker"]
    assert _rate(chain, "community:stack:2") == 11.0


def test_only_the_drivers_stack_and_the_worst_case_branch_remain() -> None:
    chain = _chain([_plant("A", 1.0)], [_driver("A", "hq", stack=2)])
    ids = {n.id for n in chain.nodes}
    assert "community:stack:1" not in ids and "community:band:18-64" not in ids
    assert {"community:stack:2", "community:band:0-4"} <= ids
    keys = {q.key for n in chain.nodes for q in n.quantities}
    assert not {k for k in keys if k.endswith(":baseline")}


def test_the_source_is_anonymous_with_the_cas_number_and_name_only() -> None:
    chain = _chain([_plant("A", 1.0)], [_driver("A", "hq", stack=1)])
    source = node(chain, "source")
    assert source.title == TEXT.worst_case.source_title.format(chemical="Benzene")
    assert {f.key: f.text for f in source.facts} == {"cas_number": "71-43-2", "chemical": "Benzene"}
    assert source.quantities == []
    assert chain.caption == TEXT.worst_case.caption


def test_the_title_falls_back_to_the_cas_number_then_to_the_configured_words() -> None:
    drivers = [_driver("A", "hq", stack=1)]
    facilities = [_plant("A", 1.0)]
    cas = build_worst_case_chain(facilities, drivers, TEXT, Chemical(cas_number="1-1-1"))
    assert "1-1-1" in node(cas, "source").title
    none = build_worst_case_chain(facilities, drivers, TEXT, Chemical())
    assert TEXT.worst_case.unknown_chemical in node(none, "source").title


def test_a_run_with_no_worker_result_has_an_unavailable_worker_lane() -> None:
    facility = _plant("A", 1.0, occupational_exposure=None)
    chain = _chain([facility], [_driver("A", "hq", stack=1)])
    lanes = {lane.id: lane for lane in chain.lanes}
    assert lanes["worker"].available is False
    assert lanes["worker"].reason == TEXT.reasons["worker"]
    assert lanes["community"].available is True
    assert not [n for n in chain.nodes if n.lane == "worker"]


def test_a_run_without_drivers_is_an_empty_graph() -> None:
    chain = _chain([_plant("A", 1.0)], [])
    assert (chain.lanes, chain.nodes, chain.edges, chain.caption) == ([], [], [], None)


def test_a_driver_of_an_unknown_facility_makes_the_lane_unavailable() -> None:
    chain = _chain([_plant("A", 1.0)], [_driver("Z", "hq", stack=1)])
    assert [lane.available for lane in chain.lanes] == [False, False]


def test_an_absent_cancer_risk_keeps_its_reason() -> None:
    chain = _chain([_plant("A", 1.0)], [_driver("A", "hq", stack=1)])
    risk = value(node(chain, "community:endpoint"), "cancer_risk")
    assert (risk.value, risk.reason) == (None, TEXT.reasons["missing"])


def test_another_facility_driving_the_cancer_risk_adds_a_note_without_a_name() -> None:
    facilities = [_plant("A", 1.0), _plant("B", 2.0)]
    drivers = [_driver("A", "hq", stack=1), _driver("B", "cancer_risk", stack=1)]
    end = node(_chain(facilities, drivers), "community:endpoint")
    note = TEXT.worst_case.other_driver_note.format(quantity=TEXT.quantities["cancer_risk"].label)
    assert note in end.warnings
    assert "B" not in note.split()


def test_the_same_facility_driving_every_quantity_adds_no_note() -> None:
    drivers = [_driver("A", "hq", stack=1), _driver("A", "cancer_risk", stack=1)]
    end = node(_chain([_plant("A", 1.0)], drivers), "community:endpoint")
    assert end.warnings == []


def test_every_edge_joins_two_nodes_of_the_chain() -> None:
    drivers = [_driver("A", "hq", stack=2), _driver("A", "oel_ratio", "worker_inhalation")]
    chain = _chain([_plant("A", 1.0)], drivers)
    ids = {n.id for n in chain.nodes}
    assert chain.edges and all(e.source in ids and e.target in ids for e in chain.edges)


def _hq_scenario(tracts: int, note: str | None) -> dict[str, object]:
    tract = {"kind": "tract", "label": "t", "residents": 10, "distance_m": 100.0}
    return {
        "pathway_key": "community_inhalation",
        "pathway": "p",
        "quantity": "hq",
        "quantity_label": "Hazard quotient",
        "value": 1.0,
        "receptors": [tract] * tracts,
        "receptors_note": note,
    }


def _note_facts(tracts: int, note: str | None) -> list[str | None]:
    plant = _plant("A", 1.0, scenarios=[_hq_scenario(tracts, note)])
    chain = _chain([plant], [_driver("A", "hq", stack=1)])
    (band,) = [n for n in chain.nodes if n.kind == "receptor" and n.lane == "community"]
    return [f.text for f in band.facts if f.key == "receptors_note"]


def test_listed_tracts_without_a_note_carry_no_empty_note() -> None:
    assert _note_facts(tracts=1, note=None) == []


def test_no_tract_carries_the_scenarios_note() -> None:
    assert _note_facts(tracts=0, note="No resident lives where the maximum falls") == [
        "No resident lives where the maximum falls",
    ]


def test_no_tract_and_no_note_says_why() -> None:
    assert _note_facts(tracts=0, note=None) == [None]
