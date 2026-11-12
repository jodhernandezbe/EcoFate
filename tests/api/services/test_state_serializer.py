"""The workspace is built from tool calls and results only, and fails closed on bad input."""

from __future__ import annotations

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from api.schemas.workspace import WorkspaceState
from api.services.projectors import PROJECTORS
from api.services.state_serializer import build_workspace, pair_exchanges
from tests.api.services.projectors.factories import (
    RULES,
    capped_inventory,
    entry,
    exchange,
    exposure,
    inventory,
    people,
    record,
    scenario,
    stack,
    stack_result,
    weather,
)
from tools.registry import registry


def build(*parts: list[BaseMessage], previous: WorkspaceState | None = None) -> WorkspaceState:
    return build_workspace([m for part in parts for m in part], RULES, previous)


def test_every_projector_is_a_registered_tool_and_every_tool_has_one() -> None:
    names = {tool.name for tool in registry.all()}
    assert set(PROJECTORS) == names


# --- pairing ----------------------------------------------------------------------------------


def test_calls_are_paired_with_their_results_in_arrival_order() -> None:
    first, second = inventory(record("A")), weather()
    messages = [HumanMessage(content="hi"), *first, *second]
    names = [e.name for e in pair_exchanges(messages)]
    assert names == ["query_emissions_inventory", "get_meteorological_boundary"]


def test_an_unanswered_call_and_a_failed_call_are_dropped() -> None:
    unanswered = AIMessage(content="", tool_calls=[{"id": "x", "name": "t", "args": {}}])
    failed = exchange("get_meteorological_boundary", {}, "boom", status="error")
    assert pair_exchanges([unanswered, *failed]) == []


# --- values come from tools -------------------------------------------------------------------


def test_nothing_is_shown_before_any_tool_ran() -> None:
    state = build()
    assert state.facilities == []
    assert state.framing_version == 0
    assert state.chemical.read_across.kind == "not_evaluated"
    assert state.risk.reason == "not yet computed"


def test_meteorology_carries_what_the_tool_reported() -> None:
    state = build(weather(source="synthetic source"))
    assert state.meteorology is not None
    assert state.meteorology.wind_speed_m_s == 3.0
    assert state.meteorology.source == "synthetic source"
    assert state.meteorology.wind_from_deg == 270.0
    assert state.meteorology.wind_toward_deg == 90.0


def test_screening_defaults_are_flagged() -> None:
    state = build(
        weather(source="screening default"),
        inventory(record()),
        people(source="screening default"),
    )
    assert state.meteorology is not None and state.meteorology.screening_default
    assert state.receptors is not None and state.receptors.screening_default


# --- untrusted results fail closed ------------------------------------------------------------


def test_a_result_that_is_not_json_is_skipped_with_a_warning() -> None:
    state = build(
        exchange("get_meteorological_boundary", {"latitude": 1.0, "longitude": 2.0}, "oops"),
    )
    assert state.meteorology is None
    assert state.warnings == [
        "Left out a get_meteorological_boundary result: its result was not valid.",
    ]


def test_an_inventory_record_with_a_bad_latitude_is_not_placed_and_names_its_id() -> None:
    state = build(inventory(record("GOOD"), record("BAD", lat=123.0)))
    assert [f.frs_id for f in state.facilities] == ["GOOD"]
    assert any("BAD" in w and "not placed" in w for w in state.warnings)


def test_an_inventory_that_is_not_a_list_is_skipped() -> None:
    state = build(exchange("query_emissions_inventory", {"cas_number": "1-1-1"}, {"frs_id": "A"}))
    assert state.facilities == []
    assert len(state.warnings) == 1


def test_a_point_outside_the_globe_leaves_the_result_out() -> None:
    state = build(weather(lat=95.0))
    assert state.meteorology is None
    assert "point" in state.warnings[0]


def test_an_unknown_tool_is_ignored() -> None:
    assert build(exchange("some_other_tool", {}, {"x": 1})) == build()


