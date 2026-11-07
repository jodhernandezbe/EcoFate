"""Tests for the ``[agent]`` settings loader (the chat model that drives the agent)."""

from __future__ import annotations

from pathlib import Path

import pytest

from config.agent import get_agent_settings, load_agent_settings

AGENT = """
[agent]
provider = " OpenAI "
model = "chat-test"
api_key_env_var = "TEST_KEY_VAR"  # pragma: allowlist secret
timeout_seconds = 5
recursion_limit = 10
temperature = 0.3
max_resumes_per_turn = 2
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "settings.toml"
    path.write_text(text)
    return path


def _replace(tmp_path: Path, line_start: str, new_line: str) -> Path:
    lines = [new_line if ln.startswith(line_start) else ln for ln in AGENT.splitlines()]
    return _write(tmp_path, "\n".join(lines))


def test_values(tmp_path: Path) -> None:
    settings = load_agent_settings(_write(tmp_path, AGENT))
    assert (settings.provider, settings.model) == ("openai", "chat-test")
    assert settings.api_key_env_var == "TEST_KEY_VAR"  # pragma: allowlist secret
    assert settings.timeout_seconds == 5.0
    assert settings.recursion_limit == 10
    assert settings.temperature == 0.3
    assert settings.max_resumes_per_turn == 2


def test_shipped_settings_load() -> None:
    settings = get_agent_settings()
    assert settings.provider == "openai"
    assert settings.model
    assert settings.temperature == 0.0  # reproducible screening runs
    assert settings.max_resumes_per_turn >= 1


@pytest.mark.parametrize(
    ("line_start", "new_line", "key"),
    [
        ("provider", 'provider = "other"', "agent.provider"),
        ("model", 'model = " "', "agent.model"),
        ("model", "model = 3", "agent.model"),
        ("api_key_env_var", 'api_key_env_var = ""', "agent.api_key_env_var"),
        ("timeout_seconds", "timeout_seconds = 0", "agent.timeout_seconds"),
        ("timeout_seconds", "timeout_seconds = true", "agent.timeout_seconds"),
        ("recursion_limit", "recursion_limit = 0", "agent.recursion_limit"),
        ("recursion_limit", "recursion_limit = 2.5", "agent.recursion_limit"),
        ("temperature", "temperature = -0.1", "agent.temperature"),
        ("temperature", "temperature = 2.5", "agent.temperature"),
        ("temperature", "temperature = true", "agent.temperature"),
        ("temperature", "", "agent.temperature"),
        ("max_resumes_per_turn", "max_resumes_per_turn = 0", "agent.max_resumes_per_turn"),
        ("max_resumes_per_turn", "max_resumes_per_turn = -1", "agent.max_resumes_per_turn"),
        ("max_resumes_per_turn", "max_resumes_per_turn = true", "agent.max_resumes_per_turn"),
        ("max_resumes_per_turn", "max_resumes_per_turn = 1.5", "agent.max_resumes_per_turn"),
        ("max_resumes_per_turn", "", "agent.max_resumes_per_turn"),
    ],
)
def test_invalid_entry_names_key(tmp_path: Path, line_start: str, new_line: str, key: str) -> None:
    with pytest.raises(ValueError, match=key):
        load_agent_settings(_replace(tmp_path, line_start, new_line))


def test_missing_section(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="agent section is missing"):
        load_agent_settings(_write(tmp_path, "[other]\nx = 1\n"))
