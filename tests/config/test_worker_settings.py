"""Tests for the ``[worker]`` settings loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from config.worker import get_worker_settings, load_worker_settings

WORKER_FILE = """
[worker]
redis_url_env_var = "REDIS_URL"
queue = "q"
concurrency = 2
prefetch_multiplier = 1
soft_time_limit_seconds = 10
time_limit_seconds = 20
visibility_timeout_seconds = 30
heartbeat_seconds = 2
stale_after_seconds = 6
event_stream_max_length = 100
event_ttl_seconds = 60
relay_block_seconds = 1
broker_timeout_seconds = 1
eager = true
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "settings.toml"
    path.write_text(text)
    return path


def test_values(tmp_path: Path) -> None:
    settings = load_worker_settings(_write(tmp_path, WORKER_FILE))
    assert settings.redis_url_env_var == "REDIS_URL"
    assert settings.queue == "q"
    assert settings.concurrency == 2
    assert (settings.soft_time_limit_seconds, settings.time_limit_seconds) == (10, 20)
    assert settings.visibility_timeout_seconds == 30
    assert settings.eager is True


def test_shipped_settings() -> None:
    settings = get_worker_settings()
    assert settings.eager is False
    assert settings.soft_time_limit_seconds < settings.time_limit_seconds
    assert settings.time_limit_seconds < settings.visibility_timeout_seconds


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("concurrency = 2", "concurrency = 0", "worker.concurrency"),
        ("concurrency = 2", "concurrency = true", "worker.concurrency"),
        ("concurrency = 2", "concurrency = 1.5", "worker.concurrency"),
        ("heartbeat_seconds = 2", "heartbeat_seconds = -1", "worker.heartbeat_seconds"),
        ("event_ttl_seconds = 60", "event_ttl_seconds = false", "worker.event_ttl_seconds"),
        ("eager = true", "eager = 1", "worker.eager"),
        ('queue = "q"', 'queue = " "', "worker.queue"),
        ('redis_url_env_var = "REDIS_URL"', "redis_url_env_var = 3", "redis_url_env_var"),
        ("soft_time_limit_seconds = 10", "soft_time_limit_seconds = 25", "time_limit_seconds"),
        ("soft_time_limit_seconds = 10", "soft_time_limit_seconds = 20", "time_limit_seconds"),
        (
            "visibility_timeout_seconds = 30",
            "visibility_timeout_seconds = 20",
            "visibility_timeout_seconds",
        ),
        ("stale_after_seconds = 6", "stale_after_seconds = 2", "stale_after_seconds"),
    ],
)
def test_invalid(tmp_path: Path, old: str, new: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        load_worker_settings(_write(tmp_path, WORKER_FILE.replace(old, new)))


def test_missing_section(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="worker section is missing"):
        load_worker_settings(_write(tmp_path, "[other]\n"))