# --- facilities -------------------------------------------------------------------------------


def test_one_facility_per_frs_id_and_the_latest_result_wins() -> None:
    state = build(inventory(record("A", rate=1.0), record("B")), inventory(record("A", rate=3.0)))
    assert [f.frs_id for f in state.facilities] == ["A", "B"]
    assert state.facilities[0].emission_rate_g_s == 3.0


def test_a_facility_carries_the_inventory_fields_and_the_queried_cas() -> None:
    facility = build(inventory(record(), cas="2-2-2")).facilities[0]
    assert facility.name == "Plant F1"
    assert facility.doc_ctrl_num == "DOCF1"
    assert facility.release_unit == "Pounds"
    assert facility.operating_hours_per_year == 8760.0
    assert facility.operating_hours_source == "default 8760 h/yr (test)"
    assert facility.cas_number == "2-2-2"
    assert facility.status is None


COU = {
    "tri_activity": "As a reactant",
    "tri_section": "3.2a",
    "lifecycle_stage": "Processing",
    "cou_category": "Processing as a reactant",
    "mapping_strength": "Direct",
}


def test_conditions_of_use_are_carried_unchanged() -> None:
    other = {**COU, "tri_section": "3.3c", "lifecycle_stage": "Industrial use"}
    extra = {
        "conditions_of_use": [COU, other],
        "lifecycle_stages": ["Processing", "Industrial use"],
    }
    facility = build(inventory(record() | extra)).facilities[0]
    assert [c.model_dump() for c in facility.conditions_of_use] == [COU, other]
    assert facility.lifecycle_stages == ["Processing", "Industrial use"]
    assert facility.conditions_note is None


def test_the_subsector_is_carried_unchanged() -> None:
    facility = build(inventory(record())).facilities[0]
    assert (facility.naics_subsector, facility.naics_subsector_title) == (
        "325",
        "Chemical Manufacturing",
    )


def test_a_record_without_a_subsector_gives_nulls() -> None:
    bare = {k: v for k, v in record().items() if not k.startswith("naics_subsector")}
    facility = build(inventory(bare)).facilities[0]
    assert (facility.naics_subsector, facility.naics_subsector_title) == (None, None)


def test_the_note_explains_missing_conditions() -> None:
    note = "TRI reported no activity for this submission"
    facility = build(inventory(record() | {"conditions_note": note})).facilities[0]
    assert facility.conditions_of_use == [] and facility.conditions_note == note


def test_a_record_without_conditions_fields_still_builds() -> None:
    facility = build(inventory(record())).facilities[0]
    assert facility.conditions_of_use == [] and facility.lifecycle_stages == []
    assert facility.conditions_note is None


def test_industry_is_attached_by_document_control_number() -> None:
    body: dict[str, object] = {
        "naics_code": "111111",
        "naics_title": "Synthetic industry",
        "code_origin": "reported",
        "source": "s",
    }
    state = build(
        inventory(record("A"), record("B")),
        exchange("fetch_facility_industry", {"doc_ctrl_num": "DOCB"}, body),
    )
    assert state.facilities[0].industry is None
    industry = state.facilities[1].industry
    assert industry is not None and industry.naics_title == "Synthetic industry"


def test_an_industry_for_an_unknown_document_is_unattributed() -> None:
    body = {"naics_code": None, "naics_title": None, "code_origin": None, "source": None}
    state = build(
        inventory(record()),
        exchange("fetch_facility_industry", {"doc_ctrl_num": "NOPE"}, body),
    )
    assert [u.tool for u in state.unattributed] == ["fetch_facility_industry"]


def test_receptors_are_matched_by_coordinates_within_the_tolerance() -> None:
    state = build(
        inventory(record("A", lat=10.0), record("B", lat=40.0)),
        people(lat=10.0005, radius=3.0),
    )
    assert state.facilities[0].receptors is not None
    assert state.facilities[0].receptors.radius_km == 3.0
    assert state.facilities[1].receptors is None


