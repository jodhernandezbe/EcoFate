"""Tests for opening the database at start-up (fake engines; no database)."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from typing import Any

import pytest

from api.services import database as subject
from tests.storage.test_engine import SETTINGS, URL

pytestmark = pytest.mark.anyio
ENV = {SETTINGS.url_env_var: URL}


class _Connection:
    def __init__(self, at_head: bool) -> None:
        self.at_head = at_head

    async def run_sync(self, function: Callable[..., Any]) -> bool:
        return self.at_head


class FakeEngine:
    def __init__(self, *, at_head: bool = True, refuse: bool = False) -> None:
        self.at_head, self.refuse, self.disposed = at_head, refuse, False

    @asynccontextmanager
    async def connect(self) -> AsyncGenerator[_Connection]:
        if self.refuse:
            raise OSError("could not connect as ecofate:s3cr3t")  # pragma: allowlist secret
        yield _Connection(self.at_head)

    async def dispose(self) -> None:
        self.disposed = True


def _use(monkeypatch: pytest.MonkeyPatch, engine: FakeEngine) -> list[str]:
    opened: list[str] = []

    @asynccontextmanager
    async def checkpointer(url: str, _settings: object) -> AsyncGenerator[object]:
        opened.append(url)
        yield object()

    def create_engine(_url: str, _settings: object) -> FakeEngine:
        return engine

    monkeypatch.setattr(subject, "create_engine", create_engine)
    monkeypatch.setattr(subject, "open_checkpointer", checkpointer)
    return opened


async def test_a_missing_url_stops_start_up_naming_the_variable() -> None:
    with pytest.raises(SystemExit) as stopped:
        async with subject.open_database({}, SETTINGS):
            pytest.fail("must not start")
    assert SETTINGS.url_env_var in str(stopped.value.code)


async def test_an_unreachable_database_names_make_migrate_and_not_the_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = FakeEngine(refuse=True)
    _use(monkeypatch, engine)
    with pytest.raises(SystemExit) as stopped:
        async with subject.open_database(ENV, SETTINGS):
            pytest.fail("must not start")
    message = str(stopped.value.code)
    assert "make migrate" in message
    assert "s3cr3t" not in message
    assert engine.disposed


async def test_a_database_behind_the_latest_migration_names_make_migrate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = FakeEngine(at_head=False)
    opened = _use(monkeypatch, engine)
    with pytest.raises(SystemExit) as stopped:
        async with subject.open_database(ENV, SETTINGS):
            pytest.fail("must not start")
    assert stopped.value.code == subject.NOT_MIGRATED
    assert opened == []  # the checkpointer is never opened
    assert engine.disposed


async def test_a_migrated_database_yields_the_store_and_is_closed_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = FakeEngine()
    opened = _use(monkeypatch, engine)
    async with subject.open_database(ENV, SETTINGS) as database:
        assert opened == [URL]
        assert database.threads is not None
        assert not engine.disposed
    assert engine.disposed
