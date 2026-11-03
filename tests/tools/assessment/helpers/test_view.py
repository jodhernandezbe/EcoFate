"""Tests for what the model is told about a batch assessment."""

from __future__ import annotations

from dataclasses import replace

from tests.tools.assessment.factories import (
    PEOPLE,
    SCREENING,
    SETTINGS,
    TOXICITY,
    WEATHER,
    FakeSteps,
    record,
    stack,
)
from tools.assessment.helpers.chain import Refined, assess_all, refine_one, worst_case_only
from tools.assessment.helpers.tiers import split
from tools.assessment.helpers.view import MAX_NOTES, Findings, assessment_view, summarize
from tools.schemas import FacilityAssessment, NotAssessed


def _refined(frs_id: str, stacks: int, rate: float = 1.0) -> Refined:
    fake = FakeSteps(nei_stacks={frs_id: [stack(10 - i) for i in range(stacks)]})
    rec = record(frs_id, eis_ids=["1"], emission_rate=rate)
    return refine_one(rec, None, TOXICITY, fake.steps(), SETTINGS)


def _full(frs_id: str, stacks: int) -> FacilityAssessment:
    return assess_all([_refined(frs_id, stacks)], TOXICITY, None, FakeSteps().steps(), SETTINGS)[0]


def _findings(**over: object) -> Findings:
    base = Findings(
        cas="1-1-1",
        toxicity=(TOXICITY, "CompTox"),
        found=10,
        full=[],
        worst_only=[],
        screened_out=[],
        thresholds=SCREENING,
        possible=True,
        skipped=[],
        warnings=[],
    )
    return replace(base, **over)  # type: ignore[arg-type]


def test_a_facility_summary_carries_provenance_and_ranges() -> None:
    summary = summarize(_full("F1", 2))
    assert (summary["frs_id"], summary["stack_tier"], summary["stacks_evaluated"]) == (
        "F1",
        "NEI",
        2,
    )
    assert summary["hq_worst"] is not None and summary["hq_representative"] is not None
    assert summary["cancer_risk_worst"] is None
    assert (summary["weather_source"], summary["residents"]) == (
        WEATHER["source"],
        PEOPLE["total_population"],
    )
    assert "synthetic facility note" in summary["notes"]


def test_notes_are_deduplicated_and_capped() -> None:
    item = _full("F1", 1)
    item["notes"] = [f"note {i}" for i in range(MAX_NOTES + 3)] + ["note 0"]
    notes = summarize(item)["notes"]
    assert len(notes) == MAX_NOTES + 1 and notes[-1].startswith("(+") and notes.count("note 0") == 1


def test_the_view_ranks_by_worst_hq_and_counts_tiers_and_gaps() -> None:
    skipped = [NotAssessed(frs_id="X", reason="not in the inventory")]
    view = assessment_view(
        _findings(full=[_full("LOW", 1), _full("HIGH", 3)], skipped=skipped),
        4,
        2,
    )
    assert [f["frs_id"] for f in view["facilities"]] == ["HIGH", "LOW"]
    assert (view["assessed"], view["facilities_found"], view["stack_tiers"]) == (2, 10, {"NEI": 2})
    assert view["not_assessed"] == skipped and view["toxicity_source"] == "CompTox"


def test_screening_counts_the_closest_call_and_the_note() -> None:
    items = [_refined("TALL", 1, rate=0.5), _refined("A", 1, rate=5.0), _refined("B", 1, rate=4.0)]
    tiers = split(items, True, replace(SETTINGS, max_facilities=1))
    worst = [worst_case_only(i, None) for i in tiers.worst_only]
    view = assessment_view(
        _findings(full=[_full("A", 1)], worst_only=worst, screened_out=tiers.screened_out),
        4,
        2,
    )
    screening = view["screening"]
    assert screening is not None and screening["possible"]
    assert (screening["hq_threshold"], screening["cancer_risk_threshold"]) == (0.1, 1e-6)
    assert (screening["screened_out_at_bound"], screening["screened_out_with_own_stacks"]) == (0, 1)
    assert [o["frs_id"] for o in screening["closest_screened_out"]] == ["TALL"]
    assert screening["closest_screened_out"][0]["stage"] == "own stacks"
    assert view["worst_case_only_count"] == 1 and view["worst_case_only"][0]["frs_id"] == "B"
    assert "stacks" not in view["worst_case_only"][0]
    assert view["note"] is not None and view["note"].startswith("All 10 facilities were screened")
    assert "SCREEN3" in view["note"] and "AirToxScreen" in view["note"]  # the screen's sources


def test_the_worst_case_list_is_capped_highest_first_and_counted() -> None:
    worst = [worst_case_only(_refined(f"W{i}", 1, rate=1.0 + i), None) for i in range(6)]
    view = assessment_view(_findings(worst_only=worst), 4, 2)
    assert view["worst_case_only_count"] == 6
    assert [w["frs_id"] for w in view["worst_case_only"]] == ["W5", "W4", "W3", "W2"]


def test_facilities_asked_for_by_id_have_no_screening_and_no_note() -> None:
    view = assessment_view(_findings(thresholds=None), 4, 2)
    assert view["screening"] is None and view["note"] is None


def test_without_benchmarks_the_note_says_nothing_could_be_screened() -> None:
    view = assessment_view(_findings(possible=False), 4, 2)
    assert view["note"] is not None and "could be screened out" in view["note"]
    assert view["screening"] is not None and not view["screening"]["possible"]


def test_the_closest_screened_out_facilities_are_listed_closest_first_and_capped() -> None:
    items = [_refined(f"S{i}", 1, rate=0.01 * (i + 1)) for i in range(4)]  # all below HQ 0.1
    tiers = split(items, True, SETTINGS)
    view = assessment_view(_findings(screened_out=tiers.screened_out), 4, 2)
    screening = view["screening"]
    assert screening is not None and screening["screened_out_with_own_stacks"] == 4
    listed = screening["closest_screened_out"]
    assert [o["frs_id"] for o in listed] == ["S3", "S2"]  # the largest rates, two listed
    assert listed[0]["emission_rate"] == 0.04 and listed[0]["hq"] is not None
