"""Tests for the assess_facilities tool: tiers, selection, benchmarks, caps and both views."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest
from langchain_core.messages import ToolMessage

from tests.tools.assessment.factories import SETTINGS, FakeSteps, match, record, stack
from tests.tools.emissions.records import worker_only_facility
from tests.tools.informatics.read_across_fakes import category_index
from tools.assessment import facilities
from tools.assessment.facilities import assess_facilities, run_assessment
from tools.emissions.helpers.inventory.listing import rank_and_cap, with_worker_only
from tools.schemas import EmissionRecord, Toxicity, WorkerOnlyFacility

# The fake unit-rate bound is HQ 1/3 (the generic 3 m stack), so a bound reaches HQ 0.1 from
# 0.3 g/s. With its own stack the fake HQ is rate / height.
RECORDS = [
    record("BIG_TALL", emission_rate=50.0),  # bound 16.7; own 100 m stack: HQ 0.5
    record("SMALL_LOW", emission_rate=2.0),  # bound 0.67; own 1 m stack: HQ 2.0, the riskiest
    record("MID", emission_rate=10.0),  # bound 3.3; own 50 m stack: HQ 0.2
    record("TALL_ONLY", emission_rate=4.0),  # bound 1.3; own 100 m stack: HQ 0.04, out
    record("TINY", emission_rate=0.1),  # bound 0.033: out at the bound
]
HEIGHTS = {"BIG_TALL": 100.0, "SMALL_LOW": 1.0, "MID": 50.0, "TALL_ONLY": 100.0}
PROPERTIES_CALLS: list[str] = []
BENCHMARKS: dict[str, float | None] = {"rfc": 0.5, "iur": None}


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> FakeSteps:
    PROPERTIES_CALLS.clear()
    BENCHMARKS.update(rfc=0.5, iur=None)
    monkeypatch.setattr(facilities, "get_assessment_settings", lambda: SETTINGS)

    def listing(cas: str, state: str | None = None, city: str | None = None):  # noqa: ANN202
        return rank_and_cap(list(RECORDS), 2, state, city)

    class Properties:
        @staticmethod
        def invoke(args: dict[str, str], config: object = None) -> dict[str, object]:
            PROPERTIES_CALLS.append(args["cas_number"])
            warnings = ["iur: not found in CompTox", "density: not found"]
            return {**BENCHMARKS, "warnings": warnings}

    monkeypatch.setattr(facilities, "inventory_listing", listing)
    monkeypatch.setattr(facilities, "fetch_chemical_properties", Properties)

    def resolved(records: list[EmissionRecord]) -> list[EmissionRecord]:
        return [{**r, "eis_ids": ["9"], "eis_note": None} for r in records]

    monkeypatch.setattr(facilities, "with_eis_ids", resolved)
    fake = FakeSteps(nei_stacks={f: [stack(h)] for f, h in HEIGHTS.items()})
    monkeypatch.setattr(facilities, "default_steps", fake.steps)
    return fake


def _run(frs_ids: list[str] | None = None, toxicity: Toxicity | None = None):  # noqa: ANN202
    return run_assessment(
        "50-00-0",
        frs_ids,
        (None, None),
        None,
        toxicity,
        facilities.default_steps(),
    )


def _ids(items: Sequence[Mapping[str, object]]) -> list[object]:
    return [i["frs_id"] for i in items]


def test_every_facility_is_screened_and_the_riskiest_are_assessed_first(
    _offline: FakeSteps,
) -> None:
    view, artifact = _run()
    # Ranked by own-stack worst-case risk, not by emissions; the cap is 3.
    assert _ids(view["facilities"]) == ["SMALL_LOW", "BIG_TALL", "MID"]
    assert view["assessed"] == 3 and view["facilities_found"] == 5
    screening = view["screening"]
    assert screening is not None
    assert (screening["screened_out_at_bound"], screening["screened_out_with_own_stacks"]) == (1, 1)
    out = {o["record"]["frs_id"]: o["stage"] for o in artifact["screened_out"]}
    assert out == {"TINY": "bound", "TALL_ONLY": "own stacks"}
    # Nothing is requested for a facility screened out at the bound.
    assert ("nei", ("TINY", ("9",))) not in _offline.calls
    assert view["note"] is not None and "All 5 facilities were screened" in view["note"]


def test_screened_out_facilities_still_get_their_worker_screening() -> None:
    view, artifact = _run()
    for out in artifact["screened_out"]:
        assert "occupational_exposure" in out and "operational_profile" in out
    screening = view["screening"]
    assert screening is not None
    assert sum(screening["screened_out_worker_bands"].values()) == 2
    top = screening["screened_out_worker_highest"]
    assert top is not None and top["frs_id"] in {"TINY", "TALL_ONLY"}
    assert all("worker_risk_tier" in o for o in screening["closest_screened_out"])
    assert view["note"] is not None and "does not apply to workers" in view["note"]


def test_beyond_the_full_cap_facilities_are_kept_at_their_worst_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace

    monkeypatch.setattr(
        facilities,
        "get_assessment_settings",
        lambda: replace(SETTINGS, max_facilities=1),
    )
    view, artifact = _run()
    assert _ids(view["facilities"]) == ["SMALL_LOW"]
    assert view["worst_case_only_count"] == 2
    assert _ids(view["worst_case_only"]) == ["BIG_TALL", "MID"]
    levels = {i["record"]["frs_id"]: i["level"] for i in artifact["assessed"]}
    assert levels == {"SMALL_LOW": "full", "BIG_TALL": "worst case only", "MID": "worst case only"}
    assert all(
        i["meteorology"] is None for i in artifact["assessed"] if i["level"] == "worst case only"
    )


def test_the_chemicals_benchmarks_are_looked_up_and_only_their_warnings_kept() -> None:
    view, _ = _run()
    assert view["toxicity"] == {"rfc": 0.5, "iur": None} and view["toxicity_source"] == "CompTox"
    assert view["warnings"] == ["iur: not found in CompTox"]
    assert PROPERTIES_CALLS == ["50-00-0"]


def test_given_benchmarks_are_used_and_the_chemical_is_still_looked_up_for_its_limits() -> None:
    given = Toxicity(rfc=2.0, iur=1e-6)
    view, _ = _run(toxicity=given)
    assert view["toxicity"] == given and view["toxicity_source"] == "given"
    assert PROPERTIES_CALLS == ["50-00-0"]  # for the worker screening, not for the benchmarks


def test_a_lookup_that_cannot_be_made_does_not_stop_an_assessment_with_given_benchmarks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Down:
        @staticmethod
        def invoke(args: dict[str, str], config: object = None) -> dict[str, object]:
            raise RuntimeError("the CompTox key is not set")

    monkeypatch.setattr(facilities, "fetch_chemical_properties", Down)
    given = Toxicity(rfc=2.0, iur=1e-6)
    view, artifact = _run(toxicity=given)
    assert view["assessed"] > 0 and artifact["assessed"]
    assert any("could not be looked up" in w for w in view["warnings"])
    worker = artifact["assessed"][0]["occupational_exposure"]
    assert worker["oel_twa_mg_m3"] is None and worker["rfc"] == 2.0


def test_without_any_benchmark_nothing_is_screened_out_and_every_warning_says_why() -> None:
    BENCHMARKS.update(rfc=None, iur=None)
    view, artifact = _run()
    assert view["warnings"] == ["iur: not found in CompTox", "density: not found"]
    assert artifact["screened_out"] == []
    assert view["screening"] is not None and not view["screening"]["possible"]
    assert view["assessed"] == 3 and view["worst_case_only_count"] == 2
    assert view["note"] is not None and "could be screened out" in view["note"]


def test_facilities_asked_for_by_id_are_assessed_without_screening(_offline: FakeSteps) -> None:
    view, artifact = _run(["TINY", " MID ", "NOPE", "TINY"])
    assert [i["record"]["frs_id"] for i in artifact["assessed"]] == ["TINY", "MID"]
    assert all(i["level"] == "full" and i["bound"] is None for i in artifact["assessed"])
    assert view["not_assessed"] == [
        {"frs_id": "NOPE", "reason": "not in the inventory of this chemical (and place)"},
    ]
    assert view["screening"] is None and artifact["screened_out"] == []


def test_facilities_asked_for_by_id_beyond_the_cap_keep_their_worst_case() -> None:
    ids = [r["frs_id"] for r in RECORDS]
    view, artifact = _run(ids)
    assert [i["record"]["frs_id"] for i in artifact["assessed"]] == ids
    levels = [i["level"] for i in artifact["assessed"]]
    assert levels == ["full"] * 3 + ["worst case only"] * (len(ids) - 3)
    assert view["not_assessed"] == [] and artifact["not_assessed"] == []
    assert all(
        i["meteorology"] is None for i in artifact["assessed"] if i["level"] == "worst case only"
    )


def test_the_artifact_lists_the_facilities_not_assessed_with_their_reasons(
    _offline: FakeSteps,
) -> None:
    view, artifact = _run(["MID", "NOPE"])
    reason = "not in the inventory of this chemical (and place)"
    assert artifact["not_assessed"] == [{"frs_id": "NOPE", "reason": reason}]
    assert view["not_assessed"] == artifact["not_assessed"]


def test_over_the_safety_bound_the_rest_is_not_assessed_and_the_call_warns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace

    monkeypatch.setattr(
        facilities,
        "get_assessment_settings",
        lambda: replace(SETTINGS, max_refined=1),
    )
    view, artifact = _run()
    assert len(artifact["not_assessed"]) >= 1
    assert all(
        "more than 1 facilities reach a threshold" in n["reason"] for n in artifact["not_assessed"]
    )
    assert any("safety bound of 1" in w for w in view["warnings"])


def test_the_scc_search_is_made_once_per_industry_title(
    monkeypatch: pytest.MonkeyPatch,
    _offline: FakeSteps,
) -> None:
    twins = [record(f"P{i}", emission_rate=5.0, naics_title="Same Industry") for i in range(3)]

    def listing(cas: str, state: str | None = None, city: str | None = None):  # noqa: ANN202
        return rank_and_cap(twins, 2)

    monkeypatch.setattr(facilities, "inventory_listing", listing)
    _offline.matches = [match("10100101", 0.9)]
    _offline.pstk_rows = {"10100101": stack(2.0, "PSTK", "10100101")}
    view, _ = _run()
    assert sum(name == "scc" for name, _ in _offline.calls) == 1
    assert view["stack_tiers"] == {"PSTK": 3}
    prefetched = [titles for name, titles in _offline.calls if name == "prefetch"]
    assert prefetched == [("Same Industry",)]  # all the titles together, once, before any search


def test_an_invalid_cas_number_assesses_nothing() -> None:
    view, artifact = run_assessment(
        "not-a-cas",
        None,
        (None, None),
        None,
        None,
        facilities.default_steps(),
    )
    assert artifact == {
        "assessed": [],
        "screened_out": [],
        "not_assessed": [],
        "worker_only": [],
        "worker_only_left_out": 0,
        "drivers": [],
    }
    assert view["assessed"] == 0 and "not a valid CAS" in view["warnings"][0]
    assert PROPERTIES_CALLS == []


def test_the_tool_gives_the_model_the_summary_and_the_program_every_detail() -> None:
    message = assess_facilities.invoke(
        {
            "type": "tool_call",
            "id": "c1",
            "name": "assess_facilities",
            "args": {"cas_number": "50-00-0"},
        },
    )
    assert isinstance(message, ToolMessage)
    view = json.loads(str(message.content))
    assert view["assessed"] == 3 and "facilities" in view
    assert "stacks" not in view["facilities"][0]  # the details stay out of the model's text
    assert "screened_out" not in view
    assert [i["record"]["frs_id"] for i in message.artifact["assessed"]] == [
        "SMALL_LOW",
        "BIG_TALL",
        "MID",
    ]
    assert len(message.artifact["screened_out"]) == 2


def test_schema() -> None:
    assert set(assess_facilities.args) == {
        "cas_number",
        "frs_ids",
        "state",
        "city",
        "radius_km",
        "toxicity",
    }


MEMBER = "95-57-8"  # 2-chlorophenol: not in TRI on its own, a member of category N084


_ROWS = (
    "95-57-8,N084,CHLOROPHENOLS,2-chlorophenol,Organic,x",
    "95-57-8,N085,SECOND GROUP,2-chlorophenol,Organic,x",
)


def _member_setup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    own: list[EmissionRecord],
    by_code: Mapping[str, list[EmissionRecord]],
    rows: tuple[str, ...] = (
        "95-57-8,N084,CHLOROPHENOLS,2-chlorophenol,Organic,x",
        "95-57-8,N085,SECOND GROUP,2-chlorophenol,Organic,x",
    ),
) -> list[str]:
    asked: list[str] = []

    def listing(cas: str, state: str | None = None, city: str | None = None):  # noqa: ANN202
        asked.append(cas)
        return rank_and_cap(own if cas == MEMBER else by_code.get(cas, []), 25, state, city)

    monkeypatch.setattr(facilities, "inventory_listing", listing)
    monkeypatch.setattr(facilities, "get_category_index", lambda: category_index(tmp_path, *rows))
    return asked


def test_member_without_own_releases_is_assessed_on_its_category(
    monkeypatch: pytest.MonkeyPatch,
    _offline: FakeSteps,
    tmp_path: Path,
) -> None:
    asked = _member_setup(
        monkeypatch,
        tmp_path,
        own=[],
        by_code={"N084": [record("PLANT_A", emission_rate=5.0)]},
    )
    view, artifact = run_assessment(
        MEMBER,
        None,
        (None, None),
        None,
        None,
        facilities.default_steps(),
    )
    assert asked == [MEMBER, "N084", "N085"]
    assert _ids(view["facilities"]) == ["PLANT_A"]
    assert artifact["assessed"] or artifact["screened_out"]
    assert any("TRI category N084" in w and "every member" in w for w in view["warnings"])
    assert PROPERTIES_CALLS == [MEMBER]  # the benchmark is still the chemical's own


def test_shared_facility_across_categories_keeps_the_larger_release(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _member_setup(
        monkeypatch,
        tmp_path,
        own=[],
        by_code={
            "N084": [record("SHARED", emission_rate=2.0)],
            "N085": [record("SHARED", emission_rate=7.0)],
        },
    )
    found = facilities.category_records(MEMBER, (None, None))
    assert [(r["frs_id"], r["emission_rate"]) for r in found.records] == [("SHARED", 7.0)]
    assert any("more than one" in n for n in found.notes)


def test_own_releases_win_over_the_categories(
    monkeypatch: pytest.MonkeyPatch,
    _offline: FakeSteps,
    tmp_path: Path,
) -> None:
    asked = _member_setup(
        monkeypatch,
        tmp_path,
        own=[record("OWN", emission_rate=3.0)],
        by_code={"N084": [record("CAT", emission_rate=9.0)]},
    )
    view, _ = run_assessment(MEMBER, None, (None, None), None, None, facilities.default_steps())
    assert asked == [MEMBER]
    assert "CAT" not in _ids(view["facilities"])
    assert not any("has no TRI release of its own" in w for w in view["warnings"])


ANALOGUE = "110-54-3"


class _Read:
    """A read-across answer; ``invoke`` mirrors the tool's call signature."""

    def __init__(self, match: dict[str, object]) -> None:
        self.match = match
        self.calls: list[str] = []

    def invoke(self, args: dict[str, str]) -> dict[str, object]:
        self.calls.append(args["cas_number"])
        return self.match


