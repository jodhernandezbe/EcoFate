"""Tests for the ``[telemetry]`` settings loader (Logfire monitoring)."""

from __future__ import annotations

from pathlib import Path

import pytest

from config.telemetry import get_telemetry_settings, load_telemetry_settings

TELEMETRY = """
[telemetry]
enabled = true
service_name = "svc"
environment = "test"
console = false
write_token_env_var = "TEST_WRITE_VAR"  # pragma: allowlist secret
read_token_env_var = "TEST_READ_VAR"  # pragma: allowlist secret
query_timeout_seconds = 5
session_window_hours = 24
max_sessions = 10
max_rows = 100
trace_url_template = "https://example.test/{organization}/{project}?trace={trace_id}"

[telemetry.spans]
cli_session = "cli run"
web_turn = "web turn"

[telemetry.attributes]
session_id = "session.id"
question = "q"
model = "m"
outcome = "o"
usage_prefix = "u."
session_usage_prefix = "s."
turn_id = "t"
resume_index = "r"

[telemetry.bridge]
operation = "op"
model_operation = "chat"
tool_operation = "tool_run"
tool_name = "tool.name"
usage_metadata = "usage.json"
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "settings.toml"
    path.write_text(text)
    return path


def _replace(tmp_path: Path, line_start: str, new_line: str) -> Path:
    lines = [new_line if ln.startswith(line_start) else ln for ln in TELEMETRY.splitlines()]
    return _write(tmp_path, "\n".join(lines))


def test_values(tmp_path: Path) -> None:
    settings = load_telemetry_settings(_write(tmp_path, TELEMETRY))
    assert (settings.enabled, settings.console) == (True, False)
    assert (settings.service_name, settings.environment) == ("svc", "test")
    assert settings.read_token_env_var == "TEST_READ_VAR"  # pragma: allowlist secret
    assert settings.write_token_env_var == "TEST_WRITE_VAR"  # pragma: allowlist secret
    assert settings.query_timeout_seconds == 5.0
    assert (settings.session_window_hours, settings.max_sessions) == (24, 10)
    assert settings.max_rows == 100
    assert settings.spans.cli_session == "cli run"
    assert settings.attributes.usage_prefix == "u."
    assert (settings.bridge.model_operation, settings.bridge.tool_operation) == ("chat", "tool_run")


def test_shipped_settings_load() -> None:
    settings = get_telemetry_settings()
    assert settings.read_token_env_var == "LOGFIRE_READ_TOKEN"  # pragma: allowlist secret
    assert settings.write_token_env_var == "LOGFIRE_TOKEN"  # pragma: allowlist secret
    assert "{trace_id}" in settings.trace_url_template
    assert settings.spans.cli_session != settings.spans.web_turn


@pytest.mark.parametrize(
    ("line_start", "new_line", "key"),
    [
        ("enabled", 'enabled = "yes"', "telemetry.enabled"),
        ("enabled", "enabled = 1", "telemetry.enabled"),
        ("console", "console = 0", "telemetry.console"),
        ("service_name", 'service_name = " "', "telemetry.service_name"),
        ("environment", "environment = 3", "telemetry.environment"),
        ("read_token_env_var", 'read_token_env_var = ""', "telemetry.read_token_env_var"),
        ("write_token_env_var", "write_token_env_var = 5", "telemetry.write_token_env_var"),
        ("query_timeout_seconds", "query_timeout_seconds = 0", "telemetry.query_timeout_seconds"),
        (
            "query_timeout_seconds",
            "query_timeout_seconds = true",
            "telemetry.query_timeout_seconds",
        ),
        ("session_window_hours", "session_window_hours = 0", "telemetry.session_window_hours"),
        ("session_window_hours", "session_window_hours = 1.5", "telemetry.session_window_hours"),
        ("max_sessions", "max_sessions = true", "telemetry.max_sessions"),
        ("max_sessions", "max_sessions = 0", "telemetry.max_sessions"),
        ("max_rows", "max_rows = 0", "telemetry.max_rows"),
        ("max_rows", "max_rows = 2.5", "telemetry.max_rows"),
        ("trace_url_template", 'trace_url_template = "https://x.test/"', "trace_url_template"),
        (
            "trace_url_template",
            'trace_url_template = "http://x.test/{trace_id}"',
            "trace_url_template",
        ),
        ("web_turn", 'web_turn = "cli run"', "telemetry.spans"),
        ("cli_session", "cli_session = 4", "telemetry.spans.cli_session"),
        ("session_usage_prefix", 'session_usage_prefix = "u."', "telemetry.attributes"),
        ("outcome", 'outcome = ""', "telemetry.attributes.outcome"),
        ("turn_id", 'turn_id = ""', "telemetry.attributes.turn_id"),
        ("resume_index", "resume_index = 1", "telemetry.attributes.resume_index"),
        ("tool_operation", "tool_operation = 3", "telemetry.bridge.tool_operation"),
        ("usage_metadata", 'usage_metadata = " "', "telemetry.bridge.usage_metadata"),
    ],
)
def test_invalid_value_names_the_key(
    tmp_path: Path,
    line_start: str,
    new_line: str,
    key: str,
) -> None:
    with pytest.raises(ValueError, match=key):
        load_telemetry_settings(_replace(tmp_path, line_start, new_line))


@pytest.mark.parametrize(
    "missing",
    ["[telemetry]", "[telemetry.spans]", "[telemetry.attributes]", "[telemetry.bridge]"],
)
def test_missing_section(tmp_path: Path, missing: str) -> None:
    text = TELEMETRY.replace(missing, "[other]")
    with pytest.raises(ValueError, match="telemetry"):
        load_telemetry_settings(_write(tmp_path, text))
