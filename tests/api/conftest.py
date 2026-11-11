"""Shared fixtures: an app wired to in-memory stores and a fake keychain, never the real ones.

``client`` is signed in as ``user`` (a verified, ordinary account), so the tests of the chat,
facility and settings routes exercise them as a signed-in person; ``anonymous`` is the same app
with no cookie.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.main import create_app
from api.services.auth.runtime import AuthRuntime
from config.ui import UiSettings, get_ui_settings
from storage.account_model import User
from storage.keys import ThreadKey
from tests.api.auth_support import SECRET, fast_settings
from tests.fakes import InMemoryThreadStore, KeyBench
from tests.fakes_accounts import FakeClock, RecordingMailer, in_memory_accounts

ORIGIN = "http://127.0.0.1:8000"


@pytest.fixture
def store() -> KeyBench:
    return KeyBench()


@pytest.fixture
def settings(tmp_path: Path) -> UiSettings:
    return replace(get_ui_settings(), frontend_dist=tmp_path / "dist")


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def mailer() -> RecordingMailer:
    return RecordingMailer()


@pytest.fixture
def threads() -> InMemoryThreadStore:
    return InMemoryThreadStore()


@pytest.fixture
def app(
    store: KeyBench,
    settings: UiSettings,
    clock: FakeClock,
    mailer: RecordingMailer,
    threads: InMemoryThreadStore,
    monkeypatch: pytest.MonkeyPatch,
) -> FastAPI:
    monkeypatch.setattr("api.main.get_auth_settings", fast_settings)  # a cheap password hash
    api = create_app(
        settings,
        threads=threads,
        accounts=in_memory_accounts(clock),
        mailer=mailer,
        session_secret=SECRET,
        keys=store.services,
    )
    return api


def runtime_of(app: FastAPI) -> AuthRuntime:
    """The account services of a started app."""
    return app.state.auth  # type: ignore[no-any-return]


def make_user(app: FastAPI, email: str = "user@example.com", *, admin: bool = False) -> User:
    """A verified account (an administrator when asked) made straight in the store."""
    from storage.account_model import Role

    role = Role.ADMIN if admin else Role.USER
    created = asyncio.run(
        runtime_of(app).accounts.users.create(email, "x", role=role, verified=True),
    )
    assert created is not None
    return created


def session_cookie(app: FastAPI, user: User) -> str:
    """A live session for ``user`` (the cookie value)."""
    return asyncio.run(runtime_of(app).sessions.start(user.id, None))


def sign_in_as(app: FastAPI, client: TestClient, user: User) -> None:
    """Give ``client`` a session cookie for ``user``."""
    client.cookies.set(runtime_of(app).sessions.cookie_name, session_cookie(app, user))


def signed_in(
    app: FastAPI,
    *,
    email: str = "user@example.com",
    admin: bool = False,
    raise_server_exceptions: bool = True,
) -> TestClient:
    """A client (not started) signed in as ``email``, made verified (an admin when asked) if new."""
    client = TestClient(app, base_url=ORIGIN, raise_server_exceptions=raise_server_exceptions)
    known = asyncio.run(runtime_of(app).accounts.users.by_email(email))
    sign_in_as(app, client, known or make_user(app, email, admin=admin))
    return client


@pytest.fixture
def anonymous(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, base_url=ORIGIN, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture
def user(app: FastAPI, anonymous: TestClient) -> User:
    return make_user(app)


@pytest.fixture
def client(app: FastAPI, anonymous: TestClient, user: User) -> TestClient:
    sign_in_as(app, anonymous, user)
    return anonymous


@pytest.fixture
def admin_client(app: FastAPI, anonymous: TestClient) -> TestClient:
    """The app's client signed in as an administrator (for the server-wide key routes)."""
    sign_in_as(app, anonymous, make_user(app, "admin@example.com", admin=True))
    return anonymous


@pytest.fixture
def thread_key(user: User) -> Callable[[str], ThreadKey]:
    """Builds the key of one of the default user's threads: ``thread_key("t1")``."""
    return lambda thread_id: ThreadKey(user.id, thread_id)
