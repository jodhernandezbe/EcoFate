"""Tests for the database health check (fake engines; no database)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import pytest

from storage.health import database_answers

pytestmark = pytest.mark.anyio


class _Connection:
    def __init__(self) -> None:
        self.statements: list[str] = []

    async def execute(self, statement: object) -> None:
        self.statements.append(str(statement))


class AnsweringEngine:
    def __init__(self) -> None:
        self.connection = _Connection()

    @asynccontextmanager
    async def connect(self) -> AsyncGenerator[Any]:
        yield self.connection


class RefusingEngine:
    @asynccontextmanager
    async def connect(self) -> AsyncGenerator[Any]:
        raise OSError("connection to server at db (10.0.0.5) refused for user ecofate")
        yield  # pragma: no cover


class HangingEngine:
    @asynccontextmanager
    async def connect(self) -> AsyncGenerator[Any]:
        await asyncio.sleep(3600)
        yield  # pragma: no cover


async def test_an_answering_database_is_healthy() -> None:
    engine = AnsweringEngine()
    assert await database_answers(engine, 1.0)
    assert engine.connection.statements == ["SELECT 1"]


async def test_a_refusing_database_is_unhealthy_and_its_message_is_not_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="storage.health"):
        assert not await database_answers(RefusingEngine(), 1.0)
    assert "OSError" in caplog.text
    assert "ecofate" not in caplog.text
    assert "10.0.0.5" not in caplog.text


async def test_a_hanging_database_is_unhealthy_within_the_timeout() -> None:
    loop = asyncio.get_running_loop()
    started = loop.time()
    assert not await database_answers(HangingEngine(), 0.05)
    assert loop.time() - started < 1.0