def _hybrid(in_domain: bool) -> dict[str, object]:
    return {
        "surrogate_tri_cas": ANALOGUE,
        "surrogate_name": "n-Hexane",
        "resolution_method": "hybrid_read_across",
        "hybrid_read_across_score": 0.66 if in_domain else 0.41,
        "within_applicability_domain": in_domain,
        "mw_scaling_factor": 1.5,
    }


def _no_own_benchmark(monkeypatch: pytest.MonkeyPatch, read: _Read) -> None:
    class Properties:
        @staticmethod
        def invoke(args: dict[str, str], config: object = None) -> dict[str, object]:
            if args["cas_number"] == ANALOGUE:
                return {"rfc": 0.2, "iur": None, "warnings": []}
            return {"rfc": None, "iur": None, "warnings": ["rfc: not found"]}

    monkeypatch.setattr(facilities, "fetch_chemical_properties", Properties)
    monkeypatch.setattr(facilities, "find_tri_read_across_surrogate", read)


def test_in_domain_analogue_supplies_the_benchmarks_and_says_so(
    monkeypatch: pytest.MonkeyPatch,
    _offline: FakeSteps,
) -> None:
    read = _Read(_hybrid(in_domain=True))
    _no_own_benchmark(monkeypatch, read)
    view, _ = _run()
    assert read.calls == ["50-00-0"]
    assert view["toxicity"]["rfc"] == 0.2
    assert view["toxicity_source"].startswith("read-across from 110-54-3")
    note = " ".join(view["warnings"])
    assert "not measured values for 50-00-0" in note and "scaling factor (1.5)" in note


