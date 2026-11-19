"""Tests for settings profiles: ``settings.<profile>.toml`` laid over the shipped file."""

from __future__ import annotations

from pathlib import Path

import pytest

from config.auth import load_auth_settings
from config.mail import load_mail_settings
from config.parsing import (
    DEFAULT_SETTINGS_PATH,
    PROFILE_ENV_VAR,
    overlay_settings,
    profile_path,
    read_toml,
)
from config.telemetry import load_telemetry_settings
from config.ui import load_ui_settings
from config.worker import load_worker_settings


def test_no_profile_reads_the_shipped_file_alone() -> None:
    assert profile_path({}) is None
    assert profile_path({PROFILE_ENV_VAR: "  "}) is None
    assert read_toml(None, {}) == read_toml(DEFAULT_SETTINGS_PATH)


def test_the_production_profile_is_found() -> None:
    path = profile_path({PROFILE_ENV_VAR: "production"})
    assert path is not None and path.name == "settings.production.toml"


@pytest.mark.parametrize("name", ["../secrets", "Production", "prod/../x", "a b", "-x", "x" * 40])
def test_a_profile_name_that_is_not_a_plain_name_is_refused(name: str) -> None:
    with pytest.raises(ValueError, match=PROFILE_ENV_VAR):
        profile_path({PROFILE_ENV_VAR: name})


def test_an_unknown_profile_is_refused() -> None:
    with pytest.raises(FileNotFoundError, match="settings.staging.toml"):
        profile_path({PROFILE_ENV_VAR: "staging"})


def test_an_explicit_path_ignores_the_profile(tmp_path: Path) -> None:
    path = tmp_path / "settings.toml"
    path.write_text("[ui]\nhost = 'x'\n")
    assert read_toml(path, {PROFILE_ENV_VAR: "production"}) == {"ui": {"host": "x"}}


def test_overlay_merges_tables_and_replaces_values() -> None:
    base: dict[str, object] = {"a": {"x": 1, "y": {"z": 2}}, "b": 3}
    merged = overlay_settings(base, {"a": {"y": {"z": 9}}, "b": 4})
    assert merged == {"a": {"x": 1, "y": {"z": 9}}, "b": 4}
    assert base == {"a": {"x": 1, "y": {"z": 2}}, "b": 3}, "the base is not changed"


def test_overlay_refuses_a_key_the_base_lacks() -> None:
    with pytest.raises(ValueError, match=r"a\.typo"):
        overlay_settings({"a": {"x": 1}}, {"a": {"typo": 2}})


@pytest.mark.parametrize("overlay", [{"a": 1}, {"b": {"x": 1}}])
def test_overlay_refuses_to_change_a_table_into_a_value_or_back(overlay: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="kind"):
        overlay_settings({"a": {"x": 1}, "b": 2}, overlay)


def test_production_profile_gives_the_production_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(PROFILE_ENV_VAR, "production")
    assert load_ui_settings().origin == "https://ecofate.org"
    assert load_mail_settings().app_base_url == "https://ecofate.org"
    auth = load_auth_settings()
    assert auth.cookie_secure is True
    assert auth.trusted_proxy_hops == 1
    assert load_telemetry_settings().environment == "production"
    assert load_worker_settings().chat.concurrency == 4
    assert load_worker_settings().heavy_tools == ()  # off in production until switched on
    assert load_worker_settings().tools.concurrency == 2


def test_without_a_profile_local_values_stay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(PROFILE_ENV_VAR, raising=False)
    assert load_ui_settings().origin == "http://127.0.0.1:8000"
    assert load_auth_settings().cookie_secure is False
    assert load_worker_settings().chat.concurrency == 2
    assert load_worker_settings().heavy_tools == ("assess_facilities",)
