"""Fugitive-only facilities reach the workspace with a worker result and no community value."""

from __future__ import annotations

from langchain_core.messages import BaseMessage

from api.schemas.workspace import WorkspaceState
from api.services.state_serializer import build_workspace
from tests.api.services.projectors.factories import (
    RULES,
    exchange,
    exposure,
    inventory,
    record,
    stack,
    stack_result,
    worker_case,
    worker_result,
)
from tests.api.services.projectors.test_assessment import (
    SCENARIO,
    TYPICAL,
    assessed_item,
    assessed_messages,
)

REASON = "the facility reports no stack release"
PROFILE: dict[str, object] = {"naics_code": "325", "life_cycle_stage": ["Processing"]}


def _only_record(frs_id: str = "W1") -> dict[str, object]:
    base = record(frs_id, lat=11.0, lon=-21.0)
    for key in ("environmental_medium", "total_release", "unit", "emission_rate"):
        del base[key]
    return {**base, "fugitive_release_kg_per_year": 500.0, "fugitive_reporting_year": 2020}


def _worker_only(
    frs_id: str = "W1",
    worker: dict[str, object] | None = None,
    **over: object,
) -> dict[str, object]:
    return {
        "facility": _only_record(frs_id),
        "operational_profile": PROFILE,
        "occupational_exposure": worker if worker is not None else worker_result(),
        "community_reason": REASON,
        **over,
    }


def _batch(
    assessed: list[dict[str, object]],
    only: list[object],
    left_out: object = 0,
) -> list[BaseMessage]:
    artifact = {
        "assessed": assessed,
        "screened_out": [],
        "not_assessed": [],
        "worker_only": only,
        "worker_only_left_out": left_out,
    }
    return exchange(
        "assess_facilities",
        {"cas_number": "1-1-1"},
        {"assessed": 1},
        artifact=artifact,
    )


def _build(*parts: list[BaseMessage]) -> WorkspaceState:
    return build_workspace([m for part in parts for m in part], RULES)


def _high(ratio: float) -> dict[str, object]:
    case = worker_case(oel_ratio=ratio, risk_tier="high", cancer_risk=None)
    return worker_result(baseline=case, worst_case=case)


def test_a_worker_only_facility_has_its_worker_result_and_no_community_value() -> None:
    state = _build(_batch([], [_worker_only()]))
    facility = state.facilities[0]
    assert facility.worker_only and facility.community_reason == REASON
    assert facility.occupational_exposure is not None and facility.operational_profile is not None
    assert (facility.latitude, facility.longitude) == (11.0, -21.0)
    assert facility.fugitive_release_kg_per_year == 500.0 and facility.naics_subsector == "325"
    community = (facility.medium, facility.total_release, facility.release_unit)
    assert community == (None, None, None) and facility.emission_rate_g_s is None
    assert facility.exposure is None and facility.status is None and facility.screening is None
    assert facility.stacks == [] and facility.receptors is None and facility.scenarios == []


def test_a_worker_only_facility_changes_no_community_figure() -> None:
    item = assessed_item("F1", 1.0, [stack(10.0)])
    alone = _build(_batch([item], []))
    both = _build(_batch([item], [_worker_only(worker=_high(50.0))]))
    assert both.risk == alone.risk and both.selected_frs_id == alone.selected_frs_id == "F1"
    assert both.scenario_drivers == alone.scenario_drivers
    assert [f.frs_id for f in both.facilities if not f.worker_only] == ["F1"]
    assert both.facilities[0] == alone.facilities[0]


def test_a_worker_only_facility_can_hold_the_highest_worker_figure() -> None:
    item = assessed_item("F1", 1.0, [stack(10.0)], occupational_exposure=_high(2.0))
    state = _build(_batch([item], [_worker_only(worker=_high(9.0))]))
    ratio = state.worker_risk.worst_case.oel_ratio
    assert ratio is not None and ratio.frs_id == "W1" and ratio.value == 9.0
    assert ratio.evidence == "activity_model"


def test_a_workspace_of_worker_only_facilities_has_a_worker_summary_and_no_community_one() -> None:
    state = _build(_batch([], [_worker_only()]))
    assert state.worker_risk.reason is None and state.worker_risk.baseline.oel_ratio is not None
    assert state.risk.hq_worst is None and state.risk.reason is not None
    assert state.selected_frs_id is None