def test_out_of_domain_analogue_is_not_used_and_the_threshold_is_named(
    monkeypatch: pytest.MonkeyPatch,
    _offline: FakeSteps,
) -> None:
    _no_own_benchmark(monkeypatch, _Read(_hybrid(in_domain=False)))
    view, _ = _run()
    assert view["toxicity"]["rfc"] is None
    assert view["toxicity_source"] == "CompTox"
    assert any("not used as a stand-in" in w and "0.41" in w for w in view["warnings"])


def test_own_benchmark_is_never_replaced_by_an_analogue(
    monkeypatch: pytest.MonkeyPatch,
    _offline: FakeSteps,
) -> None:
    read = _Read(_hybrid(in_domain=True))
    monkeypatch.setattr(facilities, "find_tri_read_across_surrogate", read)
    view, _ = _run()
    assert read.calls == []
    assert view["toxicity_source"] == "CompTox"


def test_a_failed_tri_read_is_not_taken_for_no_releases(
    monkeypatch: pytest.MonkeyPatch,
    _offline: FakeSteps,
    tmp_path: Path,
) -> None:
    """Regression: a failed TRI read must not fall back to the category, nor claim no releases."""
    from tools.emissions.helpers.inventory.lookup import TriReadError

    asked: list[str] = []

    def listing(cas: str, state: str | None = None, city: str | None = None):  # noqa: ANN202
        asked.append(cas)
        if cas == MEMBER:
            raise TriReadError(f"TRI could not be read for {cas}: HTTP 500")
        return rank_and_cap([record("CAT", emission_rate=9.0)], 25, state, city)

    monkeypatch.setattr(facilities, "inventory_listing", listing)
    monkeypatch.setattr(facilities, "get_category_index", lambda: category_index(tmp_path, *_ROWS))
    view, artifact = run_assessment(
        MEMBER,
        None,
        (None, None),
        None,
        None,
        facilities.default_steps(),
    )
    assert asked == [MEMBER]  # (a) the category route was never queried
    warnings = " ".join(view["warnings"])
    assert "not completed" in warnings and "could not be read" in warnings  # (c) reported
    assert "no TRI release of its own" not in warnings  # (b) no claim of absence
    assert view["assessed"] == 0 and artifact["screened_out"] == []
    assert PROPERTIES_CALLS == []  # nothing else was run on a failed read


