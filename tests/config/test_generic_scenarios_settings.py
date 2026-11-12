"""Tests for the ``[generic_scenarios]`` settings loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from config.generic_scenarios import get_generic_scenario_settings, load_generic_scenario_settings
from config.parsing import PROJECT_ROOT


def _load(tmp_path: Path, text: str):  # noqa: ANN202
    path = tmp_path / "settings.toml"
    path.write_text(text, encoding="utf-8")
    return load_generic_scenario_settings(path)


def test_a_relative_path_is_resolved_against_the_project(tmp_path: Path) -> None:
    settings = _load(tmp_path, '[generic_scenarios]\ncrosswalk_path = "data/x.csv"\n')
    assert settings.crosswalk_path == PROJECT_ROOT / "data" / "x.csv"


def test_a_missing_section_or_key_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="generic_scenarios"):
        _load(tmp_path, "[other]\nx = 1\n")
    with pytest.raises(ValueError, match="crosswalk_path"):
        _load(tmp_path, "[generic_scenarios]\n")


def test_the_bundled_file_is_configured() -> None:
    assert get_generic_scenario_settings().crosswalk_path.name == "cdr_sector_generic_scenarios.csv"
