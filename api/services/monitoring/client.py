"""The Logfire query API as the monitoring service uses it: rows of a statement, and the project.

Every failure of the API becomes one of three exceptions the service turns into a state; their
messages are user-safe and never hold the token or the API's response.
"""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

import httpx
from logfire.query_client import (
    AsyncLogfireQueryClient,
    InfoRequestError,
    QueryExecutionError,
    QueryRequestError,
    UnexpectedResponseError,
)
from pydantic import SecretStr

from config.telemetry import TelemetrySettings

logger = logging.getLogger("api.monitoring")
_STATUS = re.compile(r"^Unexpected response status code (\d{3})")
_REFUSED = frozenset({401, 403})


class MonitoringUnavailableError(Exception):
    """Logfire could not be reached, timed out, rate-limited the call or failed it."""


class MonitoringUnauthorizedError(Exception):
    """Logfire refused the read token."""


@dataclass(frozen=True)
class Project:
    """The Logfire project the read token belongs to (for links to its traces)."""

    organization: str
    name: str


class LogfireQuery(Protocol):
    """What the service needs from Logfire; tests substitute a fake."""

    async def project(self) -> Project: ...

    async def rows(self, sql: str, window_hours: int) -> list[Mapping[str, object]]: ...


def _refused(error: Exception) -> bool:
    match = _STATUS.match(str(error)) if isinstance(error, UnexpectedResponseError) else None
    return match is not None and int(match.group(1)) in _REFUSED


def _translate(error: Exception) -> Exception:
    """The service-level exception for an API failure; the cause stays in the log only."""
    if _refused(error):
        return MonitoringUnauthorizedError("Logfire refused the read token.")
    logger.warning("Logfire query failed: %s", type(error).__name__)
    return MonitoringUnavailableError("Logfire could not be reached.")


_FAILURES = (
    httpx.HTTPError,
    InfoRequestError,
    QueryExecutionError,
    QueryRequestError,
    UnexpectedResponseError,
)


class _ApiQuery:
    def __init__(self, client: AsyncLogfireQueryClient, max_rows: int) -> None:
        self._client = client
        self._max_rows = max_rows

    async def project(self) -> Project:
        try:
            info = await self._client.info()
        except _FAILURES as error:
            raise _translate(error) from error
        return Project(info.get("organization_name", ""), info.get("project_name", ""))

    async def rows(self, sql: str, window_hours: int) -> list[Mapping[str, object]]:
        since = datetime.now(UTC) - timedelta(hours=window_hours)
        try:
            result = await self._client.query_json_rows(
                sql=sql,
                min_timestamp=since,
                limit=self._max_rows,
            )
        except _FAILURES as error:
            raise _translate(error) from error
        return list(result["rows"])


@asynccontextmanager
async def logfire_query(
    token: SecretStr,
    settings: TelemetrySettings,
) -> AsyncGenerator[LogfireQuery]:
    """Open the Logfire query API with the read token and the configured time limit."""
    timeout = httpx.Timeout(settings.query_timeout_seconds)
    async with AsyncLogfireQueryClient(token.get_secret_value(), timeout=timeout) as client:
        yield _ApiQuery(client, settings.max_rows)
