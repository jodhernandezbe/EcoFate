"""Every route needs a session except a reviewed public list; Monitoring is for admins only."""

from __future__ import annotations

import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.dependencies import get_monitoring
from api.services.monitoring.service import MonitoringService
from tests.api.conftest import ORIGIN, make_user, signed_in
from tests.api.services.monitoring.factories import labels, settings, turn_row
from tests.api.services.monitoring.fakes import FakeQuery, opener

OWN = {"Origin": ORIGIN}
PUBLIC = {
    ("GET", "/api/health"),
    ("GET", "/api/v1/settings/client"),
    ("POST", "/api/v1/auth/signup"),
    ("POST", "/api/v1/auth/verify"),
    ("POST", "/api/v1/auth/resend"),
    ("POST", "/api/v1/auth/signin"),
    ("POST", "/api/v1/auth/forgot"),
    ("POST", "/api/v1/auth/reset"),
}


def _routes(app: FastAPI) -> list[tuple[str, str]]:
    """Every (method, path) the API serves, from its OpenAPI document (the static shell is not
    an API route)."""
    paths: dict[str, dict[str, object]] = app.openapi()["paths"]
    return [(method.upper(), path) for path, item in paths.items() for method in item]


def _concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "x1", path)


def test_the_public_list_names_only_routes_that_exist(app: FastAPI) -> None:
    assert PUBLIC <= set(_routes(app))


def test_every_other_route_answers_401_without_a_session(
    anonymous: TestClient,
    app: FastAPI,
) -> None:
    protected = [(m, p) for m, p in _routes(app) if (m, p) not in PUBLIC]
    assert len(protected) > 20  # the table is really being walked
    for method, path in protected:
        response = anonymous.request(method, _concrete(path), json={}, headers=OWN)
        assert response.status_code == 401, (method, path)
        assert set(response.json()) == {"error", "correlation_id"}, (method, path)


def test_a_missing_session_is_refused_before_the_body_is_read(anonymous: TestClient) -> None:
    response = anonymous.post("/api/v1/chat/stream", content=b"{not json", headers=OWN)
    assert response.status_code == 401


def test_a_garbage_cookie_is_the_same_401(anonymous: TestClient) -> None:
    anonymous.cookies.set("ecofate_session", "a" * 43)
    assert anonymous.get("/api/v1/chat/threads/t1").status_code == 401


def test_the_public_routes_work_without_a_session(anonymous: TestClient) -> None:
    assert anonymous.get("/api/health").status_code == 200
    assert anonymous.get("/api/v1/settings/client").status_code == 200


def test_the_static_shell_needs_no_session(app: FastAPI, tmp_path: object) -> None:
    from dataclasses import replace
    from pathlib import Path

    from tests.api.auth_support import build_app

    dist = Path(str(tmp_path)) / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>shell</html>")
    shell = build_app(
        replace(app.state.ui if hasattr(app.state, "ui") else _ui(), frontend_dist=dist),
    )
    with TestClient(shell, base_url=ORIGIN) as client:
        assert client.get("/").status_code == 200


def _ui():  # noqa: ANN202
    from config.ui import get_ui_settings

    return get_ui_settings()


def _monitoring(app: FastAPI, query: FakeQuery) -> None:
    service = MonitoringService(
        settings(),
        labels(),
        {settings().read_token_env_var: "pylf_v1_us_" + "r" * 40},  # pragma: allowlist secret
        opener(query),
        emails=app.state.auth.accounts.users.emails,
    )
    app.dependency_overrides[get_monitoring] = lambda: service


@pytest.mark.parametrize("path", ["/api/v1/monitoring/sessions", "/api/v1/monitoring/sessions/s1"])
def test_a_non_admin_gets_the_404_of_an_unknown_route_and_no_logfire_query(
    app: FastAPI,
    path: str,
) -> None:
    query = FakeQuery([turn_row()])
    _monitoring(app, query)
    with signed_in(app, raise_server_exceptions=False) as client:
        denied = client.get(path)
        unknown = client.get("/api/v1/monitoring/nothing-here")
    assert denied.status_code == unknown.status_code == 404
    assert set(denied.json()) == set(unknown.json()) == {"error", "correlation_id"}
    assert denied.json()["error"] == unknown.json()["error"]
    assert query.statements == [] and query.tokens == []


def test_an_admin_sees_each_session_with_the_account_that_ran_it(app: FastAPI) -> None:
    ana, bo = make_user(app, "ana@example.com"), make_user(app, "bo@example.com")
    rows = [
        turn_row(sid="s1", trace_id="a" * 32, user_id=str(ana.id)),
        turn_row(sid="s2", trace_id="b" * 32, user_id=str(bo.id)),
    ]
    _monitoring(app, FakeQuery(rows))
    with signed_in(app, email="root@example.com", admin=True) as client:
        sessions = {
            s["session_id"]: s["account"]
            for s in client.get(
                "/api/v1/monitoring/sessions",
            ).json()["sessions"]
        }
    assert sessions == {"s1": "ana@example.com", "s2": "bo@example.com"}


def test_a_session_of_a_deleted_or_unknown_account_shows_no_account(app: FastAPI) -> None:
    import asyncio

    gone = make_user(app, "gone@example.com")
    asyncio.run(app.state.auth.accounts.users.delete(gone.id))
    rows = [
        turn_row(sid="s1", trace_id="a" * 32, user_id=str(gone.id)),
        turn_row(sid="s2", trace_id="b" * 32, user_id=None),
        turn_row(sid="s3", trace_id="c" * 32, user_id="not-a-uuid"),
    ]
    _monitoring(app, FakeQuery(rows))
    with signed_in(app, email="root@example.com", admin=True) as client:
        body = client.get("/api/v1/monitoring/sessions").json()
    assert body["state"] == "ok"
    assert {s["session_id"]: s["account"] for s in body["sessions"]} == {
        "s1": None,
        "s2": None,
        "s3": None,
    }
    assert len(body["sessions"]) == 3


def test_no_email_is_sent_to_the_monitoring_query(app: FastAPI) -> None:
    ana = make_user(app, "ana@example.com")
    query = FakeQuery([turn_row(user_id=str(ana.id))])
    _monitoring(app, query)
    with signed_in(app, email="root@example.com", admin=True) as client:
        client.get("/api/v1/monitoring/sessions")
    assert query.statements and all("ana@example.com" not in sql for sql, _ in query.statements)
