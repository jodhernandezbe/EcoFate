"""Builds the auth services over in-memory stores, with cheap Argon2 settings, for unit tests."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from fastapi import FastAPI

from api.main import create_app
from api.services.auth.flows import AuthParts, AuthService
from api.services.auth.passwords import Passwords
from api.services.auth.sessions import SessionService
from api.services.auth.stores import Accounts
from api.services.auth.throttle import Throttle
from api.services.auth.tokens import TokenHasher, TokenService
from config.auth import Argon2Settings, AuthSettings, ThrottleSettings, get_auth_settings
from tests.fakes import InMemoryThreadStore
from tests.fakes_accounts import FakeClock, RecordingMailer, in_memory_accounts

SECRET = b"unit-test-session-secret-0123456789abcdef"  # pragma: allowlist secret
BASE_URL = "http://127.0.0.1:8000"
PASSWORD = "correct horse battery staple"  # pragma: allowlist secret
EMAIL = "Ana@Example.com"
NORMAL_EMAIL = "Ana@example.com"
ADDRESS = "203.0.113.7"


def fast_settings(**changes: object) -> AuthSettings:
    """The shipped settings with a cheap hash and a small throttle (so tests stay quick)."""
    base = replace(
        get_auth_settings(),
        argon2=Argon2Settings(time_cost=1, memory_cost_kib=8, parallelism=1),
        throttle=ThrottleSettings(attempts=3, window_minutes=10),
    )
    return replace(base, **changes)  # type: ignore[arg-type]


@dataclass
class AuthKit:
    """A wired auth service and the fakes behind it."""

    settings: AuthSettings
    clock: FakeClock
    accounts: Accounts
    mailer: RecordingMailer
    threads: InMemoryThreadStore
    passwords: Passwords
    tokens: TokenService
    sessions: SessionService
    throttle: Throttle
    service: AuthService


def make_auth(settings: AuthSettings | None = None) -> AuthKit:
    """A new service with empty stores."""
    chosen = settings or fast_settings()
    clock = FakeClock()
    accounts = in_memory_accounts(clock)
    hasher = TokenHasher(SECRET)
    passwords = Passwords(chosen)
    tokens = TokenService(accounts.tokens, hasher, chosen)
    sessions = SessionService(accounts.sessions, hasher, chosen)
    throttle = Throttle(accounts.attempts, chosen.throttle)
    threads = InMemoryThreadStore(clock=clock)
    parts = AuthParts(accounts, passwords, tokens, sessions, throttle, threads, chosen, BASE_URL)
    return AuthKit(
        chosen,
        clock,
        accounts,
        RecordingMailer(),
        threads,
        passwords,
        tokens,
        sessions,
        throttle,
        AuthService(parts),
    )


def token_in(body: str) -> str:
    """The token in the single link of an email body (after ``=`` in the URL fragment)."""
    link = next(line for line in body.splitlines() if line.startswith(BASE_URL))
    return link.split("=", 1)[1]


def build_app(*args: Any, **kwargs: Any) -> FastAPI:  # noqa: ANN401
    """``create_app`` with in-memory accounts, a recording mailer and a test secret filled in
    (for tests that build the app themselves)."""
    kwargs.setdefault("threads", InMemoryThreadStore())
    kwargs.setdefault("accounts", in_memory_accounts(FakeClock()))
    kwargs.setdefault("mailer", RecordingMailer())
    kwargs.setdefault("session_secret", SECRET)
    return create_app(*args, **kwargs)
