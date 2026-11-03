"""Tests for the monitoring service: data from Logfire or a state, never invented sessions."""

from __future__ import annotations

import logging

import pytest

from api.services.monitoring.client import MonitoringUnauthorizedError, MonitoringUnavailableError
from api.services.monitoring.queries import detail_sql, sessions_sql
from api.services.monitoring.service import (
    NOT_CONFIGURED,
    UNAUTHORIZED,
    UNAVAILABLE,
    MonitoringService,
)
from tests.api.services.monitoring.factories import call_row, labels, root_row, settings, turn_row
from tests.api.services.monitoring.fakes import FakeQuery, opener

pytestmark = pytest.mark.anyio
SETTINGS = settings()
TOKEN = "pylf_v1_us_" + "r" * 40  # pragma: allowlist secret
ENVIRON = {SETTINGS.read_token_env_var: TOKEN}


def _service(query: FakeQuery, environ: dict[str, str] | None = None) -> MonitoringService:
    return MonitoringService(
        SETTINGS,
        labels(),
        ENVIRON if environ is None else environ,
        opener(query),
    )


@pytest.mark.parametrize("environ", [{}, {SETTINGS.read_token_env_var: "  "}])
async def test_without_a_read_token_logfire_is_not_called(environ: dict[str, str]) -> None:
    query = FakeQuery([turn_row()])
    sessions = await _service(query, environ).sessions()
    detail = await _service(query, environ).session("s1")
    for answer in (sessions, detail):
        assert (answer.state, answer.message) == ("not_configured", NOT_CONFIGURED)
    assert (sessions.sessions, detail.session, detail.turns) == ([], None, [])
    assert query.statements == [] and query.tokens == []


async def test_sessions_are_read_with_one_statement_in_the_configured_window() -> None:
    older = turn_row(sid="old", start_timestamp="2026-01-01T00:00:00Z", trace_id="c" * 32)
    query = FakeQuery([older, turn_row()])
    answer = await _service(query).sessions()
    assert answer.state == "ok" and answer.message is None
    assert [s.session_id for s in answer.sessions] == ["s1", "old"]
    assert query.statements == [(sessions_sql(SETTINGS), SETTINGS.session_window_hours)]
    assert query.tokens == [TOKEN]


async def test_a_row_without_identity_is_skipped_not_listed() -> None:
    answer = await _service(FakeQuery([turn_row(sid=None), turn_row()])).sessions()
    assert [s.session_id for s in answer.sessions] == ["s1"]


@pytest.mark.parametrize(
    ("failure", "state", "message"),
    [
        (MonitoringUnavailableError("down"), "unavailable", UNAVAILABLE),
        (MonitoringUnauthorizedError("no"), "unauthorized", UNAUTHORIZED),
    ],
)
async def test_a_logfire_failure_is_a_state_with_no_sessions(
    failure: Exception,
    state: str,
    message: str,
) -> None:
    answer = await _service(FakeQuery(failure=failure)).sessions()
    assert (answer.state, answer.message, answer.sessions) == (state, message, [])
    detail = await _service(FakeQuery(failure=failure)).session("s1")
    assert (detail.state, detail.message, detail.session, detail.turns) == (
        state,
        message,
        None,
        [],
    )


async def test_a_session_comes_with_its_turns_calls_and_link() -> None:
    rows = [root_row(), call_row("chat", 1), call_row("execute_tool", 2), call_row("chat", 3)]
    query = FakeQuery(rows)
    answer = await _service(query).session("s1")
    assert answer.state == "ok" and answer.session is not None
    assert (answer.session.model_calls, answer.session.tool_calls) == (2, 1)
    assert answer.session.input_tokens == 100  # the turn's recorded usage, not re-added from calls
    (turn,) = answer.turns
    assert [s.kind for s in turn.steps] == ["model", "tool", "model"]
    assert turn.trace_url is not None and turn.trace_url.startswith("https://")
    assert query.statements == [(detail_sql(SETTINGS, "s1"), SETTINGS.session_window_hours)]


async def test_an_unknown_session_has_no_summary() -> None:
    answer = await _service(FakeQuery([])).session("nope")
    assert (answer.state, answer.session, answer.turns) == ("ok", None, [])


async def test_a_malformed_id_never_reaches_logfire() -> None:
    query = FakeQuery([])
    with pytest.raises(ValueError, match="session id"):
        await _service(query).session("x' or '1'='1")
    assert query.statements == []


async def test_the_token_never_appears_in_an_answer_or_the_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG):
        answers = [
            await _service(FakeQuery(failure=MonitoringUnauthorizedError("no"))).sessions(),
            await _service(FakeQuery(failure=MonitoringUnavailableError("down"))).sessions(),
            await _service(FakeQuery([turn_row()])).sessions(),
        ]
    assert all(TOKEN not in answer.model_dump_json() for answer in answers)
    assert TOKEN not in caplog.text
