"""The batch assessment fills the workspace like the single tools do, keyed by FRS ID."""

from __future__ import annotations

from langchain_core.messages import BaseMessage

from api.schemas.workspace import WorkspaceState
from api.services.state_serializer import build_workspace
from tests.api.services.projectors.factories import (
    RULES,
    exchange,
    exposure,
    inventory,
    monitoring_result,
    record,
    stack,
    stack_result,
    worker_case,
    worker_result,
)

SCENARIO: dict[str, object] = {
    "max_concentration": 4.0,
    "distance_m": 500.0,
    "hq": 2.0,
    "cancer_risk": None,
}
TYPICAL: dict[str, object] = {
    "max_concentration": 1.0,
    "distance_m": 900.0,
    "hq": 0.5,
    "cancer_risk": None,
}
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


def _exposure(stacks: list[dict[str, object]], hq_high: float) -> dict[str, object]:
    entry = {"low": 0.5, "high": hq_high, "low_stack": 1, "high_stack": len(stacks)}
    return {
        "results": [stack_result(i + 1, s, SCENARIO, TYPICAL) for i, s in enumerate(stacks)],
        "range": {
            "max_concentration": None,
            "hq": entry,
            "cancer_risk": None,
            "representative": {"max_concentration": None, "hq": entry, "cancer_risk": None},
        },
        "stacks_given": len(stacks),
        "stacks_evaluated": len(stacks),
        "warnings": [],
    }


def assessed_item(
    frs_id: str,
    rate: float,
    stacks: list[dict[str, object]],
    **over: object,
) -> dict[str, object]:
    return {
        "record": record(frs_id, rate=rate),
        "stacks": stacks,
        "stack_tier": stacks[0]["source"],
        "scc_matches": [],
        "industry": None,
        "meteorology": WEATHER,
        "population": PEOPLE,
        "radius_km": None,
        "exposure": _exposure(stacks, 2.0),
        "notes": [],
        **over,
    }


def assessed_messages(*items: dict[str, object]) -> list[BaseMessage]:
    return exchange(
        "assess_facilities",
        {"cas_number": "1-1-1"},
        {"assessed": len(items)},
        artifact=list(items),
    )


def _build(*parts: list[BaseMessage]) -> WorkspaceState:
    return build_workspace([m for part in parts for m in part], RULES)


def test_every_assessed_facility_gets_its_stacks_weather_residents_and_risk() -> None:
    state = _build(assessed_messages(assessed_item("F1", 1.0, [stack(10.0), stack(20.0)])))
    facility = state.facilities[0]
    assert facility.frs_id == "F1" and [s.height_m for s in facility.stacks] == [10.0, 20.0]
    assert facility.status == "high"
    assert facility.meteorology is not None and facility.receptors is not None
    assert facility.receptors.radius_km == RULES.default_radius_km
    assert facility.exposure is not None and facility.exposure.hq_worst is not None
    assert state.unattributed == []


def test_facilities_with_the_same_emission_rate_keep_their_own_results() -> None:
    a = assessed_item("A", 1.0, [stack(10.0)])
    b = assessed_item(
        "B",
        1.0,
        [stack(30.0)],
        record={**record("B", lat=11.0, lon=-21.0, rate=1.0)},
    )
    state = _build(assessed_messages(a, b))
    by_id = {f.frs_id: f for f in state.facilities}
    assert by_id["A"].stacks[0].height_m == 10.0 and by_id["B"].stacks[0].height_m == 30.0
    assert all(f.exposure is not None for f in state.facilities) and state.unattributed == []


def test_a_pstk_stack_shows_its_tier_and_scc_description() -> None:
    match = {
        "scc": "1",
        "level_one": "a",
        "level_two": "b",
        "level_three": "c",
        "level_four": "Process 1",
        "sector": "s",
        "score": 0.7,
    }
    item = assessed_item("F1", 1.0, [stack(15.0, "PSTK", "1")], scc_matches=[match])
    shown = _build(assessed_messages(item)).facilities[0].stacks[0]
    assert (shown.tier, shown.scc, shown.scc_description) == (2, "1", "Process 1")


def test_a_later_single_tool_result_replaces_the_batch_one() -> None:
    later = exposure(
        1.0,
        [stack_result(1, stack(10.0), {**SCENARIO, "hq": 9.0}, TYPICAL)],
        {"low": 9.0, "high": 9.0, "low_stack": 1, "high_stack": 1},
    )
    state = _build(assessed_messages(assessed_item("F1", 1.0, [stack(10.0)])), later)
    assert state.facilities[0].exposure is not None
    assert state.facilities[0].exposure.hq_worst is not None
    assert state.facilities[0].exposure.hq_worst.high == 9.0


