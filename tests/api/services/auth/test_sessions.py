"""Sessions: cookie flags, rotation, expiry and revocation."""

from __future__ import annotations

from typing import cast

import pytest

from tests.api.auth_support import SECRET, fast_settings, make_auth
from tests.fakes_accounts import InMemorySessions

pytestmark = pytest.mark.anyio


async def test_the_cookie_is_httponly_lax_and_secure_by_setting() -> None:
    secure = make_auth(fast_settings(cookie_secure=True)).sessions.cookie()
    assert (secure["httponly"], secure["secure"], secure["samesite"], secure["path"]) == (
        True,
        True,
        "lax",
        "/",
    )
    assert make_auth(fast_settings(cookie_secure=False)).sessions.cookie()["secure"] is False


async def test_a_started_session_resolves_and_is_stored_only_as_a_hash() -> None:
    kit = make_auth()
    user = await kit.accounts.users.create("a@example.com", "h")
    assert user is not None
    token = await kit.sessions.start(user.id, None)
    assert (await kit.sessions.resolve(token)) == user
    stored = list(cast(InMemorySessions, kit.accounts.sessions).rows)
    assert len(stored) == 1 and token not in stored[0] and SECRET.decode() not in stored[0]
    assert await kit.sessions.resolve(stored[0]) is None  # a stored hash is not a cookie


async def test_starting_a_session_ends_the_one_presented_before() -> None:
    kit = make_auth()
    user = await kit.accounts.users.create("a@example.com", "h")
    assert user is not None
    planted = await kit.sessions.start(user.id, None)
    fresh = await kit.sessions.start(user.id, planted)
    assert fresh != planted
    assert await kit.sessions.resolve(planted) is None
    assert await kit.sessions.resolve(fresh) == user


async def test_an_unknown_or_missing_cookie_resolves_to_nobody() -> None:
    kit = make_auth()
    assert await kit.sessions.resolve(None) is None
    assert await kit.sessions.resolve("not a token") is None
    assert await kit.sessions.resolve("a" * 43) is None


async def test_a_session_ends_after_the_idle_time_without_a_request() -> None:
    kit = make_auth()
    user = await kit.accounts.users.create("a@example.com", "h")
    assert user is not None
    token = await kit.sessions.start(user.id, None)
    kit.clock.advance(kit.settings.session_idle_seconds - 1)
    assert await kit.sessions.resolve(token) == user  # this request moves the idle expiry on
    kit.clock.advance(kit.settings.session_idle_seconds - 1)
    assert await kit.sessions.resolve(token) == user
    kit.clock.advance(kit.settings.session_idle_seconds + 1)
    assert await kit.sessions.resolve(token) is None
    assert cast(InMemorySessions, kit.accounts.sessions).rows == {}


async def test_a_session_ends_at_the_absolute_lifetime_however_active() -> None:
    kit = make_auth(fast_settings(session_idle_minutes=60, session_absolute_days=1))
    user = await kit.accounts.users.create("a@example.com", "h")
    assert user is not None
    token = await kit.sessions.start(user.id, None)
    for _ in range(40):
        kit.clock.advance(3000)
        if await kit.sessions.resolve(token) is None:
            break
    assert await kit.sessions.resolve(token) is None


async def test_end_revokes_one_session_and_end_all_keeps_the_named_one() -> None:
    kit = make_auth()
    user = await kit.accounts.users.create("a@example.com", "h")
    other = await kit.accounts.users.create("b@example.com", "h")
    assert user is not None and other is not None
    first, second, third = [await kit.sessions.start(user.id, None) for _ in range(3)]
    theirs = await kit.sessions.start(other.id, None)
    await kit.sessions.end(first)
    assert await kit.sessions.resolve(first) is None
    assert await kit.sessions.end_all(user.id, keep=second) == 1
    assert await kit.sessions.resolve(second) == user and await kit.sessions.resolve(third) is None
    assert await kit.sessions.resolve(theirs) == other
    await kit.sessions.end(None)
    await kit.sessions.end("garbage")