def test_a_population_call_without_a_radius_reports_the_default_radius() -> None:
    state = build(inventory(record()), people(radius=None))
    assert state.facilities[0].receptors is not None
    assert state.facilities[0].receptors.radius_km == RULES.default_radius_km


def test_a_point_that_matches_two_facilities_is_unattributed() -> None:
    state = build(inventory(record("A"), record("B")), people())
    assert all(f.receptors is None for f in state.facilities)
    assert [u.tool for u in state.unattributed] == ["get_population_receptors"]


def test_meteorology_is_attached_by_coordinates_and_shown_even_when_unattached() -> None:
    state = build(inventory(record()), weather(lat=50.0, lon=50.0))
    assert state.facilities[0].meteorology is None
    assert state.meteorology is not None  # the latest result still fills the ribbon


# --- stacks and tiers -------------------------------------------------------------------------


def nei(frs_id: str, *candidates: dict[str, object]) -> list[BaseMessage]:
    body: dict[str, object] = {
        "eis_ids": ["E"],
        "candidates": list(candidates),
        "total_candidates": len(candidates),
        "warnings": [],
    }
    return exchange("fetch_stack_parameters_from_nei", {"frs_id": frs_id}, body)


def test_three_nei_candidates_are_listed_as_tier_one() -> None:
    stacks = (
        build(inventory(record()), nei("F1", stack(5.0), stack(10.0), stack(15.0)))
        .facilities[0]
        .stacks
    )
    assert [s.height_m for s in stacks] == [5.0, 10.0, 15.0]
    assert {s.tier_label for s in stacks} == {"Tier 1: Empirical NEI"}
    assert {s.tier for s in stacks} == {1}


def test_stack_values_a_source_does_not_report_stay_absent() -> None:
    stacks = build(inventory(record()), nei("F1", stack(None))).facilities[0].stacks
    assert stacks[0].height_m is None
    assert stacks[0].exit_temperature_k is None


def test_a_stack_with_no_source_has_no_tier() -> None:
    stacks = build(inventory(record()), nei("F1", stack(source=None))).facilities[0].stacks
    assert stacks[0].tier is None and stacks[0].tier_label is None


def test_a_generic_stack_is_tier_three() -> None:
    base = stack(3.0, source="AirToxScreen global default")
    result = stack_result(1, base, scenario(0.1, 1e-8), scenario(0.1, 1e-8))
    state = build(inventory(record()), exposure(1.0, [result], entry(0.1, 0.1)))
    assert state.facilities[0].stacks[0].tier_label == "Tier 3: EPA global default"


def test_a_pstk_stack_shows_the_scc_description_and_score_of_the_lookup() -> None:
    base = stack(7.0, source="PSTK", scc="30600101")
    lookup = {
        "matches": [{"scc": "30600101", "level_four": "Synthetic process", "score": 0.5}],
        "warnings": [],
    }
    state = build(
        inventory(record()),
        exchange("lookup_scc_process_description", {"naics_description": "x"}, lookup),
        exchange("fetch_stack_parameters_from_scc", {"scc_code": "30600101"}, base),
        exposure(
            1.0,
            [stack_result(1, base, scenario(0.1, None), scenario(0.1, None))],
            entry(0.1, 0.1),
        ),
    )
    shown = state.facilities[0].stacks[0]
    assert shown.tier_label == "Tier 2: PSTK by SCC"
    assert (shown.scc, shown.scc_description, shown.scc_score) == (
        "30600101",
        "Synthetic process",
        0.5,
    )