def test_an_invalid_item_is_left_out_with_a_warning_and_no_artifact_is_skipped() -> None:
    state = _build(inventory(record("F0")), assessed_messages({"record": "junk"}))
    assert any("batch assessment was left out" in w for w in state.warnings)
    bare = _build(exchange("assess_facilities", {"cas_number": "1-1-1"}, {"assessed": 0}))
    assert any("carried no facility details" in w for w in bare.warnings)


def _tiered(
    assessed: list[dict[str, object]],
    screened_out: list[dict[str, object]],
    not_assessed: list[dict[str, object]] | None = None,
) -> list[BaseMessage]:
    artifact = {
        "assessed": assessed,
        "screened_out": screened_out,
        "not_assessed": not_assessed or [],
    }
    return exchange(
        "assess_facilities",
        {"cas_number": "1-1-1"},
        {"assessed": 1},
        artifact=artifact,
    )


def _out(frs_id: str, stage: str, hq: float, **over: object) -> dict[str, object]:
    return {
        "record": record(frs_id, lat=12.0, lon=-22.0, rate=0.01),
        "stage": stage,
        "hq": hq,
        "cancer_risk": None,
        "stacks": [],
        "stack_tier": "AirToxScreen global default",
        "reason": f"screened out ({frs_id})",
        **over,
    }


def test_a_fully_assessed_facility_says_so_with_its_bound() -> None:
    item = assessed_item(
        "F1",
        1.0,
        [stack(10.0)],
        level="full",
        bound={"hq": 5.0, "cancer_risk": None},
    )
    facility = _build(_tiered([item], [])).facilities[0]
    assert facility.screening is not None and facility.screening.outcome == "full"
    assert facility.screening.bound_hq == 5.0 and facility.screening.reason is None


def test_a_worst_case_only_facility_has_its_risk_but_no_weather_or_residents() -> None:
    item = assessed_item(
        "F1",
        1.0,
        [stack(10.0)],
        level="worst case only",
        meteorology=None,
        population=None,
    )
    facility = _build(_tiered([item], [])).facilities[0]
    assert facility.screening is not None and facility.screening.outcome == "worst_case_only"
    assert facility.meteorology is None and facility.receptors is None and facility.buffer is None
    assert facility.exposure is not None and facility.status == "high"


def test_screened_out_facilities_are_placed_with_their_value_reason_and_status() -> None:
    own = _out("OWN", "own stacks", 0.02, stacks=[stack(80.0)], stack_tier="NEI")
    state = _build(_tiered([], [_out("BOUND", "bound", 0.05), own]))
    by_id = {f.frs_id: f for f in state.facilities}
    bound = by_id["BOUND"].screening
    assert bound is not None and bound.outcome == "screened_out_at_bound"
    assert (bound.bound_hq, bound.value_hq, bound.reason) == (0.05, 0.05, "screened out (BOUND)")
    assert by_id["BOUND"].stacks == [] and by_id["BOUND"].status == "low"
    with_own = by_id["OWN"].screening
    assert with_own is not None and with_own.outcome == "screened_out_with_own_stacks"
    assert with_own.bound_hq is None and with_own.value_hq == 0.02
    assert [s.height_m for s in by_id["OWN"].stacks] == [80.0]
    assert by_id["OWN"].exposure is None


def test_an_invalid_screened_out_item_is_left_out_and_a_bad_shape_is_skipped() -> None:
    state = _build(_tiered([], [{"record": "junk"}]))
    assert any("batch assessment was left out" in w for w in state.warnings)
    bad = exchange("assess_facilities", {"cas_number": "1-1-1"}, {}, artifact={"assessed": "nope"})
    assert any("carried no facility details" in w for w in _build(bad).warnings)


def test_a_facility_not_assessed_carries_its_reason_and_no_status() -> None:
    left: list[dict[str, object]] = [
        {"frs_id": "F0", "reason": "more than 5 facilities reach a threshold"},
    ]
    state = _build(inventory(record("F0")), _tiered([], [], left))
    screening = state.facilities[0].screening
    assert screening is not None and screening.outcome == "not_assessed"
    assert screening.reason == "more than 5 facilities reach a threshold"
    assert state.facilities[0].status is None and state.facilities[0].exposure is None


def test_a_not_assessed_reason_never_replaces_a_real_result() -> None:
    left: list[dict[str, object]] = [{"frs_id": "F1", "reason": "should not show"}]
    item = assessed_item("F1", 1.0, [stack(10.0)], level="full")
    state = _build(_tiered([item], [], left))
    screening = state.facilities[0].screening
    assert screening is not None and screening.outcome == "full" and screening.reason is None