def test_its_graph_has_the_community_lane_unavailable_and_the_worker_lane_built() -> None:
    facility = _build(_batch([], [_worker_only()])).facilities[0]
    graph = facility.exposure_graph
    assert graph is not None
    lanes = {lane.id: lane for lane in graph.lanes}
    assert not lanes["community"].available and lanes["community"].reason == REASON
    assert lanes["worker"].available
    ids = {n.id for n in graph.nodes}
    assert not any(i.startswith("community:") for i in ids) and "worker:endpoint" in ids
    source = next(n for n in graph.nodes if n.id == "source")
    assert source.headline == "fugitive_release"
    assert [q.value for q in source.quantities if q.key == "fugitive_release"] == [500.0]


def test_the_inventory_lists_worker_only_facilities_without_a_worker_result() -> None:
    listed = {
        "total_found": 2,
        "matching": 2,
        "shown": 1,
        "facilities": [record("F1")],
        "note": None,
        "worker_only": [_only_record("W1")],
        "worker_only_left_out": 3,
    }
    state = _build(exchange("query_emissions_inventory", {"cas_number": "1-1-1"}, listed))
    by_id = {f.frs_id: f for f in state.facilities}
    assert by_id["W1"].worker_only and by_id["W1"].occupational_exposure is None
    assert by_id["W1"].community_reason == REASON and not by_id["F1"].worker_only
    assert any("3 more worker-only facilities" in w for w in state.warnings)


def test_the_left_out_count_becomes_a_note_and_none_means_no_note() -> None:
    noted = _build(_batch([], [_worker_only()], left_out=4))
    assert any("4 more worker-only" in w for w in noted.warnings)
    assert not any("worker-only" in w for w in _build(_batch([], [_worker_only()])).warnings)


def test_a_malformed_left_out_count_is_ignored() -> None:
    for bad in (True, -1, "3", 2.5):
        state = _build(_batch([], [_worker_only()], left_out=bad))
        assert not any("more worker-only" in w for w in state.warnings)


def test_malformed_worker_only_entries_are_dropped_with_a_warning() -> None:
    bad_coordinates = _worker_only("W2", facility={**_only_record("W2"), "latitude": 91.0})
    no_reason = {k: v for k, v in _worker_only("W3").items() if k != "community_reason"}
    state = _build(_batch([], [_worker_only("W1"), "junk", bad_coordinates, no_reason]))
    assert [f.frs_id for f in state.facilities] == ["W1"]
    assert sum("was left out: its result was not valid" in w for w in state.warnings) == 3


def test_an_invalid_worker_result_leaves_out_only_the_worker_result() -> None:
    nan = {**worker_result(), "molecular_weight": float("nan")}
    state = _build(_batch([], [_worker_only(worker=nan)]))
    facility = state.facilities[0]
    assert facility.worker_only and facility.occupational_exposure is None
    assert any("worker exposure of facility W1" in w for w in state.warnings)


def test_a_stack_facility_with_the_same_frs_id_is_never_replaced() -> None:
    item = assessed_item("F1", 1.0, [stack(10.0)])
    state = _build(_batch([item], [_worker_only("F1")]))
    assert len(state.facilities) == 1 and not state.facilities[0].worker_only
    assert state.facilities[0].exposure is not None


def test_an_earlier_artifact_without_worker_only_keys_still_projects() -> None:
    state = _build(assessed_messages(assessed_item("F1", 1.0, [stack(10.0)])))
    assert [f.frs_id for f in state.facilities] == ["F1"]
    assert not any("worker-only" in w for w in state.warnings)


def test_a_later_stack_result_for_the_same_facility_keeps_the_stack_facility() -> None:
    later = exposure(
        1.0,
        [stack_result(1, stack(10.0), SCENARIO, TYPICAL)],
        {"low": 1.0, "high": 2.0, "low_stack": 1, "high_stack": 1},
    )
    state = _build(inventory(record("W1")), _batch([], [_worker_only("W1")]), later)
    assert [f.worker_only for f in state.facilities] == [False]
