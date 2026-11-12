"""Tests for the ``[osha_cehd]`` settings loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from config.osha_cehd import get_osha_cehd_settings, load_osha_cehd_settings

TEXT = """
[osha_cehd]
url_pattern = "https://example.test/{year}.zip"
crosswalk_url_pattern = "https://example.test/list?page={page}"
user_agent = "agent"
timeout_s = 30
years = [2020, 2021]
naics_prefix_lengths = [6, 4, 3]
min_values = 5
molar_volume_l_per_mol = 24.45
summary_path = "data/s.csv"
crosswalk_path = "data/c.csv"
nondetect_qualifiers = ["ND"]
blank_marker = "BLK"
[osha_cehd.units]
M = "mg/m^3"
P = "ppm"
"""


def _load(tmp_path: Path, text: str):  # noqa: ANN202
    path = tmp_path / "settings.toml"
    path.write_text(text, encoding="utf-8")
    return load_osha_cehd_settings(path)


def test_loads_values(tmp_path: Path) -> None:
    settings = _load(tmp_path, TEXT)
    assert settings.years == (2020, 2021)
    assert settings.naics_prefix_lengths == (6, 4, 3)
    assert settings.units["P"] == "ppm"
    assert settings.summary_path.name == "s.csv"


def test_real_file_loads() -> None:
    settings = get_osha_cehd_settings()
    assert len(settings.years) == 10
    assert settings.min_values == 5


@pytest.mark.parametrize(
    ("old", "new", "key"),
    [
        ('url_pattern = "https://example.test/{year}.zip"', 'url_pattern = "x"', "url_pattern"),
        ("years = [2020, 2021]", "years = [2021, 2020]", "years"),
        ("years = [2020, 2021]", "years = []", "years"),
        ("years = [2020, 2021]", "years = [true]", "years"),
        ("[6, 4, 3]", "[3, 4, 6]", "naics_prefix_lengths"),
        ("[6, 4, 3]", "[7]", "naics_prefix_lengths"),
        ("min_values = 5", "min_values = 0", "min_values"),
        ("min_values = 5", "min_values = true", "min_values"),
        ("molar_volume_l_per_mol = 24.45", "molar_volume_l_per_mol = 0", "molar_volume"),
        ("timeout_s = 30", "timeout_s = -1", "timeout_s"),
        ('P = "ppm"', 'P = "percent"', "units"),
        ('nondetect_qualifiers = ["ND"]', "nondetect_qualifiers = []", "nondetect_qualifiers"),
    ],
)
def test_rejects_invalid(tmp_path: Path, old: str, new: str, key: str) -> None:
    with pytest.raises(ValueError, match=key):
        _load(tmp_path, TEXT.replace(old, new))


def test_missing_section(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="osha_cehd"):
        _load(tmp_path, "[other]\nx = 1\n")