def test_a_not_assessed_facility_unknown_to_the_workspace_is_ignored() -> None:
    state = _build(_tiered([], [], [{"frs_id": "GHOST", "reason": "x"}]))
    assert state.facilities == [] and state.warnings == []


def test_an_invalid_not_assessed_item_is_left_out_with_a_warning() -> None:
    state = _build(_tiered([], [], [{"frs_id": 5}]))
    assert any("batch assessment was left out" in w for w in state.warnings)


def _dosed(add_by_band: dict[str, float]) -> dict[str, object]:
    top = max(add_by_band, key=lambda band: add_by_band[band]) if add_by_band else None
    return {
        **SCENARIO,
        "add": add_by_band[top] if top else None,
        "add_band": top,
        "add_by_band": add_by_band,
    }


def test_facility_dose_is_the_highest_per_band_over_its_stacks() -> None:
    stacks = [stack(10.0), stack(20.0)]
    results = [
        stack_result(1, stacks[0], _dosed({"0-4": 2.0, "18-64": 1.0}), TYPICAL),
        stack_result(2, stacks[1], _dosed({"0-4": 1.0, "18-64": 3.0}), TYPICAL),
    ]
    exposure = {**_exposure(stacks, 2.0), "results": results}
    facility = _build(
        assessed_messages(assessed_item("F1", 1.0, stacks, exposure=exposure)),
    ).facilities[0]
    assert facility.stacks[0].dose is not None and facility.stacks[0].dose.highest_band == "0-4"
    assert facility.exposure is not None and facility.exposure.dose is not None
    assert facility.exposure.dose.by_band == {"0-4": 2.0, "18-64": 3.0}
    assert facility.exposure.dose.highest_band == "18-64"
    assert facility.exposure.dose.highest_mg_kg_day == 3.0


def test_no_reported_dose_stays_absent() -> None:
    state = _build(assessed_messages(assessed_item("F1", 1.0, [stack(10.0)])))
    facility = state.facilities[0]
    assert facility.exposure is not None and facility.exposure.dose is None
    assert facility.stacks[0].dose is None


TIER = worker_case()
WORKER = worker_result()
PROFILE: dict[str, object] = {
    "naics_code": "325199",
    "life_cycle_stage": ["Processing"],
    "cou_category": ["Processing as a reactant"],
    "cdr_sector": {
        "code": "IS21",
        "name": "All Other Basic Organic Chemical Manufacturing",
        "matched_naics_prefix": "32519",
        "naics_edition": "2007",
    },
    "days_per_week": 5,
    "operating_days_per_year": 250.0,
    "hours_per_day": 16.0,
    "annual_operating_hours": 4000.0,
    "schedule_source": "Census QPC test",
    "warnings": [],
}


def _worker_item(**over: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "occupational_exposure": WORKER,
        "operational_profile": PROFILE,
        "record": record("F1", fugitive_release_kg_per_year=1000.0, fugitive_reporting_year=2020),
        **over,
    }
    return assessed_item("F1", 1.0, [stack(10.0)], **fields)


def test_the_worker_result_and_profile_reach_the_facility_as_the_tool_gave_them() -> None:
    facility = _build(assessed_messages(_worker_item())).facilities[0]
    worker, profile = facility.occupational_exposure, facility.operational_profile
    assert worker is not None and profile is not None
    assert worker.baseline.twa_mg_m3 == 2.0 and worker.baseline.oel_ratio == 0.4
    assert worker.worst_case.risk_tier == "high" and worker.oel_source is not None
    assert profile.cdr_sector is not None and profile.cdr_sector.code == "IS21"
    assert profile.annual_operating_hours == 4000.0 and profile.life_cycle_stage == ["Processing"]
    assert facility.fugitive_release_kg_per_year == 1000.0
    assert facility.exposure is not None  # the community result is unaffected


def test_the_evidence_properties_and_driving_activity_reach_the_facility() -> None:
    worker = _build(assessed_messages(_worker_item())).facilities[0].occupational_exposure
    assert worker is not None
    assert (worker.evidence, worker.volatility) == ("activity_model", "within")
    assert (worker.molecular_weight, worker.molecular_weight_source) == (100.0, "synthetic source")
    assert (worker.vapor_pressure_mmhg, worker.vapor_pressure_source) == (
        10.0,
        "synthetic pressure",
    )
    assert worker.driving_activity is not None and worker.driving_activity.label == "Drum loading"
    assert worker.driving_activity.estimator == "two_zone" and worker.driving_activity.hours == 2.0