def test_a_pstk_stack_without_a_lookup_has_no_description() -> None:
    base = stack(7.0, source="PSTK", scc="30600101")
    state = build(
        inventory(record()),
        exchange("fetch_stack_parameters_from_scc", {"scc_code": "30600101"}, base),
        exposure(
            1.0,
            [stack_result(1, base, scenario(0.1, None), scenario(0.1, None))],
            entry(0.1, 0.1),
        ),
    )
    shown = state.facilities[0].stacks[0]
    assert shown.scc == "30600101" and shown.scc_description is None and shown.scc_score is None


def test_nei_stacks_get_their_results_when_evaluated() -> None:
    first, second = stack(5.0), stack(10.0)
    results = [
        stack_result(1, first, scenario(0.2, None), scenario(0.1, None)),
        stack_result(2, second, scenario(0.9, 2e-6), scenario(0.4, None)),
    ]
    state = build(
        inventory(record()),
        nei("F1", first, second),
        exposure(1.0, results, entry(0.2, 0.9, 1, 2), entry(1e-6, 2e-6, 1, 2)),
    )
    stacks = state.facilities[0].stacks
    assert [s.stack_number for s in stacks] == [1, 2]
    assert stacks[1].worst_case is not None and stacks[1].worst_case.hq == 0.9
    assert stacks[1].representative is not None and stacks[1].representative.hq == 0.4


# --- exposure attribution and summary ---------------------------------------------------------


def evaluated(
    rate: float,
    hq: float,
    risk: float | None = None,
    number: int = 1,
) -> list[BaseMessage]:
    base = stack(10.0)
    result = stack_result(number, base, scenario(hq, risk), scenario(hq / 2, None))
    return exposure(
        rate,
        [result],
        entry(hq, hq, number, number),
        entry(risk, risk, number, number) if risk else None,
    )


def test_an_exposure_result_goes_to_the_facility_with_that_emission_rate() -> None:
    state = build(inventory(record("A", rate=1.0), record("B", rate=2.0)), evaluated(2.0, 0.3))
    assert state.facilities[0].exposure is None
    assert state.facilities[1].exposure is not None
    assert state.facilities[1].exposure.hq_worst is not None


def test_an_ambiguous_exposure_result_is_attached_to_neither_and_listed() -> None:
    state = build(inventory(record("A", rate=2.0), record("B", rate=2.0)), evaluated(2.0, 0.3))
    assert all(f.exposure is None for f in state.facilities)
    assert [u.tool for u in state.unattributed] == ["calculate_exposure_metrics"]
    assert state.risk.hq_worst is None
    assert "could not be matched" in (state.risk.reason or "")


def test_no_exposure_yet_gives_no_risk_and_the_reason() -> None:
    state = build(inventory(record()))
    assert state.risk.hq_worst is None and state.risk.cancer_risk_worst is None
    assert state.risk.reason == "not yet computed"


def test_hq_at_the_upper_boundary_or_above_is_high() -> None:
    state = build(inventory(record()), evaluated(1.0, 2.5))
    top = state.risk.hq_worst
    assert top is not None and (top.value, top.status, top.frs_id) == (2.5, "high", "F1")
    assert state.facilities[0].status == "high"


def test_status_bands_follow_the_risk_band_boundaries() -> None:
    def status(hq: float) -> str | None:
        return build(inventory(record()), evaluated(1.0, hq)).facilities[0].status

    assert [status(0.05), status(0.1), status(0.5), status(1.0), status(1.01)] == [
        "low",
        "moderate",
        "moderate",
        "high",
        "high",
    ]


def test_cancer_risk_status_uses_its_own_thresholds() -> None:
    def status(risk: float) -> str | None:
        top = build(inventory(record()), evaluated(1.0, 0.1, risk)).risk.cancer_risk_worst
        return top.status if top else None

    assert [status(1e-7), status(1e-5), status(1e-3)] == ["low", "moderate", "high"]


