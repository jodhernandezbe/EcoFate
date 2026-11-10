"""Typed loader for the ``[auth]`` settings: accounts, sessions, throttling and password hashing."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from config.parsing import (
    read_toml,
    require_bool,
    require_int,
    require_str,
    section,
    subtable,
)
from config.telemetry import load_telemetry_settings

_NAME = "auth"
_PRODUCTION = "production"
_MINUTES_PER_HOUR = 60
_MINUTES_PER_DAY = 24 * _MINUTES_PER_HOUR
_MIN_ARGON2_MEMORY_PER_LANE_KIB = 8  # Argon2 needs at least 8 KiB per lane


@dataclass(frozen=True)
class Argon2Settings:
    """Argon2id cost parameters.

    Attributes:
        time_cost: Passes over the memory.
        memory_cost_kib: Memory per hash, in KiB.
        parallelism: Lanes.
    """

    time_cost: int
    memory_cost_kib: int
    parallelism: int


@dataclass(frozen=True)
class ThrottleSettings:
    """Limit on failed sign-in and recovery attempts.

    Attributes:
        attempts: Failed attempts allowed per key within the window.
        window_minutes: Length of the counting window, in minutes.
    """

    attempts: int
    window_minutes: int

    @property
    def window_seconds(self) -> int:
        """The window in seconds (the ``Retry-After`` upper bound)."""
        return self.window_minutes * _MINUTES_PER_HOUR


@dataclass(frozen=True)
class AuthSettings:
    """Account settings. The session secret is never stored, only its variable name.

    Attributes:
        signup_open: Whether anyone may create an account.
        password_min_length: Shortest accepted password, in characters.
        password_max_length: Longest accepted password, in characters.
        session_idle_minutes: Minutes without a request after which a session ends.
        session_absolute_days: Days after which a session ends whatever its activity.
        verification_token_hours: Hours an email-verification link stays valid.
        reset_token_minutes: Minutes a password-reset link stays valid.
        cookie_name: Name of the session cookie.
        cookie_secure: Whether the cookie carries ``Secure`` (false only for plain-HTTP local runs).
        trusted_proxy_hops: Reverse proxies whose ``X-Forwarded-For`` entries are trusted.
        session_secret_env_var: Environment variable holding the session secret.
        argon2: Password-hash cost.
        throttle: Failed-attempt limit.
    """

    signup_open: bool
    password_min_length: int
    password_max_length: int
    session_idle_minutes: int
    session_absolute_days: int
    verification_token_hours: int
    reset_token_minutes: int
    cookie_name: str
    cookie_secure: bool
    trusted_proxy_hops: int
    session_secret_env_var: str
    argon2: Argon2Settings
    throttle: ThrottleSettings

    @property
    def session_idle_seconds(self) -> int:
        """The idle lifetime in seconds."""
        return self.session_idle_minutes * _MINUTES_PER_HOUR

    @property
    def session_absolute_seconds(self) -> int:
        """The absolute lifetime in seconds."""
        return self.session_absolute_days * _MINUTES_PER_DAY * _MINUTES_PER_HOUR


def _argon2(table: dict[str, object]) -> Argon2Settings:
    name = f"{_NAME}.argon2"
    raw = subtable(table, "argon2", _NAME)
    values = Argon2Settings(
        time_cost=require_int(raw, "time_cost", minimum=1, name=name),
        memory_cost_kib=require_int(raw, "memory_cost_kib", minimum=8, name=name),
        parallelism=require_int(raw, "parallelism", minimum=1, name=name),
    )
    if values.memory_cost_kib < _MIN_ARGON2_MEMORY_PER_LANE_KIB * values.parallelism:
        raise ValueError(f"{name}.memory_cost_kib must be at least 8 KiB per lane (parallelism)")
    return values


def _throttle(table: dict[str, object]) -> ThrottleSettings:
    name = f"{_NAME}.throttle"
    raw = subtable(table, "throttle", _NAME)
    return ThrottleSettings(
        attempts=require_int(raw, "attempts", minimum=1, name=name),
        window_minutes=require_int(raw, "window_minutes", minimum=1, name=name),
    )


def _positive(table: dict[str, object], key: str) -> int:
    return require_int(table, key, minimum=1, name=_NAME)


def _password_lengths(table: dict[str, object]) -> tuple[int, int]:
    smallest = require_int(table, "password_min_length", minimum=1, name=_NAME)
    largest = require_int(table, "password_max_length", minimum=1, name=_NAME)
    if smallest > largest:
        raise ValueError(f"{_NAME}.password_min_length must not exceed password_max_length")
    return smallest, largest


def _secure_cookie(table: dict[str, object], path: Path | None) -> bool:
    secure = require_bool(table, "cookie_secure", _NAME)
    if not secure and load_telemetry_settings(path).environment == _PRODUCTION:
        raise ValueError(
            f"{_NAME}.cookie_secure must be true when telemetry.environment is production",
        )
    return secure


def load_auth_settings(path: Path | None = None) -> AuthSettings:
    """Load and validate the account settings.

    Args:
        path: Settings file; defaults to the ``settings.toml`` shipped in ``config/``.

    Returns:
        The validated settings (session idle in minutes, absolute in days, token lifetimes in
        hours and minutes as named).

    Raises:
        FileNotFoundError: If the settings file does not exist.
        ValueError: If a key is missing or invalid; the message names the key.
    """
    table = section(read_toml(path), _NAME)
    smallest, largest = _password_lengths(table)
    return AuthSettings(
        signup_open=require_bool(table, "signup_open", _NAME),
        password_min_length=smallest,
        password_max_length=largest,
        session_idle_minutes=_positive(table, "session_idle_minutes"),
        session_absolute_days=_positive(table, "session_absolute_days"),
        verification_token_hours=_positive(table, "verification_token_hours"),
        reset_token_minutes=_positive(table, "reset_token_minutes"),
        cookie_name=require_str(table, "cookie_name", _NAME).strip(),
        cookie_secure=_secure_cookie(table, path),
        trusted_proxy_hops=require_int(table, "trusted_proxy_hops", minimum=0, name=_NAME),
        session_secret_env_var=require_str(table, "session_secret_env_var", _NAME).strip(),
        argon2=_argon2(table),
        throttle=_throttle(table),
    )


@lru_cache(maxsize=1)
def get_auth_settings() -> AuthSettings:
    """Return the cached account settings from the default file."""
    return load_auth_settings()
