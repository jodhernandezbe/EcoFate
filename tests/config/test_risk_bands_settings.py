"""Tests for the ``[risk_bands]`` settings loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from config.risk_bands import get_risk_bands, load_risk_bands

TEXT = """
[risk_bands]
hq_lower = 0.1
hq_upper = 1.0
cancer_risk_lower = 1e-6
cancer_risk_upper = 1e-4
oel_ratio_lower = 0.1
oel_ratio_upper = 1.0
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "settings.toml"
    path.write_text(text)
    return path


def test_loads_values(tmp_path: Path) -> None:
    bands = load_risk_bands(_write(tmp_path, TEXT))
    assert (bands.hq_lower, bands.hq_upper) == (0.1, 1.0)
    assert (bands.cancer_risk_lower, bands.cancer_risk_upper) == (1e-6, 1e-4)
    assert (bands.oel_ratio_lower, bands.oel_ratio_upper) == (0.1, 1.0)


@pytest.mark.parametrize(
    ("old", "new", "key"),
    [
        ("hq_lower = 0.1", "hq_lower = 2.0", "hq_lower"),
        ("cancer_risk_upper = 1e-4", "cancer_risk_upper = 1e-6", "cancer_risk_lower"),
        ("oel_ratio_lower = 0.1", "oel_ratio_lower = 1.0", "oel_ratio_lower"),
        ("hq_upper = 1.0", "hq_upper = 0", "hq_upper"),
        ("hq_lower = 0.1", "hq_lower = -0.1", "hq_lower"),
        ("oel_ratio_upper = 1.0", "oel_ratio_upper = true", "oel_ratio_upper"),
        ("cancer_risk_lower = 1e-6", 'cancer_risk_lower = "low"', "cancer_risk_lower"),
        ("hq_lower = 0.1\n", "", "hq_lower"),
    ],
)
def test_invalid_values_name_the_key(tmp_path: Path, old: str, new: str, key: str) -> None:
    with pytest.raises(ValueError, match=key):
        load_risk_bands(_write(tmp_path, TEXT.replace(old, new, 1)))


def test_a_missing_section_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="risk_bands"):
        load_risk_bands(_write(tmp_path, "[other]\nx = 1\n"))


def test_default_file_loads() -> None:
    assert get_risk_bands().hq_upper == 1.0