def test_the_summary_names_the_facility_and_stack_with_the_highest_value() -> None:
    state = build(
        inventory(record("A", rate=1.0, lat=10.0), record("B", rate=2.0, lat=20.0)),
        evaluated(1.0, 0.3),
        evaluated(2.0, 0.8, number=3),
    )
    top = state.risk.hq_worst
    assert top is not None
    assert (top.frs_id, top.facility_name, top.stack_number) == ("B", "Plant B", 3)
    assert state.selected_frs_id == "B"
    assert state.risk.hq_representative is not None and state.risk.hq_representative.value == 0.8


def test_the_ribbon_follows_the_selected_facility() -> None:
    state = build(
        inventory(record("A", rate=1.0, lat=10.0), record("B", rate=2.0, lat=20.0)),
        people(lat=10.0),
        people(lat=20.0, radius=9.0),
        evaluated(2.0, 0.8),
    )
    assert state.receptors is not None and state.receptors.radius_km == 9.0


def test_the_only_facility_is_selected_even_before_any_risk() -> None:
    state = build(inventory(record()), people())
    assert state.selected_frs_id == "F1"
    assert state.receptors is not None


def test_several_facilities_with_nothing_to_tell_them_apart_select_none() -> None:
    assert build(inventory(record("A", lat=1.0), record("B", lat=2.0))).selected_frs_id is None


# --- chemical and read-across -----------------------------------------------------------------


def properties(cas: str = "1-1-1") -> list[BaseMessage]:
    body: dict[str, object] = {
        "preferred_name": "Testane",
        "molecular_weight": 50.0,
        "vapor_pressure": 7.5,
        "rfc": 0.5,
        "iur": 1e-6,
        "sources": {"rfc": "IRIS", "vapor_pressure": "CompTox (experimental)"},
        "warnings": [],
    }
    return exchange("fetch_chemical_properties", {"cas_number": cas}, body)


def surrogate(
    *,
    direct: bool = False,
    in_domain: bool = True,
    cas: str = "1-1-1",
) -> list[BaseMessage]:
    body: dict[str, object] = {
        "query_cas": cas,
        "is_direct_tri_match": direct,
        "surrogate_tri_cas": None if direct else "9-9-9",
        "surrogate_name": None if direct else "Synthetic surrogate",
        "moldeberta_cosine_sim": 0.5,
        "morgan_tanimoto_sim": 0.25,
        "hybrid_read_across_score": 0.4,
        "within_applicability_domain": in_domain,
        "resolution_method": "direct_tri_catalog_match" if direct else "hybrid_read_across",
        "warnings": [],
    }
    return exchange("find_tri_read_across_surrogate", {"cas_number": cas}, body)


def test_the_chemical_shows_the_properties_with_their_sources() -> None:
    chemical = build(properties()).chemical
    assert chemical.cas_number == "1-1-1"
    assert (chemical.molecular_weight_g_mol, chemical.rfc_mg_m3, chemical.iur_per_ug_m3) == (
        50.0,
        0.5,
        1e-6,
    )
    assert chemical.vapor_pressure_mmhg == 7.5
    assert chemical.sources == {"rfc": "IRIS", "vapor_pressure": "CompTox (experimental)"}
    assert chemical.name == "Testane"


def test_a_chemical_without_a_name_has_none() -> None:
    messages = properties()
    body: dict[str, object] = {"molecular_weight": 50.0, "sources": {}, "warnings": ["no name"]}
    chemical = build(exchange("fetch_chemical_properties", {"cas_number": "1-1-1"}, body)).chemical
    assert chemical.name is None and chemical.molecular_weight_g_mol == 50.0
    assert build(messages).chemical.name == "Testane"


def test_a_direct_tri_match_is_shown_as_one() -> None:
    assert build(surrogate(direct=True)).chemical.read_across.kind == "direct_tri_match"


def test_a_surrogate_shows_its_scores_and_domain() -> None:
    shown = build(surrogate(in_domain=True)).chemical.read_across
    assert shown.kind == "read_across"
    assert (shown.surrogate_cas, shown.surrogate_name) == ("9-9-9", "Synthetic surrogate")
    assert (shown.hybrid_score, shown.cosine_similarity, shown.tanimoto_similarity) == (
        0.4,
        0.5,
        0.25,
    )
    assert shown.within_applicability_domain is True


