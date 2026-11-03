"""Tests for which facilities go on at each tier."""

from __future__ import annotations

from dataclasses import replace

from tests.tools.assessment.factories import SETTINGS, TOXICITY, FakeSteps, record, stack
from tools.assessment.helpers.chain import Refined, refine_one
from tools.assessment.helpers.screening import unit_bound
from tools.assessment.helpers.tiers import screen, split

UNIT = unit_bound(FakeSteps().steps(), TOXICITY, SETTINGS.screening.ambient_temperatures_k)
# The fake unit-rate HQ is 1/3, so a bound reaches HQ 0.1 from 0.3 g/s.


def test_a_facility_below_both_thresholds_at_the_bound_is_screened_out_with_it() -> None:
    result = screen(
        [record("SMALL", emission_rate=0.2), record("BIG", emission_rate=3.0)],
        UNIT,
        SETTINGS,
    )
    assert [r["frs_id"] for r, _ in result.candidates] == ["BIG"]
    (out,) = result.screened_out
    assert out["record"]["frs_id"] == "SMALL" and out["stage"] == "bound"
    assert out["stack_tier"] == "AirToxScreen global default" and out["stacks"] == []
    assert out["hq"] is not None and out["hq"] < 0.1
    assert "below HQ 0.1 and cancer risk 1e-06" in out["reason"]
    assert "AirToxScreen global default stack" in out["reason"] and "SCREEN3" in out["reason"]


def test_no_candidate_is_dropped_below_the_safety_bound_and_they_go_largest_first() -> None:
    records = [record(f"F{i}", emission_rate=1.0 + i) for i in range(3)]
    result = screen(records, UNIT, replace(SETTINGS, max_refined=3))
    assert [r["frs_id"] for r, _ in result.candidates] == ["F2", "F1", "F0"]
    assert result.over == []


def test_beyond_the_safety_bound_the_rest_is_returned_as_not_assessed() -> None:
    records = [record(f"F{i}", emission_rate=1.0 + i) for i in range(3)]
    result = screen(records, UNIT, replace(SETTINGS, max_refined=2))
    assert [r["frs_id"] for r, _ in result.candidates] == ["F2", "F1"]
    assert [o["frs_id"] for o in result.over] == ["F0"]
    assert "more than 2 facilities reach a threshold" in result.over[0]["reason"]


def test_without_a_unit_bound_nothing_is_screened_out() -> None:
    result = screen([record("TINY", emission_rate=1e-9)], None, SETTINGS)
    assert [r["frs_id"] for r, _ in result.candidates] == ["TINY"] and result.screened_out == []
    assert result.candidates[0][1] is None


def _refined(frs_id: str, rate: float, height: float) -> Refined:
    fake = FakeSteps(nei_stacks={frs_id: [stack(height)]})
    rec = record(frs_id, emission_rate=rate, eis_ids=["1"])
    return refine_one(rec, None, TOXICITY, fake.steps(), SETTINGS)


def test_ranked_by_own_stack_risk_not_by_emissions_and_low_risk_screened_out() -> None:
    tall_big = _refined("TALL", 5.0, 100.0)  # HQ 0.05: below 0.1 with its own stack
    short_small = _refined("SHORT", 1.0, 2.0)  # HQ 0.5
    mid = _refined("MID", 3.0, 10.0)  # HQ 0.3
    result = split([tall_big, mid, short_small], True, SETTINGS)
    assert [i.record["frs_id"] for i in result.full] == ["SHORT", "MID"]
    (out,) = result.screened_out
    assert out["record"]["frs_id"] == "TALL" and out["stage"] == "own stacks"
    assert out["stack_tier"] == "NEI" and len(out["stacks"]) == 1
    assert "with its own stacks (NEI)" in out["reason"]


def test_beyond_the_full_cap_facilities_keep_their_worst_case() -> None:
    items = [_refined(f"F{i}", 1.0 + i, 2.0) for i in range(3)]
    result = split(items, True, replace(SETTINGS, max_facilities=1))
    assert [i.record["frs_id"] for i in result.full] == ["F2"]
    assert [i.record["frs_id"] for i in result.worst_only] == ["F1", "F0"]


def test_without_benchmarks_nothing_is_screened_out_at_refinement() -> None:
    items = [_refined("A", 1e-6, 100.0)]
    assert split(items, False, SETTINGS).full == items
