"""Tests for the Envirofacts and FRS settings loaders."""

from __future__ import annotations

from pathlib import Path

import pytest

from config.efservice import (
    EfserviceSettings,
    FrsSettings,
    load_efservice_settings,
    load_frs_settings,
)

TEXT = """
[efservice]
base_url = "https://ef.test/api/"
delay_seconds = 0
timeout_seconds = 4
max_retries = 1
backoff_seconds = 0.5

[frs]
eis_path = "/f/{frs_id}/EIS/JSON"
program = " EIS "
registry_field = "reg"
program_field = "prog"
eis_id_field = "sys"
"""


def _write(tmp_path: Path, text: str = TEXT) -> Path:
    path = tmp_path / "settings.toml"
    path.write_text(text)
    return path


def _ef(tmp_path: Path, text: str = TEXT) -> EfserviceSettings:
    return load_efservice_settings(_write(tmp_path, text))


def _frs(tmp_path: Path, text: str = TEXT) -> FrsSettings:
    return load_frs_settings(_write(tmp_path, text))


def test_efservice_explicit_values(tmp_path: Path) -> None:
    settings = _ef(tmp_path)
    assert settings.url("/x") == "https://ef.test/api/x"
    assert (settings.delay_seconds, settings.timeout_seconds) == (0, 4)
    assert (settings.max_retries, settings.backoff_seconds) == (1, 0.5)


def test_efservice_default_file_loads() -> None:
    settings = load_efservice_settings()
    assert settings.url("/x").endswith("/efservice/x")
    assert settings.timeout_seconds > 0


@pytest.mark.parametrize(
    ("line", "bad", "key"),
    [
        ("max_retries = 1", "max_retries = -1", "max_retries"),
        ("max_retries = 1", "max_retries = 1.5", "max_retries"),
        ("delay_seconds = 0", "delay_seconds = -1", "delay_seconds"),
        ("delay_seconds = 0", "delay_seconds = true", "delay_seconds"),
        ("timeout_seconds = 4", "timeout_seconds = 0", "timeout_seconds"),
        ("backoff_seconds = 0.5", "backoff_seconds = -0.1", "backoff_seconds"),
        ("backoff_seconds = 0.5", 'backoff_seconds = "x"', "backoff_seconds"),
        ('base_url = "https://ef.test/api/"', 'base_url = ""', "base_url"),
    ],
)
def test_efservice_invalid_values_name_the_key(
    tmp_path: Path,
    line: str,
    bad: str,
    key: str,
) -> None:
    with pytest.raises(ValueError, match=f"efservice.{key}"):
        _ef(tmp_path, TEXT.replace(line, bad))


def test_efservice_section_and_file_missing(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="efservice section"):
        _ef(tmp_path, "[other]\nx = 1\n")
    with pytest.raises(FileNotFoundError):
        load_efservice_settings(tmp_path / "nope.toml")


def test_frs_explicit_values(tmp_path: Path) -> None:
    settings = _frs(tmp_path)
    assert settings.eis_path == "/f/{frs_id}/EIS/JSON"
    assert settings.program == "EIS"
    assert (settings.registry_field, settings.program_field, settings.eis_id_field) == (
        "reg",
        "prog",
        "sys",
    )


def test_frs_default_file_loads() -> None:
    settings = load_frs_settings()
    assert "{frs_id}" in settings.eis_path
    assert settings.program == "EIS"
    assert settings.eis_id_field == "pgm_sys_id"


def test_frs_path_needs_the_placeholder(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="frs.eis_path"):
        _frs(tmp_path, TEXT.replace("{frs_id}", "x"))


@pytest.mark.parametrize("key", ["program", "registry_field", "program_field", "eis_id_field"])
def test_frs_each_key_is_required(tmp_path: Path, key: str) -> None:
    lines = [line for line in TEXT.splitlines() if not line.startswith(f"{key} =")]
    with pytest.raises(ValueError, match=f"frs.{key}"):
        _frs(tmp_path, "\n".join(lines))


def test_frs_section_missing(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="frs section"):
        _frs(tmp_path, TEXT.split("[frs]")[0])
