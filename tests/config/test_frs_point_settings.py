"""Tests for the ``[frs_point]`` settings loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from config.frs_point import load_frs_point_settings

TEXT = """
[frs_point]
base_url = "https://frs.test/svc"
path = "/p/{frs_ids}"
registry_field = " id "
latitude_field = " la "
longitude_field = "lo"
batch_size = 25
"""


def _write(tmp_path: Path, text: str = TEXT) -> Path:
    path = tmp_path / "settings.toml"
    path.write_text(text)
    return path


def test_explicit_values(tmp_path: Path) -> None:
    settings = load_frs_point_settings(_write(tmp_path))
    assert (settings.base_url, settings.path) == ("https://frs.test/svc", "/p/{frs_ids}")
    assert (settings.registry_field, settings.latitude_field) == ("id", "la")
    assert (settings.longitude_field, settings.batch_size) == ("lo", 25)


def test_default_file_loads() -> None:
    settings = load_frs_point_settings()
    assert "{frs_ids}" in settings.path
    assert settings.base_url.startswith("https://")
    assert settings.latitude_field == "latitude"
    assert 1 <= settings.batch_size < 200  # 200 IDs were answered, 400 refused


def test_path_needs_the_placeholder(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="frs_point.path"):
        load_frs_point_settings(_write(tmp_path, TEXT.replace("{frs_ids}", "x")))


@pytest.mark.parametrize(
    "key",
    ["base_url", "path", "registry_field", "latitude_field", "longitude_field", "batch_size"],
)
def test_each_key_is_required(tmp_path: Path, key: str) -> None:
    text = "\n".join(line for line in TEXT.splitlines() if not line.startswith(key))
    with pytest.raises(ValueError, match=key):
        load_frs_point_settings(_write(tmp_path, text))


@pytest.mark.parametrize("bad", ["0", "-1", "1.5", "true"])
def test_the_batch_size_must_be_a_positive_integer(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ValueError, match="batch_size"):
        load_frs_point_settings(
            _write(tmp_path, TEXT.replace("batch_size = 25", f"batch_size = {bad}")),
        )


def test_section_missing(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="frs_point"):
        load_frs_point_settings(_write(tmp_path, "[x]\na = 1\n"))
