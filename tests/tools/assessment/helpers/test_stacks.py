"""Tests for the stack-source order of the batch assessment: NEI, then PSTK, then the default."""

from __future__ import annotations

from tests.tools.assessment.factories import GLOBAL, SETTINGS, FakeSteps, match, record, stack
from tools.assessment.helpers.stacks import choose_stacks


def test_the_facilitys_own_nei_stacks_come_first() -> None:
    fake = FakeSteps(nei_stacks={"F1": [stack(10), stack(20)]})
    choice = choose_stacks(record(eis_ids=["123"]), fake.steps(), SETTINGS)
    assert choice.tier == "NEI" and [s["stack_height"] for s in choice.stacks] == [10, 20]
    assert ("nei", ("F1", ("123",))) in fake.calls
    assert not any(name in {"scc", "pstk"} for name, _ in fake.calls)


def test_without_eis_ids_the_industry_gives_pstk_stacks_and_the_reason_is_noted() -> None:
    fake = FakeSteps(
        matches=[match("1", 0.9), match("2", 0.8), match("3", 0.7)],
        pstk_rows={
            "1": stack(15, "PSTK", "1"),
            "2": stack(25, "PSTK", "2"),
            "3": stack(35, "PSTK", "3"),
        },
    )
    rec = record(naics_title="Synthetic Milling", eis_note="no EIS registration for F1")
    choice = choose_stacks(rec, fake.steps(), SETTINGS)
    assert choice.tier == "PSTK"
    assert [s["scc"] for s in choice.stacks] == ["1", "2"]  # capped at max_scc_stacks
    assert [m["scc"] for m in choice.scc_matches] == ["1", "2"]
    assert choice.notes[0] == "no EIS registration for F1"
    assert not any(name == "nei" for name, _ in fake.calls)


def test_matches_below_the_score_floor_or_without_pstk_rows_are_skipped_and_duplicates_merged() -> (
    None
):
    fake = FakeSteps(
        matches=[match("1", 0.9), match("2", 0.8), match("3", 0.7), match("4", 0.2)],
        pstk_rows={
            "2": stack(15, "PSTK", "2"),
            "3": stack(15, "PSTK", "3"),
            "4": stack(99, "PSTK", "4"),
        },
    )
    choice = choose_stacks(record(naics_title="Synthetic Milling"), fake.steps(), SETTINGS)
    assert [s["scc"] for s in choice.stacks] == [
        "2",
    ]  # 1 has no PSTK row, 3 repeats 2, 4 is too weak


def test_a_missing_title_is_looked_up_by_control_number() -> None:
    fake = FakeSteps(
        titles={"DOC1": "Synthetic Milling"},
        matches=[match("1", 0.9)],
        pstk_rows={"1": stack(15, "PSTK", "1")},
    )
    choice = choose_stacks(record(doc_ctrl_num="DOC1"), fake.steps(), SETTINGS)
    assert choice.tier == "PSTK" and choice.industry is not None
    assert ("scc", "Synthetic Milling") in fake.calls


def test_the_global_default_is_last_and_never_missing() -> None:
    weak = FakeSteps(matches=[match("1", 0.3)])
    choice = choose_stacks(record(naics_title="Synthetic Milling"), weak.steps(), SETTINGS)
    assert choice.tier == "AirToxScreen global default" and choice.stacks == [GLOBAL]
    assert any(
        "closely enough (best similarity 0.30, at least 0.50 needed)" in n for n in choice.notes
    )
    assert "generic" in choice.notes[-1]


def test_an_unknown_industry_goes_to_the_default_without_a_search() -> None:
    fake = FakeSteps()
    choice = choose_stacks(record(), fake.steps(), SETTINGS)
    assert choice.tier == "AirToxScreen global default"
    assert any("industry is unknown" in n for n in choice.notes)
    assert not any(name == "scc" for name, _ in fake.calls)


def test_eis_ids_without_nei_rows_fall_back_and_say_so() -> None:
    fake = FakeSteps(matches=[match("1", 0.9)], pstk_rows={"1": stack(15, "PSTK", "1")})
    choice = choose_stacks(
        record(eis_ids=["123"], naics_title="Synthetic Milling"),
        fake.steps(),
        SETTINGS,
    )
    assert choice.tier == "PSTK"
    assert choice.notes[0] == "the NEI has no usable stack for EIS ID 123"


def test_no_match_and_all_matches_without_rows_are_told_apart() -> None:
    none = choose_stacks(record(naics_title="T"), FakeSteps().steps(), SETTINGS)
    assert "no SCC process matched the industry 'T'" in none.notes
    rowless = choose_stacks(
        record(naics_title="T"),
        FakeSteps(matches=[match("1", 0.9)]).steps(),
        SETTINGS,
    )
    assert "none of the 1 SCC processes matching 'T' has a PSTK stack" in rowless.notes