def test_a_surrogate_out_of_domain_is_flagged() -> None:
    assert (
        build(surrogate(in_domain=False)).chemical.read_across.within_applicability_domain is False
    )


def test_an_unresolved_chemical_is_not_a_surrogate() -> None:
    body: dict[str, object] = {
        "query_cas": "1-1-1",
        "is_direct_tri_match": False,
        "within_applicability_domain": False,
        "resolution_method": "unresolved",
        "warnings": ["no surrogate"],
    }
    state = build(exchange("find_tri_read_across_surrogate", {"cas_number": "1-1-1"}, body))
    assert state.chemical.read_across.kind == "unresolved"


def test_results_for_an_earlier_chemical_are_not_shown_for_the_latest() -> None:
    state = build(properties("1-1-1"), surrogate(cas="1-1-1"), inventory(record(), cas="3-3-3"))
    assert state.chemical.cas_number == "3-3-3"
    assert state.chemical.rfc_mg_m3 is None
    assert state.chemical.read_across.kind == "not_evaluated"


def test_the_cas_is_matched_ignoring_hyphens() -> None:
    assert build(properties("111"), inventory(record(), cas="1-1-1")).chemical.rfc_mg_m3 == 0.5


# --- framing ----------------------------------------------------------------------------------


def test_new_facilities_raise_the_framing_version_and_set_the_bounds() -> None:
    state = build(inventory(record("A", lat=10.0, lon=-20.0), record("B", lat=30.0, lon=-10.0)))
    assert state.framing_version == 1
    assert state.bounds is not None
    assert (state.bounds.west, state.bounds.south, state.bounds.east, state.bounds.north) == (
        -20.0,
        10.0,
        -10.0,
        30.0,
    )


def test_an_unrelated_update_leaves_the_framing_version_alone() -> None:
    before = build(inventory(record()))
    after = build(inventory(record()), properties(), previous=before)
    assert after.framing_version == before.framing_version == 1


def test_a_new_buffer_raises_the_framing_version() -> None:
    before = build(inventory(record()))
    assert build(inventory(record()), people(), previous=before).framing_version == 2


def test_a_new_facility_raises_the_framing_version_again() -> None:
    before = build(inventory(record("A")))
    after = build(inventory(record("A")), inventory(record("B", lat=30.0)), previous=before)
    assert after.framing_version == 2


def test_the_state_is_rebuilt_identically_from_the_same_messages() -> None:
    messages = [*inventory(record()), *people(), *weather()]
    assert build_workspace(messages, RULES) == build_workspace(messages, RULES)


# --- drawn shapes -----------------------------------------------------------------------------


def test_a_facility_with_receptors_has_a_buffer_at_their_radius() -> None:
    facility = build(inventory(record()), people(radius=3.0)).facilities[0]
    assert facility.buffer is not None
    assert facility.sector is None  # no weather yet
    ring = facility.buffer.coordinates[0]
    assert ring[0] == ring[-1]


def test_a_facility_with_receptors_and_weather_has_a_sector_toward_the_wind() -> None:
    facility = build(inventory(record()), people(radius=3.0), weather()).facilities[0]
    assert facility.sector is not None
    arc = facility.sector.coordinates[0][1:-1]
    assert all(p[0] > facility.longitude for p in arc)  # wind from 270 blows toward 90 (east)


def test_no_shapes_without_receptors() -> None:
    facility = build(inventory(record()), weather()).facilities[0]
    assert facility.buffer is None and facility.sector is None


def test_the_bounds_cover_the_buffer() -> None:
    plain = build(inventory(record())).bounds
    drawn = build(inventory(record()), people(radius=3.0)).bounds
    assert plain is not None and drawn is not None
    assert drawn.west < plain.west and drawn.east > plain.east
    assert drawn.south < plain.south and drawn.north > plain.north


