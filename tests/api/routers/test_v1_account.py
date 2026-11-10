"""Account management: change password, sign out everywhere, delete the account."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.services.auth.stores import UserStore
from tests.api.auth_support import PASSWORD
from tests.api.conftest import ORIGIN, make_user, runtime_of, sign_in_as
from tests.api.keys import owned

OWN = {"Origin": ORIGIN}
ACCOUNT = "/api/v1/account"
NEW = "a brand new password"


def _account(app: FastAPI, mailer: Any, email: str = "ana@example.com") -> TestClient:
    from tests.api.auth_support import token_in

    client = TestClient(app, base_url=ORIGIN)
    client.post("/api/v1/auth/signup", json={"email": email, "password": PASSWORD}, headers=OWN)
    client.post("/api/v1/auth/verify", json={"token": token_in(mailer.sent[-1].body)}, headers=OWN)
    client.post("/api/v1/auth/signin", json={"email": email, "password": PASSWORD}, headers=OWN)
    return client


def test_changing_the_password_needs_the_current_one(app: FastAPI, mailer: Any) -> None:
    client = _account(app, mailer)
    body = {"current_password": "wrong password!!", "new_password": NEW}  # pragma: allowlist secret
    assert client.post(f"{ACCOUNT}/password", json=body, headers=OWN).status_code == 403
    assert client.get("/api/v1/auth/me").status_code == 200


def test_changing_the_password_ends_the_other_sessions_but_not_this_one(
    app: FastAPI,
    mailer: Any,
) -> None:
    client = _account(app, mailer)
    elsewhere = TestClient(app, base_url=ORIGIN)
    elsewhere.post(
        "/api/v1/auth/signin",
        json={"email": "ana@example.com", "password": PASSWORD},
        headers=OWN,
    )
    body = {"current_password": PASSWORD, "new_password": NEW}
    assert client.post(f"{ACCOUNT}/password", json=body, headers=OWN).status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 200
    assert elsewhere.get("/api/v1/auth/me").status_code == 401
    fresh = TestClient(app, base_url=ORIGIN)
    ok = {"email": "ana@example.com", "password": NEW}
    assert fresh.post("/api/v1/auth/signin", json=ok, headers=OWN).json()["state"] == "signed_in"
    old = {"email": "ana@example.com", "password": PASSWORD}
    assert fresh.post("/api/v1/auth/signin", json=old, headers=OWN).status_code == 401


def test_a_weak_new_password_is_422_and_changes_nothing(app: FastAPI, mailer: Any) -> None:
    client = _account(app, mailer)
    body = {"current_password": PASSWORD, "new_password": "short"}  # pragma: allowlist secret
    response = client.post(f"{ACCOUNT}/password", json=body, headers=OWN)
    assert response.status_code == 422
    assert [f["loc"] for f in response.json()["fields"]] == [["body", "new_password"]]
    old = {"email": "ana@example.com", "password": PASSWORD}
    assert client.post("/api/v1/auth/signin", json=old, headers=OWN).status_code == 200


def test_sign_out_everywhere_ends_every_session_including_this_one(
    app: FastAPI,
    mailer: Any,
) -> None:
    client = _account(app, mailer)
    elsewhere = TestClient(app, base_url=ORIGIN)
    elsewhere.post(
        "/api/v1/auth/signin",
        json={"email": "ana@example.com", "password": PASSWORD},
        headers=OWN,
    )
    assert client.post(f"{ACCOUNT}/sign-out-everywhere", headers=OWN).status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401
    assert elsewhere.get("/api/v1/auth/me").status_code == 401


def test_deleting_the_account_needs_the_password_and_removes_everything(
    app: FastAPI,
    mailer: Any,
) -> None:
    import asyncio

    client = _account(app, mailer)
    me = client.get("/api/v1/auth/me").json()
    threads = app.state.threads
    from uuid import UUID

    key = owned("t1", UUID(me["id"]))
    asyncio.run(threads.touch(key))
    assert (
        client.post(
            f"{ACCOUNT}/delete",
            json={"password": "wrong password!!"},  # pragma: allowlist secret
            headers=OWN,
        ).status_code
        == 403
    )
    assert asyncio.run(threads.holds(key))
    assert (
        client.post(f"{ACCOUNT}/delete", json={"password": PASSWORD}, headers=OWN).status_code
        == 204
    )
    assert client.get("/api/v1/auth/me").status_code == 401
    assert not asyncio.run(threads.holds(key))
    users: UserStore = runtime_of(app).accounts.users
    assert asyncio.run(users.by_email("ana@example.com")) is None
    gone = {"email": "ana@example.com", "password": PASSWORD}
    assert client.post("/api/v1/auth/signin", json=gone, headers=OWN).status_code == 401


def test_the_account_routes_need_a_session(anonymous: TestClient) -> None:
    for path in ("password", "sign-out-everywhere", "delete"):
        assert anonymous.post(f"{ACCOUNT}/{path}", json={}, headers=OWN).status_code == 401


def test_another_users_threads_survive_an_account_deletion(app: FastAPI, mailer: Any) -> None:
    import asyncio

    other = make_user(app, "other@example.com")
    sign_in_as(app, TestClient(app, base_url=ORIGIN), other)
    key = owned("t1", other.id)
    asyncio.run(app.state.threads.touch(key))
    client = _account(app, mailer)
    client.post(f"{ACCOUNT}/delete", json={"password": PASSWORD}, headers=OWN)
    assert asyncio.run(app.state.threads.holds(key))
