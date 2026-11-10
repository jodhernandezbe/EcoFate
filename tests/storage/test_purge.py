"""Tests for the periodic purge of idle threads (a fake store; no database)."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from uuid import UUID

import pytest

from storage.keys import ThreadKey
from storage.purge import purge_once, purge_periodically
from tests.storage.test_engine import SETTINGS

OWNER = UUID(int=1)
pytestmark = pytest.mark.anyio


class Store:
    def __init__(self, purged: list[ThreadKey] | None = None, *, fail: bool = False) -> None:
        self.calls: list[timedelta] = []
        self.purged = purged or []
        self.fail = fail

    async def purge_idle(self, older_than: timedelta) -> list[ThreadKey]:
        self.calls.append(older_than)
        if self.fail:
            raise OSError("database down")
        return self.purged


async def test_purge_uses_the_retention_in_days() -> None:
    store = Store([ThreadKey(OWNER, "a"), ThreadKey(OWNER, "b")])
    assert await purge_once(store, SETTINGS) == 2
    assert store.calls == [timedelta(days=SETTINGS.thread_retention_days)]


async def test_a_database_failure_is_logged_and_the_loop_survives(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="storage.purge"):
        assert await purge_once(Store(fail=True), SETTINGS) == 0
    assert "OSError" in caplog.text


async def test_an_unexpected_error_is_not_swallowed() -> None:
    class Broken(Store):
        async def purge_idle(self, older_than: timedelta) -> list[ThreadKey]:
            raise KeyError("bug")

    with pytest.raises(KeyError):
        await purge_once(Broken(), SETTINGS)


async def test_the_loop_purges_then_sleeps_the_interval_until_cancelled() -> None:
    store = Store()
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await purge_periodically(store, SETTINGS, sleep)
    assert len(store.calls) == 2
    assert sleeps == [SETTINGS.purge_interval_minutes * 60] * 2
