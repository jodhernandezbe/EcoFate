"""Time-dependent rules of the in-memory thread store (lease expiry, idle purge).

The rest of the contract is in ``test_thread_store_contract.py``; the PostgreSQL versions of
these rules are in ``tests/storage/test_postgres_threads.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tests.fakes import InMemoryThreadStore

pytestmark = pytest.mark.anyio


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 1, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


async def test_an_expired_lease_can_be_claimed() -> None:
    clock = Clock()
    store = InMemoryThreadStore(lease=timedelta(minutes=5), clock=clock)
    assert await store.claim("t")
    clock.now += timedelta(minutes=4)
    assert not await store.claim("t")
    clock.now += timedelta(minutes=2)
    assert not await store.running("t")
    assert await store.claim("t")


async def test_purge_deletes_old_idle_threads_and_keeps_busy_and_recent_ones() -> None:
    clock = Clock()
    store = InMemoryThreadStore(lease=timedelta(days=60), clock=clock)
    await store.touch("old")
    await store.claim("old-busy")
    clock.now += timedelta(days=40)
    await store.touch("recent")
    purged = await store.purge_idle(timedelta(days=30))
    assert purged == ["old"]
    assert not await store.holds("old")
    assert await store.holds("old-busy")
    assert await store.holds("recent")
