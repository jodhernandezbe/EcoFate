"""Tests for the ``[database]`` settings loader (PostgreSQL store)."""

from __future__ import annotations

from pathlib import Path

import pytest

from config.database import get_database_settings, load_database_settings

_FILE = """
[agent]
provider = "openai"
model = "test-model"
api_key_env_var = "TEST_KEY_VAR"  # pragma: allowlist secret
timeout_seconds = 120.0
recursion_limit = 10
temperature = 0.0

[database]
url_env_var = "TEST_DATABASE_URL"
pool_size = 4
pool_timeout_seconds = 5.0
statement_timeout_seconds = 20.0
health_timeout_seconds = 1.5
turn_lease_seconds = 300.0
thread_retention_days = 14
purge_interval_minutes = 30
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "settings.toml"
    path.write_text(text)
    return path


def _replace(tmp_path: Path, line_start: str, new_line: str) -> Path:
    lines = [new_line if ln.startswith(line_start) else ln for ln in _FILE.splitlines()]
    return _write(tmp_path, "\n".join(lines))


def test_values(tmp_path: Path) -> None:
    settings = load_database_settings(_write(tmp_path, _FILE))
    assert settings.url_env_var == "TEST_DATABASE_URL"
    assert (settings.pool_size, settings.thread_retention_days) == (4, 14)
    assert (settings.pool_timeout_seconds, settings.statement_timeout_seconds) == (5.0, 20.0)
    assert (settings.health_timeout_seconds, settings.turn_lease_seconds) == (1.5, 300.0)
    assert settings.purge_interval_minutes == 30


def test_shipped_settings_load_without_a_url() -> None:
    settings = get_database_settings()
    assert settings.url_env_var == "DATABASE_URL"
    assert "://" not in settings.url_env_var


@pytest.mark.parametrize(
    ("line_start", "new_line"),
    [
        ("url_env_var", 'url_env_var = ""'),
        ("url_env_var", 'url_env_var = "  "'),
        ("pool_size", "pool_size = 0"),
        ("pool_size", "pool_size = true"),
        ("pool_timeout_seconds", "pool_timeout_seconds = 0"),
        ("pool_timeout_seconds", "pool_timeout_seconds = -1"),
        ("statement_timeout_seconds", "statement_timeout_seconds = true"),
        ("health_timeout_seconds", "health_timeout_seconds = 0"),
        ("turn_lease_seconds", "turn_lease_seconds = 0"),
        ("turn_lease_seconds", "turn_lease_seconds = false"),
        ("thread_retention_days", "thread_retention_days = 0"),
        ("thread_retention_days", "thread_retention_days = true"),
        ("purge_interval_minutes", "purge_interval_minutes = -5"),
        ("purge_interval_minutes", "purge_interval_minutes = true"),
    ],
)
def test_invalid_entry_names_the_key(tmp_path: Path, line_start: str, new_line: str) -> None:
    with pytest.raises(ValueError, match=f"database.{line_start}"):
        load_database_settings(_replace(tmp_path, line_start, new_line))


@pytest.mark.parametrize("lease", ["100.0", "120.0"])
def test_lease_must_exceed_the_agent_timeout(tmp_path: Path, lease: str) -> None:
    path = _replace(tmp_path, "turn_lease_seconds", f"turn_lease_seconds = {lease}")
    with pytest.raises(ValueError, match="database.turn_lease_seconds"):
        load_database_settings(path)


def test_shipped_lease_exceeds_the_shipped_agent_timeout() -> None:
    from config.agent import get_agent_settings

    assert get_database_settings().turn_lease_seconds > get_agent_settings().timeout_seconds


def test_missing_section(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="database section is missing"):
        load_database_settings(_write(tmp_path, "[agent]\n"))
