"""Tests for the choice of a facility's worker activities (synthetic crosswalk rows)."""

from __future__ import annotations

from config.occupational import get_occupational_settings
from tools.assessment.helpers.activities.crosswalk import Crosswalk, ScenarioRow
from tools.assessment.helpers.activities.select import NO_ACTIVITY, NO_SECTOR, select_activities

SETTINGS = get_occupational_settings()
MANUFACTURING = SETTINGS.stage_activities["Manufacturing"]
PROCESSING = SETTINGS.stage_activities["Processing"]


def _row(stage: str, title: str, *activities: str, sector: str = "IS99") -> ScenarioRow:
    return ScenarioRow(1, sector, stage, title, "published ESD", activities, "p1", "A source")


def _select(stages: list[str], sector: str | None, *rows: ScenarioRow):  # noqa: ANN202
    return select_activities(stages, sector, SETTINGS, Crosswalk(rows))


def test_a_sector_with_a_scenario_adds_its_activities_to_the_generic_operation() -> None:
    chosen = _select(
        ["Processing"],
        "IS99",
        _row("Processing", "Synthetic ESD", "rail_car_unloading"),
    )
    assert chosen.activities == (*PROCESSING, "rail_car_unloading")
    (route,) = chosen.routes
    assert route.generic_activities == PROCESSING
    assert [r.scenario for r in route.scenarios] == ["Synthetic ESD"]
    assert route.note is None and chosen.reason is None


def test_a_row_never_removes_a_generic_activity() -> None:
    chosen = _select(["Processing"], "IS99", _row("Processing", "Narrow ESD", "drum_unloading"))
    assert set(PROCESSING) <= set(chosen.activities)
    assert chosen.activities == PROCESSING


def test_a_sector_without_a_row_for_the_stage_uses_the_generic_operation_only() -> None:
    other_stage = _row("Industrial use", "Elsewhere", "rail_car_unloading")
    other_sector = _row("Processing", "Elsewhere", "rail_car_unloading", sector="IS1")
    chosen = _select(["Processing"], "IS99", other_stage, other_sector)
    assert chosen.activities == PROCESSING
    (route,) = chosen.routes
    assert route.scenarios == () and route.note is not None and "IS99" in route.note


def test_no_sector_uses_the_generic_operation_and_says_so() -> None:
    chosen = _select(
        ["Manufacturing"],
        None,
        _row("Manufacturing", "Never used", "rail_car_unloading"),
    )
    assert chosen.activities == MANUFACTURING
    assert NO_SECTOR in chosen.notes


def test_several_stages_share_an_activity_once_and_name_both_routes() -> None:
    chosen = _select(["Manufacturing", "Processing"], None)
    assert len(chosen.activities) == len(set(chosen.activities))
    assert set(chosen.activities) == set(MANUFACTURING) | set(PROCESSING)
    assert [r.stage for r in chosen.routes] == ["Manufacturing", "Processing"]
    assert "liquid_sampling" in MANUFACTURING and "liquid_sampling" in PROCESSING


def test_two_rows_of_the_sector_and_stage_both_add_their_activities() -> None:
    rows = (
        _row("Processing", "First", "rail_car_unloading"),
        _row("Processing", "Second", "rail_car_loading"),
    )
    chosen = _select(["Processing"], "IS99", *rows)
    assert {"rail_car_unloading", "rail_car_loading"} <= set(chosen.activities)
    assert [r.scenario for r in chosen.routes[0].scenarios] == ["First", "Second"]


def test_no_flags_means_no_activity_and_the_reason() -> None:
    chosen = _select([], "IS99", _row("Processing", "Unused", "rail_car_unloading"))
    assert chosen.activities == () and chosen.routes == ()
    assert chosen.reason == NO_ACTIVITY == "the facility reported no activity"


def test_a_stage_without_a_generic_operation_is_skipped_with_a_note() -> None:
    chosen = _select(["Commercial use", "Manufacturing"], None)
    assert chosen.activities == MANUFACTURING
    assert any("Commercial use" in note for note in chosen.notes)


def test_only_stages_without_a_generic_operation_give_no_activity() -> None:
    chosen = _select(["Disposal"], "IS99")
    assert chosen.activities == () and chosen.reason is not None
