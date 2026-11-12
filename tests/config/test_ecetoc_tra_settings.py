"""Tests for the ``[ecetoc_tra]`` settings loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from config.ecetoc_tra import load_ecetoc_tra_settings

TEXT = """
[ecetoc_tra]
table_path = "data/x.csv"
very_low_below_pa = 0.01
low_up_to_pa = 500.0
moderate_up_to_pa = 10000.0
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "settings.toml"
    path.write_text(text)
    return path


def test_loads_values(tmp_path: Path) -> None:
    s = load_ecetoc_tra_settings(_write(tmp_path, TEXT))
    assert s.table_path.is_absolute() and s.table_path.name == "x.csv"
    assert (s.very_low_below_pa, s.low_up_to_pa, s.moderate_up_to_pa) == (0.01, 500.0, 10000.0)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("low_up_to_pa = 500.0", "low_up_to_pa = 0.001"),
        ("low_up_to_pa = 500.0", "low_up_to_pa = 10000.0"),
        ("very_low_below_pa = 0.01", "very_low_below_pa = 0"),
        ("moderate_up_to_pa = 10000.0", "moderate_up_to_pa = true"),
        ('table_path = "data/x.csv"', "table_path = 3"),
    ],
)
def test_invalid_values_raise(tmp_path: Path, old: str, new: str) -> None:
    with pytest.raises(ValueError, match="ecetoc_tra"):
        load_ecetoc_tra_settings(_write(tmp_path, TEXT.replace(old, new, 1)))


def test_default_file_loads_and_table_exists() -> None:
    assert load_ecetoc_tra_settings().table_path.is_file()