def test_a_failed_category_read_is_not_completed_either(
    monkeypatch: pytest.MonkeyPatch,
    _offline: FakeSteps,
    tmp_path: Path,
) -> None:
    from tools.emissions.helpers.inventory.lookup import TriReadError

    def listing(cas: str, state: str | None = None, city: str | None = None):  # noqa: ANN202
        if cas == MEMBER:
            return rank_and_cap([], 25, state, city)
        raise TriReadError(f"TRI could not be read for {cas}: HTTP 500")

    monkeypatch.setattr(facilities, "inventory_listing", listing)
    monkeypatch.setattr(facilities, "get_category_index", lambda: category_index(tmp_path, *_ROWS))
    view, artifact = run_assessment(
        MEMBER,
        None,
        (None, None),
        None,
        None,
        facilities.default_steps(),
    )
    assert "not completed" in " ".join(view["warnings"])
    assert view["assessed"] == 0 and artifact["screened_out"] == []


def test_every_assessed_facility_carries_community_worker_and_profile_results() -> None:
    view, artifact = _run()
    assert artifact["assessed"]
    for item in artifact["assessed"]:
        assert item["exposure"]["results"] is not None  # the community result is unchanged
        assert "evidence" in item["occupational_exposure"]
        assert item["operational_profile"]["annual_operating_hours"] == 8760.0
    assert all("worker_risk_tier" in f for f in view["facilities"])
    assert all("worker_oel_ratio" in f for f in view["facilities"])


