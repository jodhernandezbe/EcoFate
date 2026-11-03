"""A fake Logfire query API for the service and router tests: it records what it was asked."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from pydantic import SecretStr

from api.services.monitoring.client import LogfireQuery, Project
from api.services.monitoring.service import QueryOpener
from config.telemetry import TelemetrySettings
from tests.api.services.monitoring.factories import PROJECT


class FakeQuery:
    """Answers every statement with ``rows``, or raises ``failure``; remembers the requests."""

    def __init__(
        self,
        rows: Sequence[Mapping[str, object]] | None = None,
        failure: Exception | None = None,
    ) -> None:
        self.rows_to_return = list(rows or [])
        self.failure = failure
        self.statements: list[tuple[str, int]] = []
        self.tokens: list[str] = []

    async def project(self) -> Project:
        if self.failure:
            raise self.failure
        return PROJECT

    async def rows(self, sql: str, window_hours: int) -> list[Mapping[str, object]]:
        if self.failure:
            raise self.failure
        self.statements.append((sql, window_hours))
        return self.rows_to_return


def opener(query: FakeQuery) -> QueryOpener:
    """An opener that hands out ``query`` and notes the token it was opened with."""

    @asynccontextmanager
    async def open_query(
        token: SecretStr,
        settings: TelemetrySettings,
    ) -> AsyncGenerator[LogfireQuery]:
        query.tokens.append(token.get_secret_value())
        yield query

    def opened(
        token: SecretStr,
        settings: TelemetrySettings,
    ) -> AbstractAsyncContextManager[LogfireQuery]:
        return open_query(token, settings)

    return opened