# --- the inventory the model reads is capped, the workspace's is not -------------------------


def test_every_facility_is_placed_even_when_the_model_was_shown_only_the_largest() -> None:
    state = build(
        capped_inventory(record("A"), record("B", lat=20.0), record("C", lat=30.0), shown=1),
    )
    assert [f.frs_id for f in state.facilities] == ["A", "B", "C"]


def test_a_capped_result_without_its_artifact_still_places_what_was_listed() -> None:
    listed = {
        "total_found": 3,
        "matching": 3,
        "shown": 1,
        "facilities": [record("A")],
        "note": "partial",
    }
    state = build(exchange("query_emissions_inventory", {"cas_number": "1-1-1"}, listed))
    assert [f.frs_id for f in state.facilities] == ["A"]


def test_a_dict_without_facilities_is_left_out() -> None:
    state = build(
        exchange("query_emissions_inventory", {"cas_number": "1-1-1"}, {"total_found": 0}),
    )
    assert state.facilities == [] and len(state.warnings) == 1


def test_an_artifact_that_is_not_a_list_falls_back_to_the_text() -> None:
    messages = exchange(
        "query_emissions_inventory",
        {"cas_number": "1-1-1"},
        [record("A")],
        artifact="junk",
    )
    assert [f.frs_id for f in build(messages).facilities] == ["A"]


# --- NAICS from the inventory ------------------------------------------------------------------


def test_the_inventory_naics_code_shows_until_the_industry_tool_answers() -> None:
    state = build(inventory(record(naics_code="311224")))
    industry = state.facilities[0].industry
    assert industry is not None
    assert (industry.naics_code, industry.naics_title, industry.source) == (
        "311224",
        None,
        "TRI inventory",
    )


def test_the_inventory_title_shows_for_every_facility() -> None:
    state = build(inventory(record(naics_code="311224", naics_title="Synthetic milling")))
    industry = state.facilities[0].industry
    assert industry is not None
    assert (industry.naics_title, industry.code_origin, industry.source) == (
        "Synthetic milling",
        None,
        "TRI inventory",
    )


def test_the_industry_tool_answer_replaces_the_bare_code() -> None:
    body = {
        "naics_code": "311224",
        "naics_title": "Synthetic milling",
        "code_origin": "reported",
        "source": "TRI",
    }
    state = build(
        inventory(record(naics_code="311224")),
        exchange("fetch_facility_industry", {"doc_ctrl_num": "DOCF1"}, body),
    )
    industry = state.facilities[0].industry
    assert industry is not None and industry.naics_title == "Synthetic milling"


def test_a_facility_without_a_naics_code_has_no_industry() -> None:
    assert build(inventory(record())).facilities[0].industry is None


# --- which place the weather is for ---------------------------------------------------------------


def test_weather_at_a_facility_names_that_facility() -> None:
    state = build(inventory(record()), weather())
    shown = state.facilities[0].meteorology
    assert shown is not None and (shown.frs_id, shown.facility_name) == ("F1", "Plant F1")
    assert (shown.latitude, shown.longitude) == (10.0, -20.0)


def test_weather_for_another_point_says_it_is_no_facility() -> None:
    state = build(inventory(record()), weather(lat=50.0, lon=50.0))
    assert state.meteorology is not None
    assert state.meteorology.frs_id is None and state.meteorology.facility_name is None
    assert (state.meteorology.latitude, state.meteorology.longitude) == (50.0, 50.0)


def _missing_rfc(cas: str = "1-1-1") -> list[BaseMessage]:
    body: dict[str, object] = {
        "preferred_name": "Testane",
        "molecular_weight": 50.0,
        "rfc": None,
        "iur": 1e-6,
        "sources": {"iur": "IRIS"},
        "warnings": ["rfc: not found in CompTox"],
    }
    return exchange("fetch_chemical_properties", {"cas_number": cas}, body)