def test_screened_out_facilities_get_no_worker_result() -> None:
    _, artifact = _run()
    assert {s["record"]["frs_id"] for s in artifact["screened_out"]}.isdisjoint(
        {a["record"]["frs_id"] for a in artifact["assessed"]},
    )


def test_without_limits_the_worker_result_says_so() -> None:
    _, artifact = _run(toxicity=Toxicity(rfc=2.0, iur=1e-6))
    warnings = " ".join(artifact["assessed"][0]["occupational_exposure"]["warnings"])
    assert "no 8-hour occupational limit" in warnings


def test_the_chemicals_limits_and_vapor_pressure_reach_the_worker_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limits: dict[str, object] = {
        "oel_twa_mg_m3": 3.0,
        "oel_source": "OSHA PEL-TWA (PubChem)",
        "limits": {},
        "reasons": {},
        "warnings": [],
    }

    class Properties:
        @staticmethod
        def invoke(args: dict[str, str], config: object = None) -> dict[str, object]:
            return {
                "rfc": 0.5,
                "iur": None,
                "warnings": [],
                "vapor_pressure": 7.0,
                "molecular_weight": 84.0,
                "sources": {"vapor_pressure": "experimental", "molecular_weight": "PubChem"},
                "occupational_limits": limits,
            }

    monkeypatch.setattr(facilities, "fetch_chemical_properties", Properties)
    _, artifact = _run()
    worker = artifact["assessed"][0]["occupational_exposure"]
    assert worker["oel_twa_mg_m3"] == 3.0 and worker["oel_source"] == "OSHA PEL-TWA (PubChem)"
    assert worker["vapor_pressure_mmhg"] == 7.0
    assert worker["vapor_pressure_source"] == "CompTox (experimental)"
    assert worker["molecular_weight"] == 84.0 and worker["molecular_weight_source"] == "PubChem"