def test_every_activity_keeps_its_typical_and_worst_case_values() -> None:
    worker = _build(assessed_messages(_worker_item())).facilities[0].occupational_exposure
    assert worker is not None and [a.key for a in worker.activities] == ["drum_loading"]
    activity = worker.activities[0]
    assert (activity.model, activity.setting, activity.hours) == ("ap42_loading", "indoor", 2.0)
    assert activity.typical.generation_g_per_s == 0.25 and activity.typical.capped is False
    assert activity.worst_case.room_m3 == 50.0 and activity.worst_case.air_exchange_per_h == 4.0
    assert activity.worst_case.concentration_mg_m3 == 4.0 and activity.worst_case.twa_mg_m3 == 2.0
    assert activity.warnings == ["a synthetic activity warning"]


def test_both_cases_keep_every_field_and_the_routes_and_fugitive_context() -> None:
    worker = _build(assessed_messages(_worker_item())).facilities[0].occupational_exposure
    assert worker is not None
    assert (worker.baseline.estimator, worker.baseline.airflow_m3_per_s) == ("mass_balance", 1.0)
    assert (worker.baseline.mixing_factor, worker.baseline.generation_g_per_s) == (0.5, 0.25)
    assert (worker.worst_case.estimator, worker.worst_case.room_m3) == ("two_zone", 50.0)
    assert worker.worst_case.air_exchange_per_h == 4.0 and worker.worst_case.capped is False
    route = worker.routes[0]
    assert route.stage == "Processing" and route.generic_operation == ["drum_loading"]
    assert route.scenarios[0].category == "published ESD" and route.scenarios[0].pages == "pp. 1-2"
    assert worker.fugitive_release_kg_per_year == 1000.0 and worker.fugitive_statement
    assert worker.monitoring is None and worker.monitoring_reason == "no samples for the industry"


def test_a_monitoring_result_keeps_its_summary_and_has_no_activity() -> None:
    item = _worker_item(occupational_exposure=monitoring_result())
    worker = _build(assessed_messages(item)).facilities[0].occupational_exposure
    assert worker is not None and worker.evidence == "monitoring"
    assert worker.driving_activity is None and worker.activities == []
    assert worker.activity_reason == "measured samples were used instead"
    summary = worker.monitoring
    assert summary is not None and (summary.n_values, summary.n_nondetect) == (40, 5)
    assert (summary.median_mg_m3, summary.p95_mg_m3) == (1.5, 6.0)
    assert (summary.first_year, summary.last_year) == (2005, 2020)
    assert summary.source == "OSHA CEHD (synthetic)" and summary.statements
    assert worker.worst_case.estimator == "monitoring" and worker.worst_case.twa_mg_m3 == 6.0


def test_a_result_without_activities_still_projects_with_its_reason() -> None:
    bare = worker_result(
        evidence=None,
        driving_activity=None,
        activities=[],
        routes=[],
        activity_reason="no activity applies",
        baseline=worker_case(estimator=None, twa_mg_m3=None, risk_tier=None),
        worst_case=worker_case(estimator=None, twa_mg_m3=None, risk_tier=None),
        risk_tier=None,
    )
    worker = _build(assessed_messages(_worker_item(occupational_exposure=bare))).facilities[0]
    assert worker.occupational_exposure is not None
    assert worker.occupational_exposure.activities == []
    assert worker.occupational_exposure.activity_reason == "no activity applies"
    assert worker.occupational_exposure.baseline.twa_mg_m3 is None


def test_an_unknown_band_of_a_case_reads_as_none_and_keeps_the_result() -> None:
    old = {**WORKER, "baseline": {**TIER, "risk_tier": "exceedance"}, "risk_tier": "elevated"}
    worker = _build(assessed_messages(_worker_item(occupational_exposure=old))).facilities[0]
    assert worker.occupational_exposure is not None
    assert worker.occupational_exposure.baseline.risk_tier is None
    assert worker.occupational_exposure.risk_tier is None
    assert worker.occupational_exposure.baseline.twa_mg_m3 == 2.0


def test_no_worker_result_stays_absent() -> None:
    facility = _build(assessed_messages(assessed_item("F1", 1.0, [stack(10.0)]))).facilities[0]
    assert facility.occupational_exposure is None and facility.operational_profile is None


def test_a_non_finite_worker_value_leaves_out_only_the_worker_result() -> None:
    bad = {**WORKER, "baseline": {**TIER, "twa_mg_m3": float("nan")}}
    state = _build(assessed_messages(_worker_item(occupational_exposure=bad)))
    facility = state.facilities[0]
    assert facility.occupational_exposure is None and facility.operational_profile is not None
    assert facility.exposure is not None and facility.status == "high"
    assert any("worker exposure of facility F1" in w for w in state.warnings)


