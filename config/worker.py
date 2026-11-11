"""Typed loader for the ``[worker]`` settings: the background worker that runs chat turns."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from config.parsing import read_toml, require_bool, require_int, require_str, section

_NAME = "worker"


@dataclass(frozen=True)
class WorkerSettings:
    """Worker, broker and event-stream settings (times in seconds).

    Attributes:
        redis_url_env_var: Environment variable holding the Redis URL (never the URL itself).
        queue: The Celery queue turns are enqueued on.
        concurrency: Turns one worker runs at once.
        prefetch_multiplier: Tasks a child reserves ahead.
        soft_time_limit_seconds: After this a turn becomes ``interrupted/time_limit``.
        time_limit_seconds: After this the child is killed (backstop); above the soft limit.
        visibility_timeout_seconds: Redis redelivers an unacknowledged task after this; above
            the hard limit.
        heartbeat_seconds: How often the running turn's heartbeat is recorded.
        stale_after_seconds: A heartbeat older than this means the worker is lost.
        event_stream_max_length: Approximate cap on the events kept per turn.
        event_ttl_seconds: How long a finished turn's events stay readable.
        relay_block_seconds: How long one blocking read of a turn's events waits.
        broker_timeout_seconds: How long enqueueing waits for Redis.
        eager: Run tasks in the calling process with an in-memory event stream (tests).
    """

    redis_url_env_var: str
    queue: str
    concurrency: int
    prefetch_multiplier: int
    soft_time_limit_seconds: int
    time_limit_seconds: int
    visibility_timeout_seconds: int
    heartbeat_seconds: int
    stale_after_seconds: int
    event_stream_max_length: int
    event_ttl_seconds: int
    relay_block_seconds: int
    broker_timeout_seconds: int
    eager: bool


_POSITIVE = (
    "concurrency",
    "prefetch_multiplier",
    "soft_time_limit_seconds",
    "time_limit_seconds",
    "visibility_timeout_seconds",
    "heartbeat_seconds",
    "stale_after_seconds",
    "event_stream_max_length",
    "event_ttl_seconds",
    "relay_block_seconds",
    "broker_timeout_seconds",
)


def load_worker_settings(path: Path | None = None) -> WorkerSettings:
    """Load and validate the ``[worker]`` settings.

    Args:
        path: Settings file; defaults to the ``settings.toml`` shipped in ``config/``.

    Returns:
        The validated settings.

    Raises:
        FileNotFoundError: If the settings file does not exist.
        ValueError: If a key is missing or not positive (a boolean is not a number), or the
            limits are out of order (soft < hard < visibility timeout, heartbeat < stale age);
            the message names the key.
    """
    table = section(read_toml(path), _NAME)
    numbers = {key: require_int(table, key, minimum=1, name=_NAME) for key in _POSITIVE}
    settings = WorkerSettings(
        redis_url_env_var=require_str(table, "redis_url_env_var", _NAME).strip(),
        queue=require_str(table, "queue", _NAME).strip(),
        eager=require_bool(table, "eager", _NAME),
        **numbers,
    )
    _check_order(settings)
    return settings


def _check_order(settings: WorkerSettings) -> None:
    """Raise unless soft limit < hard limit < visibility timeout and heartbeat < stale age."""
    if settings.time_limit_seconds <= settings.soft_time_limit_seconds:
        raise ValueError(f"{_NAME}.time_limit_seconds must exceed soft_time_limit_seconds")
    if settings.visibility_timeout_seconds <= settings.time_limit_seconds:
        raise ValueError(f"{_NAME}.visibility_timeout_seconds must exceed time_limit_seconds")
    if settings.stale_after_seconds <= settings.heartbeat_seconds:
        raise ValueError(f"{_NAME}.stale_after_seconds must exceed heartbeat_seconds")


@lru_cache(maxsize=1)
def get_worker_settings() -> WorkerSettings:
    """Return the cached ``[worker]`` settings from the default file."""
    return load_worker_settings()