def test_a_supplied_value_fills_the_empty_benchmark_as_the_users() -> None:
    chemical = build_workspace(_missing_rfc(), RULES, supplied={"rfc:1-1-1": 0.5}).chemical
    assert chemical.rfc_mg_m3 == 0.5
    assert chemical.sources == {"iur": "IRIS", "rfc": "user-provided"}
    assert chemical.warnings == []  # the tool's "rfc: not found" no longer holds


def test_a_supplied_value_never_replaces_a_tool_value() -> None:
    chemical = build_workspace(properties(), RULES, supplied={"rfc:1-1-1": 9.0}).chemical
    assert chemical.rfc_mg_m3 == 0.5 and chemical.sources["rfc"] == "IRIS"


def test_a_supplied_value_for_another_cas_is_not_shown() -> None:
    chemical = build_workspace(_missing_rfc("1-1-1"), RULES, supplied={"rfc:2-2-2": 0.5}).chemical
    assert chemical.rfc_mg_m3 is None and chemical.cas_number == "1-1-1"


def test_a_supplied_value_shows_even_before_any_tool_ran() -> None:
    chemical = build_workspace([], RULES, supplied={"iur:3-3-3": 2e-6}).chemical
    assert chemical.cas_number == "3-3-3" and chemical.iur_per_ug_m3 == 2e-6
    assert chemical.sources == {"iur": "user-provided"}


def _props(**over: object) -> list[BaseMessage]:
    body: dict[str, object] = {
        "preferred_name": "Testane",
        "molecular_weight": None,
        "vapor_pressure": None,
        "density": None,
        "rfc": 0.5,
        "iur": 1e-6,
        "sources": {},
        "warnings": [],
        "occupational_limits": {"oel_twa_mg_m3": None, "oel_source": None},
        **over,
    }
    return exchange("fetch_chemical_properties", {"cas_number": "1-1-1"}, body)


def test_the_chemical_shows_its_density_and_occupational_limit_with_the_limit_source() -> None:
    limits = {"oel_twa_mg_m3": 3.2, "oel_source": "OSHA PEL-TWA (PubChem)"}
    chemical = build(_props(density=0.88, occupational_limits=limits)).chemical
    assert chemical.density_g_cm3 == 0.88 and chemical.oel_twa_mg_m3 == 3.2
    assert chemical.sources["oel_twa"] == "OSHA PEL-TWA (PubChem)"


def test_values_the_user_entered_fill_every_missing_property_and_are_labelled() -> None:
    supplied = {
        "molecular_weight:1-1-1": 78.0,
        "vapor_pressure:1-1-1": 95.0,
        "density:1-1-1": 0.88,
        "oel_twa:1-1-1": 3.2,
    }
    chemical = build_workspace(_props(), RULES, supplied=supplied).chemical
    assert chemical.molecular_weight_g_mol == 78.0 and chemical.vapor_pressure_mmhg == 95.0
    assert chemical.density_g_cm3 == 0.88 and chemical.oel_twa_mg_m3 == 3.2
    for key in ("molecular_weight", "vapor_pressure", "density", "oel_twa"):
        assert chemical.sources[key] == "user-provided"


def test_a_value_a_source_has_is_never_replaced_by_one_the_user_entered() -> None:
    limits = {"oel_twa_mg_m3": 3.2, "oel_source": "OSHA PEL-TWA (PubChem)"}
    supplied = {"oel_twa:1-1-1": 9.0, "density:1-1-1": 5.0}
    chemical = build_workspace(
        _props(density=0.88, occupational_limits=limits),
        RULES,
        supplied=supplied,
    ).chemical
    assert chemical.oel_twa_mg_m3 == 3.2 and chemical.density_g_cm3 == 0.88
    assert chemical.sources["oel_twa"] == "OSHA PEL-TWA (PubChem)"
