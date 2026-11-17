"""Branch selection in the lane builders: the run-wide chain keeps one branch, the default all."""

from __future__ import annotations

from api.schemas.exposure_graph import GraphNode
from api.schemas.workspace import Facility
from api.services.exposure_graph import build_exposure_graph
from api.services.exposure_graph.community import community_lane
from api.services.exposure_graph.worker import worker_lane
from tests.api.services.exposure_graph.factories import (
    EXPOSURE,
    PEOPLE,
    TEXT,
    WORKER,
    facility,
    stack_dict,
    value,
)


def _community(**over: object) -> Facility:
    base: dict[str, object] = {
        "stacks": [stack_dict(1, 3.0), stack_dict(2, 4.0), stack_dict(3, 2.0)],
        "exposure": EXPOSURE,
        "receptors": PEOPLE,
    }
    return facility(**{**base, **over})


def _ids(nodes: tuple[GraphNode, ...], prefix: str) -> list[str]:
    return [n.id for n in nodes if n.id.startswith(prefix)]


def test_the_default_keeps_every_stack_and_every_band() -> None:
    parts = community_lane(_community(), TEXT)
    assert _ids(parts.nodes, "community:stack:") == [f"community:stack:{n}" for n in (1, 2, 3)]
    assert _ids(parts.nodes, "community:band:") == ["community:band:0-4", "community:band:18-64"]


def test_the_default_per_facility_graph_has_no_release_quantities_on_the_stacks() -> None:
    graph = build_exposure_graph(_community(), TEXT)
    stack = next(n for n in graph.nodes if n.id == "community:stack:1")
    assert "total_release" not in {q.key for q in stack.quantities}


def test_one_stack_of_three_is_kept_with_the_release_quantities() -> None:
    parts = community_lane(_community(), TEXT, stack_number=2)
    assert _ids(parts.nodes, "community:stack:") == ["community:stack:2"]
    stack = next(n for n in parts.nodes if n.id == "community:stack:2")
    assert value(stack, "total_release").unit == "Pounds"
    assert value(stack, "emission_rate").value == 1.0
    assert {e.source for e in parts.edges if e.target == "community:air"} == {"community:stack:2"}


def test_an_unknown_stack_falls_back_to_the_generic_release_node() -> None:
    parts = community_lane(_community(), TEXT, stack_number=9)
    assert _ids(parts.nodes, "community:stack:") == []
    assert "community:release" in _ids(parts.nodes, "community:release")


def test_the_highest_dose_band_is_chosen_with_its_share_residents_and_radius() -> None:
    parts = community_lane(_community(), TEXT, single_band=True)
    (band,) = [n for n in parts.nodes if n.kind == "receptor"]
    assert band.id == "community:band:0-4"
    assert (value(band, "band_dose").value, value(band, "band_share").value) == (0.3, 10.0)
    assert (value(band, "residents").value, value(band, "radius").value) == (1000.0, 2.0)
    assert [e.target for e in parts.edges if e.source == "community:inhale"] == [band.id]


def test_a_tie_goes_to_the_first_band_in_reported_order() -> None:
    tied = {**EXPOSURE, "dose": {"by_band": {"0-4": 0.2, "18-64": 0.2}}}
    parts = community_lane(_community(exposure=tied), TEXT, single_band=True)
    assert [n.id for n in parts.nodes if n.kind == "receptor"] == ["community:band:0-4"]


def test_a_later_band_with_the_higher_dose_wins() -> None:
    later = {**EXPOSURE, "dose": {"by_band": {"0-4": 0.1, "18-64": 0.5}}}
    parts = community_lane(_community(exposure=later), TEXT, single_band=True)
    assert [n.id for n in parts.nodes if n.kind == "receptor"] == ["community:band:18-64"]


def test_without_doses_the_single_residents_node_is_used() -> None:
    no_dose = {k: v for k, v in EXPOSURE.items() if k != "dose"}
    parts = community_lane(_community(exposure=no_dose), TEXT, single_band=True)
    assert [n.id for n in parts.nodes if n.kind == "receptor"] == ["community:residents"]


def test_the_worker_default_carries_both_cases() -> None:
    parts = worker_lane(facility(occupational_exposure=WORKER), TEXT)
    keys = {q.key for n in parts.nodes for q in n.quantities}
    assert {"oel_ratio:baseline", "oel_ratio:worst_case"} <= keys


def test_the_worst_case_only_drops_the_baseline_everywhere() -> None:
    parts = worker_lane(facility(occupational_exposure=WORKER), TEXT, variants=("worst_case",))
    keys = {q.key for n in parts.nodes for q in n.quantities}
    assert not {k for k in keys if k.endswith(":baseline")}
    assert "oel_ratio:worst_case" in keys
    facts = " ".join(f.text or "" for n in parts.nodes for f in n.facts)
    assert TEXT.variants["baseline"] not in facts
    assert all(e.quantity is None or not e.quantity.key.endswith(":baseline") for e in parts.edges)
