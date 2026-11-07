"""Typed loader for the ``[database]`` settings: the PostgreSQL store of the web program."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from config.agent import load_agent_settings
from config.parsing import read_toml, require_int, require_number, require_str, section

_NAME = "database"


@dataclass(frozen=True)
class DatabaseSettings:
    """Database settings. The connection URL is never stored, only its variable name.

    Attributes:
        url_env_var: Environment variable holding the connection URL (with the password).
        pool_size: Connections kept open per process.
        pool_timeout_seconds: Seconds to wait for a free pooled connection.
        statement_timeout_seconds: Seconds one statement may run before it is cancelled.
        health_timeout_seconds: Seconds the health check waits for the database.
        turn_lease_seconds: Seconds a turn holds its thread before another process may claim it.
        thread_retention_days: Days a thread may sit idle before it is purged.
        purge_interval_minutes: Minutes between purges of idle threads.
    """

    url_env_var: str
    pool_size: int
    pool_timeout_seconds: float
    statement_timeout_seconds: float
    health_timeout_seconds: float
    turn_lease_seconds: float
    thread_retention_days: int
    purge_interval_minutes: int


def _seconds(table: dict[str, object], key: str) -> float:
    return require_number(table, key, minimum=0.001, name=_NAME)


def _lease(table: dict[str, object], agent_timeout_seconds: float) -> float:
    lease = _seconds(table, "turn_lease_seconds")
    if lease <= agent_timeout_seconds:
        raise ValueError(
            f"{_NAME}.turn_lease_seconds must be greater than agent.timeout_seconds "
            f"({agent_timeout_seconds})",
        )
    return lease


def load_database_settings(path: Path | None = None) -> DatabaseSettings:
    """Load and validate the database settings.

    Args:
        path: Settings file; defaults to the ``settings.toml`` shipped in ``config/``.

    Returns:
        The validated settings (timeouts and lease in seconds, retention in days, purge
        interval in minutes).

    Raises:
        FileNotFoundError: If the settings file does not exist.
        ValueError: If a key is missing or invalid; the message names the key.
    """
    table = section(read_toml(path), _NAME)
    url_env_var = require_str(table, "url_env_var", _NAME).strip()
    return DatabaseSettings(
        url_env_var=url_env_var,
        pool_size=require_int(table, "pool_size", minimum=1, name=_NAME),
        pool_timeout_seconds=_seconds(table, "pool_timeout_seconds"),
        statement_timeout_seconds=_seconds(table, "statement_timeout_seconds"),
        health_timeout_seconds=_seconds(table, "health_timeout_seconds"),
        turn_lease_seconds=_lease(table, load_agent_settings(path).timeout_seconds),
        thread_retention_days=require_int(table, "thread_retention_days", minimum=1, name=_NAME),
        purge_interval_minutes=require_int(table, "purge_interval_minutes", minimum=1, name=_NAME),
    )


@lru_cache(maxsize=1)
def get_database_settings() -> DatabaseSettings:
    """Return the cached database settings from the default file."""
    return load_database_settings()