def _with_workers(
    monkeypatch: pytest.MonkeyPatch,
    workers: Sequence[WorkerOnlyFacility],
    cap: int = 25,
) -> None:
    """The inventory of the module's records plus these fugitive-only facilities."""

    def listing(cas: str, state: str | None = None, city: str | None = None):  # noqa: ANN202
        view, every = rank_and_cap(list(RECORDS), 2, state, city)
        return with_worker_only(view, workers, cap, state, city), every

    monkeypatch.setattr(facilities, "inventory_listing", listing)


WORKERS = [worker_only_facility("WORK_A", 5.0), worker_only_facility("WORK_B", 80.0)]


def test_a_worker_only_facility_has_a_worker_result_and_no_community_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _with_workers(monkeypatch, WORKERS)
    view, artifact = _run()
    found = {w["facility"]["frs_id"]: w for w in artifact["worker_only"]}
    assert set(found) == {"WORK_A", "WORK_B"}
    for item in found.values():
        assert item["community_reason"] == "the facility reports no stack release"
        assert item["occupational_exposure"]["fugitive_release_kg_per_year"] is not None
        assert item["operational_profile"]["schedule_source"]
        assert "exposure" not in item and "population" not in item
    assert "WORK_A" not in _ids(view["facilities"]) and view["worker_only_count"] == 2


def test_screening_counts_are_unchanged_by_worker_only_facilities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plain, plain_artifact = _run()
    _with_workers(monkeypatch, WORKERS)
    view, artifact = _run()
    for key in (
        "facilities_found",
        "assessed",
        "screening",
        "stack_tiers",
        "worst_case_only_count",
    ):
        assert view[key] == plain[key]  # type: ignore[literal-required]
    assert _ids(view["facilities"]) == _ids(plain["facilities"])
    assert artifact["screened_out"] == plain_artifact["screened_out"]
    assert [a["record"]["frs_id"] for a in artifact["assessed"]] == [
        a["record"]["frs_id"] for a in plain_artifact["assessed"]
    ]
    assert plain["worker_only_count"] == 0 and plain["worker_only_highest"] is None


