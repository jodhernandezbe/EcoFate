"""Typed loader for the ``[worker]`` settings: the two worker pools (``chat`` and ``tools``)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from config.parsing import (
    names,
    read_toml,
    require_bool,
    require_int,
    require_str,
    section,
    subtable,
)

_NAME = "worker"


@dataclass(frozen=True)
class PoolSettings:
    """One worker pool: the queue it consumes and how it runs tasks (times in seconds).

    Attributes:
        queue: The Celery queue this pool consumes.
        concurrency: Tasks the pool runs at once (prefork child processes).
        prefetch_multiplier: Tasks a child reserves ahead.
        soft_time_limit_seconds: After this a task is stopped by its own runner (resumable).
        time_limit_seconds: After this the child is killed (backstop); above the soft limit.
    """

    queue: str
    concurrency: int
    prefetch_multiplier: int
    soft_time_limit_seconds: int
    time_limit_seconds: int


@dataclass(frozen=True)
class WorkerSettings:
    """Worker, broker and event-stream settings (times in seconds).

    Attributes:
        redis_url_env_var: Environment variable holding the Redis URL (never the URL itself).
        chat: The pool that runs agent turns (``ecofate.run_turn``).
        tools: The pool that runs background tool jobs (``ecofate.run_job``).
        heavy_tools: Names of the tools that run as background jobs (validated against the
            registered tools by ``check_heavy_tools``, where the registry is built).
        max_open_jobs_per_user: Queued plus running jobs one user may have.
        visibility_timeout_seconds: Redis redelivers an unacknowledged task after this; above
            both pools' hard limits.
        heartbeat_seconds: How often the running turn's heartbeat is recorded.
        stale_after_seconds: A heartbeat older than this means the worker is lost.
        event_stream_max_length: Approximate cap on the events kept per turn.
        event_ttl_seconds: How long a finished turn's events stay readable.
        relay_block_seconds: How long one blocking read of a turn's events waits.
        broker_timeout_seconds: How long enqueueing waits for Redis.
        eager: Run tasks in the calling process with an in-memory event stream (tests).
    """

    redis_url_env_var: str
    chat: PoolSettings
    tools: PoolSettings
    heavy_tools: tuple[str, ...]
    max_open_jobs_per_user: int
    visibility_timeout_seconds: int
    heartbeat_seconds: int
    stale_after_seconds: int
    event_stream_max_length: int
    event_ttl_seconds: int
    relay_block_seconds: int
    broker_timeout_seconds: int
    eager: bool


_POOL_NUMBERS = (
    "concurrency",
    "prefetch_multiplier",
    "soft_time_limit_seconds",
    "time_limit_seconds",
)
_POSITIVE = (
    "max_open_jobs_per_user",
    "visibility_timeout_seconds",
    "heartbeat_seconds",
    "stale_after_seconds",
    "event_stream_max_length",
    "event_ttl_seconds",
    "relay_block_seconds",
    "broker_timeout_seconds",
)


def _load_pool(table: dict[str, object], pool: str) -> PoolSettings:
    """One pool's settings from ``[worker.<pool>]``."""
    where = f"{_NAME}.{pool}"
    own = subtable(table, pool, _NAME)
    numbers = {key: require_int(own, key, minimum=1, name=where) for key in _POOL_NUMBERS}
    return PoolSettings(queue=require_str(own, "queue", where).strip(), **numbers)


def load_worker_settings(path: Path | None = None) -> WorkerSettings:
    """Load and validate the ``[worker]`` settings.

    Args:
        path: Settings file; defaults to the ``settings.toml`` shipped in ``config/``.

    Returns:
        The validated settings.

    Raises:
        FileNotFoundError: If the settings file does not exist.
        ValueError: If a key is missing or not positive (a boolean is not a number), or the
            limits are out of order (soft < hard < visibility timeout for each pool, heartbeat <
            stale age), or the two pools share a queue; the message names the key. The heavy
            tool names are checked against the registry by ``check_heavy_tools``.
    """
    table = section(read_toml(path), _NAME)
    numbers = {key: require_int(table, key, minimum=1, name=_NAME) for key in _POSITIVE}
    settings = WorkerSettings(
        redis_url_env_var=require_str(table, "redis_url_env_var", _NAME).strip(),
        chat=_load_pool(table, "chat"),
        tools=_load_pool(table, "tools"),
        heavy_tools=names(table, "heavy_tools", _NAME, allow_empty=True),
        eager=require_bool(table, "eager", _NAME),
        **numbers,
    )
    _check_order(settings)
    return settings


def _check_pool(pool: PoolSettings, name: str) -> None:
    if pool.time_limit_seconds <= pool.soft_time_limit_seconds:
        raise ValueError(f"{name}.time_limit_seconds must exceed soft_time_limit_seconds")


def _check_order(settings: WorkerSettings) -> None:
    """Raise unless soft < hard per pool, hard < visibility timeout and heartbeat < stale age."""
    _check_pool(settings.chat, f"{_NAME}.chat")
    _check_pool(settings.tools, f"{_NAME}.tools")
    if settings.chat.queue == settings.tools.queue:
        raise ValueError(f"{_NAME}.chat.queue and {_NAME}.tools.queue must differ")
    longest = max(settings.chat.time_limit_seconds, settings.tools.time_limit_seconds)
    if settings.visibility_timeout_seconds <= longest:
        raise ValueError(f"{_NAME}.visibility_timeout_seconds must exceed every time_limit_seconds")
    if settings.stale_after_seconds <= settings.heartbeat_seconds:
        raise ValueError(f"{_NAME}.stale_after_seconds must exceed heartbeat_seconds")


def check_heavy_tools(settings: WorkerSettings, registered: Iterable[str]) -> None:
    """Raise ``ValueError`` when ``[worker].heavy_tools`` names a tool that is not registered.

    Args:
        settings: The worker settings.
        registered: The names of the registered tools (``config`` cannot import the registry,
            so the caller that builds it passes them).
    """
    unknown = sorted(set(settings.heavy_tools) - set(registered))
    if unknown:
        raise ValueError(f"{_NAME}.heavy_tools names unregistered tools: {', '.join(unknown)}")


@lru_cache(maxsize=1)
def get_worker_settings() -> WorkerSettings:
    """Return the cached ``[worker]`` settings from the default file."""
    return load_worker_settings()
