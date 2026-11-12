"""Tests for the generic scenario crosswalk reader."""

from __future__ import annotations

from pathlib import Path

import pytest

from config.generic_scenarios import get_generic_scenario_settings
from config.occupational import get_occupational_settings
from tools.assessment.helpers.activities.crosswalk import get_crosswalk, read_crosswalk
from tools.assessment.helpers.activities.select import select_activities

HEADER = "is_code,lifecycle_stage,scenario,category,activities,pages,note,source\n"
KNOWN = {"drum_loading", "drum_unloading"}


def _read(tmp_path: Path, *lines: str):  # noqa: ANN202
    path = tmp_path / "crosswalk.csv"
    path.write_text(
        "# a comment\n" + HEADER + "".join(f"{line}\n" for line in lines),
        encoding="utf-8",
    )
    return read_crosswalk(path, KNOWN)


def test_rows_are_found_by_sector_and_stage(tmp_path: Path) -> None:
    crosswalk = _read(
        tmp_path,
        'IS1,Processing,"Title, with comma",published ESD,drum_loading;drum_unloading,p1,,Doc',
        "IS1,Industrial use,Other,draft ESD,drum_loading,p2,,Doc",
    )
    (found,) = crosswalk.rows_for("IS1", "Processing")
    assert found.scenario == "Title, with comma"
    assert found.activities == ("drum_loading", "drum_unloading")
    assert (found.category, found.pages, found.source) == ("published ESD", "p1", "Doc")
    assert crosswalk.rows_for("IS1", "Manufacturing") == ()


def test_an_unknown_activity_names_the_line(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"line 4.*unknown activity 'no_such_activity'"):
        _read(
            tmp_path,
            "IS1,Processing,A,published ESD,drum_loading,p1,,Doc",
            "IS1,Processing,B,published ESD,no_such_activity,p1,,Doc",
        )


def test_a_stage_outside_the_three_names_the_line(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"line 3.*life cycle stage 'Disposal'"):
        _read(tmp_path, "IS1,Disposal,A,published ESD,drum_loading,p1,,Doc")


def test_a_malformed_row_names_the_line(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"line 3.*columns"):
        _read(tmp_path, "IS1,Processing,A")


def test_an_empty_required_field_names_the_line(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"line 3.*scenario is empty"):
        _read(tmp_path, "IS1,Processing,,published ESD,drum_loading,p1,,Doc")


def test_a_missing_column_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text("is_code,activities\nIS1,drum_loading\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing column"):
        read_crosswalk(path, KNOWN)


def test_the_bundled_crosswalk_parses_and_adds_bulk_activities_to_the_generic_operation() -> None:
    crosswalk = get_crosswalk()
    assert get_generic_scenario_settings().crosswalk_path.is_file()
    settings = get_occupational_settings()
    chosen = select_activities(["Processing"], "IS13", settings, crosswalk)
    generic = settings.stage_activities["Processing"]
    assert set(generic) <= set(chosen.activities)
    assert {"rail_car_unloading", "tank_truck_loading"} <= set(chosen.activities)
    assert chosen.routes[0].scenarios and chosen.routes[0].scenarios[0].source
