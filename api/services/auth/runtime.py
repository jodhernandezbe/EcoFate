"""The account services of one running app, built from their stores."""

from __future__ import annotations

from dataclasses import dataclass

from api.services.auth.flows import AuthParts, AuthService
from api.services.auth.mailer import Mailer
from api.services.auth.passwords import Passwords
from api.services.auth.sessions import SessionService
from api.services.auth.stores import Accounts
from api.services.auth.throttle import Throttle
from api.services.auth.tokens import TokenHasher, TokenService
from api.services.threads import ThreadStore
from config.auth import AuthSettings


@dataclass(frozen=True)
class AuthRuntime:
    """What the account routes and the session guard use.

    Attributes:
        service: The account flows.
        sessions: Resolves the session cookie.
        accounts: The account stores (the monitoring view resolves emails through them).
        mailer: Sends the emails the flows return (after the response).
        settings: Cookie name and proxy hops.
    """

    service: AuthService
    sessions: SessionService
    accounts: Accounts
    mailer: Mailer
    settings: AuthSettings


def build_auth_runtime(
    *,
    accounts: Accounts,
    threads: ThreadStore,
    mailer: Mailer,
    secret: bytes,
    settings: AuthSettings,
    base_url: str,
) -> AuthRuntime:
    """Wire the services over the stores, the session secret and the mailer."""
    hasher = TokenHasher(secret)
    sessions = SessionService(accounts.sessions, hasher, settings)
    parts = AuthParts(
        accounts=accounts,
        passwords=Passwords(settings),
        tokens=TokenService(accounts.tokens, hasher, settings),
        sessions=sessions,
        throttle=Throttle(accounts.attempts, settings.throttle),
        threads=threads,
        settings=settings,
        base_url=base_url,
    )
    return AuthRuntime(AuthService(parts), sessions, accounts, mailer, settings)
