"""Tests for the checkpointer's lifetime (a fake pool and saver; no database)."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from app.checkpointer import _connection_kwargs, open_checkpointer  # pyright: ignore[reportPrivateUsage]
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
)
URL = "postgresql+psycopg://ecofate:s3cr3t@db:5432/ecofate"  # pragma: allowlist secret


def _return(pool: FakePool) -> Callable[[str, DatabaseSettings, str | None], FakePool]:
    def factory(_url: str, _settings: DatabaseSettings, _path: str | None) -> FakePool:
        return pool

    return factory


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


async def test_pool_is_opened_set_up_and_closed() -> None:
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
    ) as saver:
        assert isinstance(saver, FakeSaver)
        assert saver.setups == 1
        assert pools[0].events == ["open", "setup"]
    assert pools[0].events == ["open", "setup", "close"]
    assert pools[0].opened_with == {"wait": True, "timeout": 4.0}
    assert seen == [(URL, "s1")]


async def test_pool_is_closed_when_the_body_raises() -> None:
    pool = FakePool()
    with pytest.raises(RuntimeError, match="boom"):
        async with open_checkpointer(
            URL,
            SETTINGS,
            pool_factory=_return(pool),
            saver_factory=FakeSaver,
        ):
            raise RuntimeError("boom")
    assert pool.events[-1] == "close"


async def test_pool_is_closed_when_setup_fails() -> None:
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
        ):
            pytest.fail("must not be reached")
    assert pool.events == ["open", "close"]


def test_connection_kwargs_follow_the_library_and_set_the_statement_timeout() -> None:
    kwargs = _connection_kwargs(SETTINGS, None)
    assert kwargs["autocommit"] is True
    assert kwargs["prepare_threshold"] == 0
    assert kwargs["options"] == "-c statement_timeout=12500"
    assert "search_path=abc" in _connection_kwargs(SETTINGS, "abc")["options"]
