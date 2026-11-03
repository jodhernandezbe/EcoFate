"""The monitoring service: sessions and session timelines read back from Logfire.

Nothing is cached or made up. Without a read token, or when Logfire fails, the answer is a
state and a user-safe message with no sessions; the cause only goes to the log.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Literal

from pydantic import SecretStr

from api.schemas.monitoring import SessionDetailResponse, SessionsResponse
from api.services.monitoring.client import (
    LogfireQuery,
    MonitoringUnauthorizedError,
    MonitoringUnavailableError,
    Project,
    logfire_query,
)
from api.services.monitoring.queries import detail_sql, sessions_sql
from api.services.monitoring.rows import Row, parse_turn
from api.services.monitoring.sessions import group_sessions, summarize_session
from api.services.monitoring.timeline import build_turns
from config.telemetry import TelemetrySettings

QueryOpener = Callable[[SecretStr, TelemetrySettings], AbstractAsyncContextManager[LogfireQuery]]
Problem = Literal["not_configured", "unavailable", "unauthorized"]
NOT_CONFIGURED = (
    "Monitoring is not set up on this server: there is no Logfire read token. "
    "Runs are still recorded when a Logfire write token is set."
)
UNAVAILABLE = "Logfire could not be reached. Try again in a moment."
UNAUTHORIZED = "Logfire refused the read token. Check that it is valid for the project."


class _Stopped(Exception):
    def __init__(self, state: Problem, message: str) -> None:
        super().__init__(message)
        self.state: Problem = state
        self.message = message


@dataclass(frozen=True)
class MonitoringService:
    """Reads recorded sessions through the Logfire query API.

    Attributes:
        settings: The monitoring settings (names, window, limits, link template).
        step_labels: Tool name -> label shown for its step.
        environ: Where the read token is looked up (injected; tests pass a dict).
        open_query: Opens the Logfire query API with the token.
    """

    settings: TelemetrySettings
    step_labels: Mapping[str, str]
    environ: Mapping[str, str]
    open_query: QueryOpener = logfire_query

    def _token(self) -> SecretStr | None:
        value = self.environ.get(self.settings.read_token_env_var, "").strip()
        return SecretStr(value) if value else None

    async def _fetch(self, sql: str, *, with_project: bool) -> tuple[list[Row], Project | None]:
        token = self._token()
        if token is None:
            raise _Stopped("not_configured", NOT_CONFIGURED)
        try:
            async with self.open_query(token, self.settings) as query:
                project = await query.project() if with_project else None
                rows = await query.rows(sql, self.settings.session_window_hours)
        except MonitoringUnauthorizedError as error:
            raise _Stopped("unauthorized", UNAUTHORIZED) from error
        except MonitoringUnavailableError as error:
            raise _Stopped("unavailable", UNAVAILABLE) from error
        return rows, project

    async def sessions(self) -> SessionsResponse:
        """The most recent sessions, newest first, or the reason there are none."""
        try:
            rows, _ = await self._fetch(sessions_sql(self.settings), with_project=False)
        except _Stopped as stopped:
            return SessionsResponse(state=stopped.state, message=stopped.message, sessions=[])
        turns = [turn for turn in map(parse_turn, rows) if turn is not None]
        return SessionsResponse(state="ok", message=None, sessions=group_sessions(turns))

    async def session(self, session_id: str) -> SessionDetailResponse:
        """One session with its turns; ``session`` is None when no such session was recorded."""
        sql = detail_sql(self.settings, session_id)
        try:
            rows, project = await self._fetch(sql, with_project=True)
        except _Stopped as stopped:
            return SessionDetailResponse(
                state=stopped.state,
                message=stopped.message,
                session=None,
                turns=[],
            )
        records, turns = build_turns(rows, self.settings, self.step_labels, project)
        summary = summarize_session(records) if records else None
        return SessionDetailResponse(state="ok", message=None, session=summary, turns=turns)
