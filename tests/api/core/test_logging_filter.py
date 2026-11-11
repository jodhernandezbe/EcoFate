"""Tests for the server's log configuration and the app-wide key protection."""

from __future__ import annotations

import pytest
from pydantic import SecretStr
from uvicorn.config import LOGGING_CONFIG

import app.redaction as redaction
from api.core.logging_filter import LITERAL_REDACTED, redact, uvicorn_log_config
from app.operator_keys import OperatorKeys
from config.telemetry import get_telemetry_settings
from tests.api.auth_support import build_app
from tests.fakes import InMemoryThreadStore, KeyBench

CENSUS = "c3n5u5k3y" + "7f" * 16  # pragma: allowlist secret
LOGFIRE = "write-token-" + "w" * 20  # pragma: allowlist secret


def test_uvicorn_log_config_filters_every_handler_without_mutating_the_base() -> None:
    config = uvicorn_log_config(LOGGING_CONFIG)
    assert all("redact_secrets" in h["filters"] for h in config["handlers"].values())
    assert "redact_secrets" not in LOGGING_CONFIG.get("filters", {})


def test_root_logger_goes_through_a_redacting_handler() -> None:
    config = uvicorn_log_config(LOGGING_CONFIG)
    assert config["root"]["handlers"] == ["default"]
    assert "redact_secrets" in config["handlers"]["default"]["filters"]


def test_operator_keys_and_process_secrets_are_protected_once_the_app_starts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient

    empty: set[str] = set()
    monkeypatch.setattr(redaction, "_PROCESS_LITERALS", empty)
    monkeypatch.setenv(get_telemetry_settings().write_token_env_var, LOGFIRE)
    operator = OperatorKeys(census=SecretStr(CENSUS))
    keys = KeyBench(operator).services
    with TestClient(build_app(threads=InMemoryThreadStore(), keys=keys)):
        assert CENSUS not in redact(f"plain text {CENSUS} in a log")
        assert LOGFIRE not in redact(f"token {LOGFIRE}")
        assert redact(f"plain text {CENSUS}") == f"plain text {LITERAL_REDACTED}"
