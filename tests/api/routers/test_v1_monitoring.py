"""The monitoring routes: thin handlers over the service, with the id checked at the edge."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.dependencies import get_monitoring
from api.services.monitoring.client import MonitoringUnavailableError
from api.services.monitoring.service import MonitoringService
from tests.api.conftest import signed_in
from tests.api.services.monitoring.factories import call_row, labels, root_row, settings, turn_row
from tests.api.services.monitoring.fakes import FakeQuery, opener

SETTINGS = settings()
TOKEN = "pylf_v1_us_" + "r" * 40  # pragma: allowlist secret


def _client(app: FastAPI, query: FakeQuery, *, token: bool = True) -> TestClient:
    environ = {SETTINGS.read_token_env_var: TOKEN} if token else {}
    service = MonitoringService(SETTINGS, labels(), environ, opener(query))
    app.dependency_overrides[get_monitoring] = lambda: service
    return signed_in(app, admin=True)


def test_sessions_are_listed(app: FastAPI) -> None:
    response = _client(app, FakeQuery([turn_row()])).get("/api/v1/monitoring/sessions")
    body = response.json()
    assert response.status_code == 200
    assert (body["state"], body["message"]) == ("ok", None)
    assert body["sessions"][0]["session_id"] == "s1"
    assert body["sessions"][0]["cost_status"] == "estimate"


def test_not_configured_is_a_normal_answer_with_a_state(app: FastAPI) -> None:
    response = _client(app, FakeQuery([turn_row()]), token=False).get("/api/v1/monitoring/sessions")
    assert response.status_code == 200
    assert (response.json()["state"], response.json()["sessions"]) == ("not_configured", [])


def test_logfire_down_is_a_normal_answer_with_a_state(app: FastAPI) -> None:
    query = FakeQuery(failure=MonitoringUnavailableError("down"))
    body = _client(app, query).get("/api/v1/monitoring/sessions").json()
    assert (body["state"], body["sessions"]) == ("unavailable", [])


def test_a_session_comes_with_its_timeline(app: FastAPI) -> None:
    query = FakeQuery([root_row(), call_row("chat", 1), call_row("execute_tool", 2)])
    response = _client(app, query).get("/api/v1/monitoring/sessions/s1")
    body = response.json()
    assert response.status_code == 200 and body["session"]["session_id"] == "s1"
    assert [step["kind"] for step in body["turns"][0]["steps"]] == ["model", "tool"]
    assert body["turns"][0]["trace_url"]


def test_an_unknown_session_is_404(app: FastAPI) -> None:
    assert _client(app, FakeQuery([])).get("/api/v1/monitoring/sessions/nope").status_code == 404


@pytest.mark.parametrize("bad", ["a%20b", "x'%20or%20'1'='1", "a;b", "x" * 65])
def test_a_malformed_id_is_422_and_makes_no_query(app: FastAPI, bad: str) -> None:
    query = FakeQuery([root_row()])
    response = _client(app, query).get(f"/api/v1/monitoring/sessions/{bad}")
    assert response.status_code == 422
    assert query.statements == []


def test_the_state_of_a_missing_token_still_answers_the_detail(app: FastAPI) -> None:
    response = _client(app, FakeQuery([]), token=False).get("/api/v1/monitoring/sessions/s1")
    assert response.status_code == 200 and response.json()["state"] == "not_configured"


def test_no_response_holds_the_token(app: FastAPI) -> None:
    client = _client(app, FakeQuery([turn_row(), root_row()]))
    for path in ("/api/v1/monitoring/sessions", "/api/v1/monitoring/sessions/s1"):
        assert TOKEN not in client.get(path).text
