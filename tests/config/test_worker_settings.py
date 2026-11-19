"""Tests for the ``[worker]`` settings loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from config.worker import check_heavy_tools, get_worker_settings, load_worker_settings

WORKER_FILE = """
[worker]
redis_url_env_var = "REDIS_URL"
heavy_tools = ["slow"]
max_open_jobs_per_user = 2
visibility_timeout_seconds = 30
heartbeat_seconds = 2
stale_after_seconds = 6
event_stream_max_length = 100
event_ttl_seconds = 60
relay_block_seconds = 1
broker_timeout_seconds = 1
eager = true

[worker.chat]
queue = "q"
concurrency = 2
prefetch_multiplier = 1
soft_time_limit_seconds = 10
time_limit_seconds = 20

[worker.tools]
queue = "t"
concurrency = 1
prefetch_multiplier = 1
soft_time_limit_seconds = 15
time_limit_seconds = 25
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "settings.toml"
    path.write_text(text)
    return path


def test_values(tmp_path: Path) -> None:
    settings = load_worker_settings(_write(tmp_path, WORKER_FILE))
    assert settings.redis_url_env_var == "REDIS_URL"
    assert (settings.chat.queue, settings.tools.queue) == ("q", "t")
    assert (settings.chat.concurrency, settings.tools.concurrency) == (2, 1)
    assert (settings.chat.soft_time_limit_seconds, settings.chat.time_limit_seconds) == (10, 20)
    assert (settings.tools.soft_time_limit_seconds, settings.tools.time_limit_seconds) == (15, 25)
    assert settings.heavy_tools == ("slow",)
    assert settings.max_open_jobs_per_user == 2
    assert settings.visibility_timeout_seconds == 30
    assert settings.eager is True


def test_shipped_settings() -> None:
    settings = get_worker_settings()
    assert settings.eager is False
    assert (settings.chat.queue, settings.tools.queue) == ("chat", "tools")
    for pool in (settings.chat, settings.tools):
        assert pool.soft_time_limit_seconds < pool.time_limit_seconds
        assert pool.time_limit_seconds < settings.visibility_timeout_seconds
    assert settings.heavy_tools == ("assess_facilities",)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("heartbeat_seconds = 2", "heartbeat_seconds = -1", "worker.heartbeat_seconds"),
        ("event_ttl_seconds = 60", "event_ttl_seconds = false", "worker.event_ttl_seconds"),
        ("max_open_jobs_per_user = 2", "max_open_jobs_per_user = 0", "max_open_jobs_per_user"),
        ("max_open_jobs_per_user = 2", "max_open_jobs_per_user = true", "max_open_jobs_per_user"),
        ('heavy_tools = ["slow"]', 'heavy_tools = "slow"', "heavy_tools"),
        ('heavy_tools = ["slow"]', 'heavy_tools = [" "]', "heavy_tools"),
        ("eager = true", "eager = 1", "worker.eager"),
        ('redis_url_env_var = "REDIS_URL"', "redis_url_env_var = 3", "redis_url_env_var"),
        ("stale_after_seconds = 6", "stale_after_seconds = 2", "stale_after_seconds"),
        (
            "visibility_timeout_seconds = 30",
            "visibility_timeout_seconds = 25",
            "visibility_timeout_seconds",
        ),
        (
            "visibility_timeout_seconds = 30",
            "visibility_timeout_seconds = 20",
            "visibility_timeout_seconds",
        ),
        ('queue = "t"', 'queue = "q"', "must differ"),
    ],
)
def test_invalid(tmp_path: Path, old: str, new: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        load_worker_settings(_write(tmp_path, WORKER_FILE.replace(old, new)))


@pytest.mark.parametrize("pool", ["chat", "tools"])
@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("concurrency", "0", "concurrency"),
        ("concurrency", "true", "concurrency"),
        ("concurrency", "1.5", "concurrency"),
        ("prefetch_multiplier", "-1", "prefetch_multiplier"),
        ("soft_time_limit_seconds", "false", "soft_time_limit_seconds"),
        ("time_limit_seconds", "0", "time_limit_seconds"),
        ("soft_time_limit_seconds", "1000", "time_limit_seconds"),
        ("soft_time_limit_seconds", "25", "time_limit_seconds"),
        ("queue", '" "', "queue"),
    ],
)
def test_invalid_pool(tmp_path: Path, pool: str, key: str, value: str, message: str) -> None:
    header = f"[worker.{pool}]"
    start = WORKER_FILE.index(header)
    end = WORKER_FILE.find("\n[", start + 1)
    table = WORKER_FILE[start : end if end != -1 else len(WORKER_FILE)]
    changed = "\n".join(
        f"{key} = {value}" if line.startswith(f"{key} =") else line for line in table.split("\n")
    )
    text = WORKER_FILE.replace(table, changed)
    with pytest.raises(ValueError, match=message):
        load_worker_settings(_write(tmp_path, text))


def test_a_missing_pool_table_is_refused(tmp_path: Path) -> None:
    text = WORKER_FILE.replace("[worker.tools]", "[worker.other]")
    with pytest.raises(ValueError, match="worker.tools"):
        load_worker_settings(_write(tmp_path, text))


def test_unregistered_heavy_tool_is_refused(tmp_path: Path) -> None:
    settings = load_worker_settings(_write(tmp_path, WORKER_FILE))
    check_heavy_tools(settings, ["slow", "fast"])
    with pytest.raises(ValueError, match="slow"):
        check_heavy_tools(settings, ["fast"])


def test_missing_section(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="worker section is missing"):
        load_worker_settings(_write(tmp_path, "[other]\n"))
