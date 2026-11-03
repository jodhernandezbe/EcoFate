"""Tests for the ``[assessment]`` settings loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from config.assessment import AssessmentSettings, ScreeningSettings, load_assessment_settings
from config.loader import get_tri_settings

TEXT = """
[assessment]
max_facilities = 7
max_workers = 2
scc_min_score = 0.6
max_scc_stacks = 2
inventory_cache_seconds = 30
max_refined = 40
max_worst_case_listed = 9
max_screened_out_listed = 3
weather_cell_deg = 0.5

[assessment.screening]
hq = 0.2
cancer_risk = 1e-5
ambient_temperatures_k = [260, 300.5]
"""


def _load(tmp_path: Path, text: str = TEXT) -> AssessmentSettings:
    path = tmp_path / "settings.toml"
    path.write_text(text, encoding="utf-8")
    return load_assessment_settings(path)


def test_explicit_values(tmp_path: Path) -> None:
    assert _load(tmp_path) == AssessmentSettings(
        max_facilities=7,
        max_refined=40,
        max_workers=2,
        scc_min_score=0.6,
        max_scc_stacks=2,
        inventory_cache_seconds=30.0,
        max_worst_case_listed=9,
        max_screened_out_listed=3,
        weather_cell_deg=0.5,
        screening=ScreeningSettings(
            hq=0.2,
            cancer_risk=1e-5,
            ambient_temperatures_k=(260.0, 300.5),
        ),
    )


def test_default_file_loads_with_the_screening_thresholds() -> None:
    s = load_assessment_settings()
    assert s.max_facilities == get_tri_settings().max_listed
    assert 0 < s.scc_min_score <= 1 and s.max_workers >= 1 and s.inventory_cache_seconds >= 0
    assert (s.screening.hq, s.screening.cancer_risk) == (0.1, 1e-6)
    assert s.max_refined >= s.max_facilities and s.weather_cell_deg == 0.25
    assert s.max_refined == 5000  # a safety bound above any chemical, not a selection


def test_a_cache_of_zero_seconds_is_allowed(tmp_path: Path) -> None:
    text = TEXT.replace("inventory_cache_seconds = 30", "inventory_cache_seconds = 0")
    assert _load(tmp_path, text).inventory_cache_seconds == 0


@pytest.mark.parametrize(
    ("old", "new", "key"),
    [
        ("max_facilities = 7", "max_facilities = 0", "max_facilities"),
        ("max_workers = 2", "max_workers = true", "max_workers"),
        ("max_workers = 2", "", "max_workers"),
        ("scc_min_score = 0.6", "scc_min_score = 0", "scc_min_score"),
        ("scc_min_score = 0.6", "scc_min_score = 1.5", "scc_min_score"),
        ("scc_min_score = 0.6", 'scc_min_score = "high"', "scc_min_score"),
        ("max_scc_stacks = 2", "max_scc_stacks = 0", "max_scc_stacks"),
        ("inventory_cache_seconds = 30", "inventory_cache_seconds = -1", "inventory_cache_seconds"),
        ("max_refined = 40", "max_refined = 0", "max_refined"),
        ("max_worst_case_listed = 9", "", "max_worst_case_listed"),
        ("max_screened_out_listed = 3", "max_screened_out_listed = 0", "max_screened_out_listed"),
        ("weather_cell_deg = 0.5", "weather_cell_deg = 0", "weather_cell_deg"),
        ("hq = 0.2", "hq = 0", "hq"),
        ("hq = 0.2", "hq = true", "hq"),
        ("cancer_risk = 1e-5", "cancer_risk = -1e-6", "cancer_risk"),
        (
            "ambient_temperatures_k = [260, 300.5]",
            "ambient_temperatures_k = []",
            "ambient_temperatures_k",
        ),
        (
            "ambient_temperatures_k = [260, 300.5]",
            "ambient_temperatures_k = [260, 0]",
            "ambient_temperatures_k",
        ),
        (
            "ambient_temperatures_k = [260, 300.5]",
            'ambient_temperatures_k = "hot"',
            "ambient_temperatures_k",
        ),
        ("[assessment.screening]", "[assessment.other]", "screening"),
    ],
)
def test_invalid_entries_name_the_key(tmp_path: Path, old: str, new: str, key: str) -> None:
    with pytest.raises(ValueError, match=key):
        _load(tmp_path, TEXT.replace(old, new, 1))


def test_section_missing(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="assessment section"):
        _load(tmp_path, "[other]\nx = 1\n")
