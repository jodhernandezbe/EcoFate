"""Typed loader for the ``[limits]`` settings: the daily quota of agent turns per user."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from config.parsing import read_toml, require_bool, require_int, require_str, section

_NAME = "limits"


@dataclass(frozen=True)
class LimitSettings:
    """Daily quota settings.

    Attributes:
        enabled: Whether any turn is counted or refused.
        daily_turns_per_user: New agent turns one user may start per UTC day (>= 1).
        admin_exempt: Whether administrators are neither counted nor refused.
        retention_days: Days a usage row is kept before the purge deletes it.
        exhausted_message: Fixed text shown when the quota is used up.
    """

    enabled: bool
    daily_turns_per_user: int
    admin_exempt: bool
    retention_days: int
    exhausted_message: str


def load_limit_settings(path: Path | None = None) -> LimitSettings:
    """Load and validate the ``[limits]`` settings.

    Args:
        path: Settings file; defaults to the ``settings.toml`` shipped in ``config/``.

    Returns:
        The validated settings.

    Raises:
        FileNotFoundError: If the settings file does not exist.
        ValueError: If a key is missing or invalid (a boolean is not a number); the message
            names the key.
    """
    table = section(read_toml(path), _NAME)
    return LimitSettings(
        enabled=require_bool(table, "enabled", _NAME),
        daily_turns_per_user=require_int(table, "daily_turns_per_user", minimum=1, name=_NAME),
        admin_exempt=require_bool(table, "admin_exempt", _NAME),
        retention_days=require_int(table, "retention_days", minimum=1, name=_NAME),
        exhausted_message=require_str(table, "exhausted_message", _NAME).strip(),
    )


@lru_cache(maxsize=1)
def get_limit_settings() -> LimitSettings:
    """Return the cached ``[limits]`` settings from the default file."""
    return load_limit_settings()
