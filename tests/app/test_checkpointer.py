"""Tests for the checkpointer's lifetime (a fake pool and saver; no database)."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager

import pytest

from app.checkpointer import (  # pyright: ignore[reportPrivateUsage]
    SetupLock,
    _connection_kwargs,  # pyright: ignore[reportPrivateUsage]
    open_checkpointer,
)
from config.database import DatabaseSettings

pytestmark = pytest.mark.anyio

SETTINGS = DatabaseSettings(
    url_env_var="X",
    pool_size=3,
    pool_timeout_seconds=4.0,
    statement_timeout_seconds=12.5,
    health_timeout_seconds=1.0,
    turn_lease_seconds=300.0,
    thread_retention_days=30,
    purge_interval_minutes=60,
    setup_lock_timeout_seconds=60.0,
    setup_lock_poll_seconds=0.05,
)
URL = "postgresql+psycopg://ecofate:s3cr3t@db:5432/ecofate"  # pragma: allowlist secret


def _return(pool: FakePool) -> Callable[[str, DatabaseSettings, str | None], FakePool]:
    def factory(_url: str, _settings: DatabaseSettings, _path: str | None) -> FakePool:
        return pool

    return factory


def _recording_lock(events: list[str]) -> SetupLock:
    """A setup lock that records when it is taken and released (no database)."""

    @asynccontextmanager
    async def lock(
        _url: str,
        _settings: DatabaseSettings,
        _path: str | None,
    ) -> AsyncGenerator[None]:
        events.append("lock")
        try:
            yield
        finally:
            events.append("unlock")

    return lock


class FakePool:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.opened_with: dict[str, object] = {}

    async def open(self, wait: bool = False, timeout: float = 30.0) -> None:
        self.opened_with = {"wait": wait, "timeout": timeout}
        self.events.append("open")

    async def close(self) -> None:
        self.events.append("close")


class FakeSaver:
    def __init__(self, pool: FakePool) -> None:
        self.pool = pool
        self.setups = 0

    async def setup(self) -> None:
        self.setups += 1
        self.pool.events.append("setup")


async def test_pool_is_opened_set_up_under_the_lock_and_closed() -> None:
    pools: list[FakePool] = []
    seen: list[tuple[str, str | None]] = []

    def pool_factory(url: str, _settings: DatabaseSettings, path: str | None) -> FakePool:
        seen.append((url, path))
        pools.append(FakePool())
        return pools[0]

    async with open_checkpointer(
        URL,
        SETTINGS,
        search_path="s1",
        pool_factory=pool_factory,
        saver_factory=FakeSaver,
        setup_lock=lambda url, settings, path: _recording_lock(pools[0].events)(
            url,
            settings,
            path,
        ),
    ) as saver:
        assert isinstance(saver, FakeSaver)
        assert saver.setups == 1
        assert pools[0].events == ["open", "lock", "setup", "unlock"]
    assert pools[0].events == ["open", "lock", "setup", "unlock", "close"]
    assert pools[0].opened_with == {"wait": True, "timeout": 4.0}
    assert seen == [(URL, "s1")]


async def test_the_lock_gets_the_url_settings_and_schema() -> None:
    pool = FakePool()
    calls: list[tuple[str, DatabaseSettings, str | None]] = []

    @asynccontextmanager
    async def lock(url: str, settings: DatabaseSettings, path: str | None) -> AsyncGenerator[None]:
        calls.append((url, settings, path))
        yield

    async with open_checkpointer(
        URL,
        SETTINGS,
        search_path="s2",
        pool_factory=_return(pool),
        saver_factory=FakeSaver,
        setup_lock=lock,
    ):
        pass
    assert calls == [(URL, SETTINGS, "s2")]


async def test_pool_is_closed_when_the_body_raises() -> None:
    pool = FakePool()
    with pytest.raises(RuntimeError, match="boom"):
        async with open_checkpointer(
            URL,
            SETTINGS,
            pool_factory=_return(pool),
            saver_factory=FakeSaver,
            setup_lock=_recording_lock(pool.events),
        ):
            raise RuntimeError("boom")
    assert pool.events == ["open", "lock", "setup", "unlock", "close"]


async def test_lock_is_released_and_pool_closed_when_setup_fails() -> None:
    pool = FakePool()

    class BrokenSaver(FakeSaver):
        async def setup(self) -> None:
            raise RuntimeError("no tables")

    with pytest.raises(RuntimeError, match="no tables"):
        async with open_checkpointer(
            URL,
            SETTINGS,
            pool_factory=_return(pool),
            saver_factory=BrokenSaver,
            setup_lock=_recording_lock(pool.events),
        ):
            pytest.fail("must not be reached")
    assert pool.events == ["open", "lock", "unlock", "close"]


async def test_a_failing_lock_never_runs_setup_and_closes_the_pool() -> None:
    pool = FakePool()

    @asynccontextmanager
    async def unavailable(
        _url: str,
        _settings: DatabaseSettings,
        _path: str | None,
    ) -> AsyncGenerator[None]:
        raise TimeoutError("lock wait timed out")
        yield

    with pytest.raises(TimeoutError):
        async with open_checkpointer(
            URL,
            SETTINGS,
            pool_factory=_return(pool),
            saver_factory=FakeSaver,
            setup_lock=unavailable,
        ):
            pytest.fail("must not be reached")
    assert pool.events == ["open", "close"]


def test_connection_kwargs_follow_the_library_and_set_the_statement_timeout() -> None:
    kwargs = _connection_kwargs(SETTINGS, None)
    assert kwargs["autocommit"] is True
    assert kwargs["prepare_threshold"] == 0
    assert kwargs["options"] == "-c statement_timeout=12500"
    assert "search_path=abc" in _connection_kwargs(SETTINGS, "abc")["options"]
