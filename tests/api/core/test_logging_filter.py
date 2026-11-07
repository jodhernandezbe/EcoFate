"""Tests for the server's log configuration and the app-wide key protection."""

from __future__ import annotations

import pytest
from uvicorn.config import LOGGING_CONFIG

from api.core.logging_filter import LITERAL_REDACTED, redact, uvicorn_log_config
from tests.fakes import InMemoryThreadStore

CENSUS = "c3n5u5k3y" + "7f" * 16  # pragma: allowlist secret


def test_uvicorn_log_config_filters_every_handler_without_mutating_the_base() -> None:
    config = uvicorn_log_config(LOGGING_CONFIG)
    assert all("redact_secrets" in h["filters"] for h in config["handlers"].values())
    assert "redact_secrets" not in LOGGING_CONFIG.get("filters", {})


def test_root_logger_goes_through_a_redacting_handler() -> None:
    config = uvicorn_log_config(LOGGING_CONFIG)
    assert config["root"]["handlers"] == ["default"]
    assert "redact_secrets" in config["handlers"]["default"]["filters"]


def test_keys_from_the_environment_are_protected_while_the_app_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient

    from api.main import create_app

    monkeypatch.setenv("CENSUS_API_KEY", CENSUS)
    monkeypatch.setenv("COMPTOX_API_KEY", "ct0x-key-" + "9d" * 14)  # pragma: allowlist secret
    with TestClient(create_app(threads=InMemoryThreadStore())):
        assert CENSUS not in redact(f"plain text {CENSUS} in a log")
        assert "ct0x-key-" not in redact("value ct0x-key-" + "9d" * 14)
    assert redact(f"plain text {CENSUS}") != "plain text " + LITERAL_REDACTED  # not after shutdown