def test_a_worker_only_facility_triggers_no_stack_weather_or_population_request(
    monkeypatch: pytest.MonkeyPatch,
    _offline: FakeSteps,
) -> None:
    _run()
    without = list(_offline.calls)
    _offline.calls.clear()
    _with_workers(monkeypatch, WORKERS)
    _run()
    # Facilities run concurrently, so the calls are compared as a multiset, not in order.
    assert sorted(map(repr, _offline.calls)) == sorted(map(repr, without))
    assert not any("WORK" in repr(call) for call in _offline.calls)


def test_the_model_is_told_how_many_and_which_has_the_highest_worker_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _with_workers(monkeypatch, WORKERS, cap=1)  # the larger release is kept; one is left out
    view, _ = _run()
    assert view["worker_only_count"] == 1 and view["worker_only_left_out"] == 1
    top = view["worker_only_highest"]
    assert top is not None and top["frs_id"] == "WORK_B"
    assert view["note"] is not None
    assert "1 facility reports only a fugitive air release" in view["note"]
    assert "WORK_B" in view["note"] and "WORK_A" not in view["note"]
    assert "1 more were left out" in view["note"]


def test_the_tool_description_tells_the_model_about_worker_only_facilities() -> None:
    text = " ".join(assess_facilities.description.split())
    for phrase in (
        "worker-only",
        "no community result",
        "worker_only_count",
        "worker_only_highest",
    ):
        assert phrase in text


def test_asking_for_a_worker_only_facility_by_id_gives_its_worker_result_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _with_workers(monkeypatch, WORKERS)
    view, artifact = _run(["WORK_B"])
    assert [w["facility"]["frs_id"] for w in artifact["worker_only"]] == ["WORK_B"]
    assert view["not_assessed"] == [] and view["assessed"] == 0
    assert view["worker_only_left_out"] == 0


def test_asking_for_a_stack_facility_by_id_leaves_the_worker_only_ones_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _with_workers(monkeypatch, WORKERS)
    view, artifact = _run(["MID"])
    assert artifact["worker_only"] == [] and view["worker_only_count"] == 0
    assert _ids(view["facilities"]) == ["MID"]


def test_an_unknown_id_is_still_not_assessed_when_worker_only_facilities_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _with_workers(monkeypatch, WORKERS)
    view, _ = _run(["NOPE"])
    assert _ids(view["not_assessed"]) == ["NOPE"]


def test_a_chemical_with_only_fugitive_releases_is_assessed_for_workers_not_its_categories(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    asked = _member_setup(monkeypatch, tmp_path, own=[], by_code={"N084": [record("CAT")]})

    def listing(cas: str, state: str | None = None, city: str | None = None):  # noqa: ANN202
        asked.append(cas)
        view, every = rank_and_cap([], 25, state, city)
        return with_worker_only(view, WORKERS, 25, state, city), every

    monkeypatch.setattr(facilities, "inventory_listing", listing)
    asked.clear()
    view, artifact = run_assessment(
        MEMBER,
        None,
        (None, None),
        None,
        None,
        facilities.default_steps(),
    )
    assert asked == [MEMBER]
    assert len(artifact["worker_only"]) == 2 and view["facilities_found"] == 0


def test_category_facilities_with_a_fugitive_release_only_are_merged_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _member_setup(monkeypatch, tmp_path, own=[], by_code={})

    def listing(cas: str, state: str | None = None, city: str | None = None):  # noqa: ANN202
        stack = [record("PLANT_A")] if cas == "N084" else []
        only = [worker_only_facility("PLANT_A", 9.0), worker_only_facility("SOLO", 4.0)]
        only = only if cas != MEMBER else []
        view, every = rank_and_cap(stack, 25, state, city)
        return with_worker_only(view, only, 25, state, city), every

    monkeypatch.setattr(facilities, "inventory_listing", listing)
    found = facilities.category_records(MEMBER, (None, None))
    assert [r["frs_id"] for r in found.records] == ["PLANT_A"]
    assert [w["frs_id"] for w in found.worker_only] == ["SOLO"]  # PLANT_A is a stack source