def test_a_boolean_where_a_number_is_expected_is_refused() -> None:
    bad = {**WORKER, "rfc": True}
    state = _build(assessed_messages(_worker_item(occupational_exposure=bad)))
    assert state.facilities[0].occupational_exposure is None
    assert any("not valid" in w for w in state.warnings)


def test_an_invalid_profile_is_left_out_alone() -> None:
    state = _build(assessed_messages(_worker_item(operational_profile={"days_per_week": "five"})))
    facility = state.facilities[0]
    assert facility.operational_profile is None and facility.occupational_exposure is not None
    assert any("operational profile of facility F1" in w for w in state.warnings)


def test_the_workspace_names_the_facility_with_the_highest_worker_values() -> None:
    low = {**WORKER, "baseline": {**TIER, "oel_ratio": 0.1, "hq": 0.9, "cancer_risk": None}}
    high = {**WORKER, "baseline": {**TIER, "oel_ratio": 3.0, "hq": 0.2, "cancer_risk": 5e-5}}
    a = _worker_item(occupational_exposure=low, record=record("A", lat=11.0))
    b = _worker_item(occupational_exposure=high, record=record("B", lat=12.0))
    summary = _build(assessed_messages(a, b)).worker_risk
    assert summary.reason is None
    assert summary.baseline.oel_ratio is not None and summary.baseline.oel_ratio.frs_id == "B"
    assert summary.baseline.oel_ratio.value == 3.0
    assert summary.baseline.hq is not None and summary.baseline.hq.frs_id == "A"  # a selection
    assert summary.baseline.cancer_risk is not None and summary.baseline.cancer_risk.frs_id == "B"
    assert summary.worst_case.oel_ratio is not None  # the other tier is summarised too
    assert summary.baseline.oel_ratio.risk_tier == "moderate"
    assert summary.baseline.oel_ratio.evidence == "activity_model"
    assert summary.baseline.oel_ratio.driving_activity == "Drum loading"


def test_a_summary_figure_resting_on_monitoring_says_so() -> None:
    sampled = monitoring_result()
    item = _worker_item(occupational_exposure=sampled, record=record("M", lat=11.0))
    ratio = _build(assessed_messages(item)).worker_risk.worst_case.oel_ratio
    assert ratio is not None and ratio.value == 1.2 and ratio.risk_tier == "high"
    assert ratio.evidence == "monitoring" and ratio.driving_activity is None


def test_without_a_worker_result_the_summary_says_why() -> None:
    summary = _build(assessed_messages(assessed_item("F1", 1.0, [stack(10.0)]))).worker_risk
    assert summary.baseline.oel_ratio is None and summary.reason is not None


def test_every_facility_carries_its_exposure_graph() -> None:
    facility = _build(assessed_messages(_worker_item())).facilities[0]
    graph = facility.exposure_graph
    assert graph is not None
    assert [(lane.id, lane.available) for lane in graph.lanes] == [
        ("community", True),
        ("worker", True),
    ]
    worker_end = next(n for n in graph.nodes if n.id == "worker:endpoint")
    assert (worker_end.status, worker_end.status_label) == ("high", "High")


def test_a_screened_out_facility_keeps_its_worker_result_and_profile() -> None:
    out = _out("BOUND", "bound", 0.05, occupational_exposure=WORKER, operational_profile=PROFILE)
    facility = _build(_tiered([], [out])).facilities[0]
    assert facility.screening is not None and facility.screening.outcome == "screened_out_at_bound"
    assert facility.exposure is None  # no community result: it was screened out
    worker, profile = facility.occupational_exposure, facility.operational_profile
    assert worker is not None and worker.baseline.twa_mg_m3 == 2.0
    assert profile is not None and profile.annual_operating_hours == 4000.0


def test_a_screened_out_facility_of_an_earlier_form_has_no_worker_result() -> None:
    facility = _build(_tiered([], [_out("BOUND", "bound", 0.05)])).facilities[0]
    assert facility.occupational_exposure is None and facility.operational_profile is None


def test_an_invalid_worker_result_of_a_screened_out_facility_leaves_out_only_itself() -> None:
    out = _out("BOUND", "bound", 0.05, occupational_exposure={"junk": 1})
    state = _build(_tiered([], [out]))
    facility = state.facilities[0]
    assert facility.occupational_exposure is None and facility.screening is not None
    assert any("worker exposure of facility BOUND" in w for w in state.warnings)
