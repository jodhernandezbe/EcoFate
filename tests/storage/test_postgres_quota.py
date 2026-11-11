"""PostgreSQL behaviour of the daily turn quota repository and the 0004 migration
(``postgres`` marker). Each test works in its own migrated schema (``tests/postgres.py``)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import literal, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from storage.keys import ThreadKey
from storage.quota import QuotaRepository
from storage.turns import TurnRepository
from tests.postgres import Database, add_user, database

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]
LIMIT = 3
FIRST = date(2026, 1, 1)


@dataclass
class Quota:
    db: Database
    repo: QuotaRepository
    user: UUID

    def on(self, day: date) -> QuotaRepository:
        """The repository as it behaves on ``day`` (the database clock fixed)."""
        return QuotaRepository(async_sessionmaker(self.db.engine), literal(day))


@pytest.fixture
async def quota() -> AsyncGenerator[Quota]:
    async with database() as db:
        user = await add_user(db.engine, uuid4())
        yield Quota(db, QuotaRepository(async_sessionmaker(db.engine)), user)


async def _usage_rows(engine: AsyncEngine) -> list[tuple[UUID, date, int]]:
    async with engine.connect() as connection:
        rows = await connection.execute(text("SELECT user_id, day, turns FROM daily_turn_usage"))
        return [(row[0], row[1], row[2]) for row in rows]


async def test_counts_up_to_the_limit_then_refuses(quota: Quota) -> None:
    results = [await quota.repo.consume(quota.user, LIMIT) for _ in range(LIMIT + 2)]
    assert results == [1, 2, 3, None, None]
    assert await quota.repo.usage(quota.user) == LIMIT


async def test_a_refused_turn_is_not_counted(quota: Quota) -> None:
    for _ in range(LIMIT + 1):
        await quota.repo.consume(quota.user, LIMIT)
    assert [row[2] for row in await _usage_rows(quota.db.engine)] == [LIMIT]


async def test_five_concurrent_turns_with_one_left_accept_exactly_one(quota: Quota) -> None:
    for _ in range(LIMIT - 1):
        await quota.repo.consume(quota.user, LIMIT)
    results = await asyncio.gather(*(quota.repo.consume(quota.user, LIMIT) for _ in range(5)))
    assert sorted(result for result in results if result is not None) == [LIMIT]
    assert results.count(None) == 4


async def test_a_new_utc_day_accepts_again(quota: Quota) -> None:
    for _ in range(LIMIT):
        await quota.on(FIRST).consume(quota.user, LIMIT)
    assert await quota.on(FIRST).consume(quota.user, LIMIT) is None
    assert await quota.on(FIRST + timedelta(days=1)).consume(quota.user, LIMIT) == 1
    assert await quota.on(FIRST).usage(quota.user) == LIMIT


async def test_users_are_counted_apart(quota: Quota) -> None:
    other = await add_user(quota.db.engine, uuid4())
    for _ in range(LIMIT):
        await quota.repo.consume(quota.user, LIMIT)
    assert await quota.repo.consume(other, LIMIT) == 1
    assert await quota.repo.usage(other) == 1


async def test_the_day_is_the_database_utc_date(quota: Quota) -> None:
    await quota.repo.consume(quota.user, LIMIT)
    async with quota.db.engine.connect() as connection:
        expected = (
            await connection.execute(text("SELECT (now() AT TIME ZONE 'UTC')::date"))
        ).scalar_one()
    assert [row[1] for row in await _usage_rows(quota.db.engine)] == [expected]


async def _begun(quota: Quota, thread: str = "t1") -> str:
    turn = await TurnRepository(async_sessionmaker(quota.db.engine)).begin(
        ThreadKey(quota.user, thread),
    )
    assert turn is not None
    return turn.id


async def test_a_refund_gives_the_turn_back_once(quota: Quota) -> None:
    await quota.repo.consume(quota.user, LIMIT)
    await quota.repo.consume(quota.user, LIMIT)
    turn_id = await _begun(quota)
    assert await quota.repo.refund(quota.user, turn_id) is True
    assert await quota.repo.refund(quota.user, turn_id) is False
    assert await quota.repo.usage(quota.user) == 1


async def test_a_refund_never_goes_below_zero(quota: Quota) -> None:
    turn_id = await _begun(quota)
    assert await quota.repo.refund(quota.user, turn_id) is True
    assert await quota.repo.usage(quota.user) == 0


async def test_another_users_turn_cannot_be_refunded(quota: Quota) -> None:
    other = await add_user(quota.db.engine, uuid4())
    await quota.repo.consume(quota.user, LIMIT)
    turn_id = await _begun(quota)
    assert await quota.repo.refund(other, turn_id) is False
    assert await quota.repo.usage(quota.user) == 1


async def test_an_unknown_turn_is_not_refunded(quota: Quota) -> None:
    await quota.repo.consume(quota.user, LIMIT)
    assert await quota.repo.refund(quota.user, "no-such-turn") is False
    assert await quota.repo.usage(quota.user) == 1


async def test_purge_deletes_only_rows_older_than_the_retention(quota: Quota) -> None:
    for offset in (0, 5, 40):
        await quota.on(FIRST + timedelta(days=offset)).consume(quota.user, LIMIT)
    today = quota.on(FIRST + timedelta(days=40))
    assert await today.purge_usage(timedelta(days=35)) == 1
    assert sorted(row[1] for row in await _usage_rows(quota.db.engine)) == [
        FIRST + timedelta(days=5),
        FIRST + timedelta(days=40),
    ]


async def test_deleting_the_user_deletes_the_rows(quota: Quota) -> None:
    await quota.repo.consume(quota.user, LIMIT)
    async with quota.db.engine.begin() as connection:
        await connection.execute(text("DELETE FROM users WHERE id = :id"), {"id": quota.user})
    assert await _usage_rows(quota.db.engine) == []
