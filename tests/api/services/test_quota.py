"""Tests for ``QuotaService`` over an in-memory store (the SQL is tested with PostgreSQL)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from api.services.quota import QuotaService
from config.limits import LimitSettings, get_limit_settings
from storage.account_model import Role, User
from tests.fakes_quota import InMemoryQuota

pytestmark = pytest.mark.anyio
NOW = datetime(2026, 3, 5, 18, 30, tzinfo=UTC)


def _user(role: Role = Role.USER, number: int = 1) -> User:
    return User(
        id=UUID(int=number),
        email=f"u{number}@example.test",
        password_hash="x",
        role=role,
        verified_at=NOW,
        created_at=NOW,
    )


def _service(store: InMemoryQuota, **changes: object) -> QuotaService:
    settings: LimitSettings = replace(get_limit_settings(), daily_turns_per_user=2, **changes)  # type: ignore[arg-type]
    return QuotaService(store, settings, now=lambda: NOW)


async def test_turns_are_accepted_until_the_limit_then_refused() -> None:
    service = _service(InMemoryQuota())
    results = [await service.admit(_user()) for _ in range(3)]
    assert [(r.accepted, r.counted) for r in results] == [
        (True, True),
        (True, True),
        (False, False),
    ]


async def test_a_refusal_carries_the_next_midnight_utc() -> None:
    service = _service(InMemoryQuota())
    for _ in range(2):
        await service.admit(_user())
    reset = (await service.admit(_user())).reset
    assert reset is not None
    assert reset.at == datetime(2026, 3, 6, tzinfo=UTC)
    assert reset.seconds == 5 * 3600 + 30 * 60


async def test_the_reset_just_before_midnight_is_at_least_one_second() -> None:
    almost = datetime(2026, 3, 5, 23, 59, 59, 900_000, tzinfo=UTC)
    service = QuotaService(InMemoryQuota(), get_limit_settings(), now=lambda: almost)
    assert service.reset().seconds == 1


async def test_a_disabled_quota_never_counts_or_refuses() -> None:
    store = InMemoryQuota()
    service = _service(store, enabled=False)
    results = [await service.admit(_user()) for _ in range(5)]
    assert all(r.accepted and not r.counted for r in results)
    assert store.calls == []
    assert await service.standing(_user()) is None


async def test_an_exempt_admin_is_not_counted_and_a_user_still_is() -> None:
    store = InMemoryQuota()
    service = _service(store, admin_exempt=True)
    admin = _user(Role.ADMIN, 2)
    admitted = [await service.admit(admin) for _ in range(5)]
    assert all(a.accepted and not a.counted for a in admitted)
    assert store.calls == []
    for _ in range(2):
        await service.admit(_user())
    assert (await service.admit(_user())).accepted is False


async def test_an_admin_is_counted_when_not_exempt() -> None:
    service = _service(InMemoryQuota(), admin_exempt=False)
    admin = _user(Role.ADMIN, 2)
    results = [await service.admit(admin) for _ in range(3)]
    assert [r.accepted for r in results] == [True, True, False]


async def test_standing_reports_limit_used_and_remaining() -> None:
    service = _service(InMemoryQuota())
    await service.admit(_user())
    standing = await service.standing(_user())
    assert standing is not None
    assert (standing.limit, standing.used, standing.remaining) == (2, 1, 1)


async def test_remaining_is_never_negative_after_the_limit_was_lowered() -> None:
    store = InMemoryQuota()
    for _ in range(5):
        await store.consume(_user().id, 10)
    standing = await _service(store).standing(_user())
    assert standing is not None
    assert (standing.used, standing.remaining) == (5, 0)


async def test_standing_shows_only_the_users_own_count() -> None:
    service = _service(InMemoryQuota())
    await service.admit(_user(number=1))
    other = await service.standing(_user(number=2))
    assert other is not None
    assert other.used == 0


async def test_a_refund_gives_a_counted_turn_back_once() -> None:
    store = InMemoryQuota()
    service = _service(store)
    await service.admit(_user())
    assert await service.refund(_user().id, "turn-1") is True
    assert await service.refund(_user().id, "turn-1") is False
    standing = await service.standing(_user())
    assert standing is not None
    assert standing.used == 0
