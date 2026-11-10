"""Passwords and tokens never reach a log, a response body, an error, a span or a URL query."""

from __future__ import annotations

import logging
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.api.auth_support import token_in
from tests.api.conftest import ORIGIN
from tests.fakes_accounts import RecordingMailer

OWN = {"Origin": ORIGIN}
EMAIL = "ana@example.com"
PASSWORD = "unique-password-" + "7Qx9Lm2Zk4"  # pragma: allowlist secret
NEW_PASSWORD = "unique-new-password-" + "3Vb8Nc5Jr1"  # pragma: allowlist secret


class _Run:
    """Everything one account lifecycle produced, and the secrets that must not be in it."""

    def __init__(self) -> None:
        self.responses: list[Any] = []
        self.secrets: list[str] = [PASSWORD, NEW_PASSWORD]
        self.session_cookie: str | None = None

    def post(self, client: TestClient, path: str, body: dict[str, Any]) -> Any:
        response = client.post(f"/api/v1/{path}", json=body, headers=OWN)
        self.responses.append(response)
        return response


def _lifecycle(client: TestClient, mailer: RecordingMailer) -> _Run:
    run = _Run()
    run.post(client, "auth/signup", {"email": EMAIL, "password": PASSWORD})
    verify = token_in(mailer.sent[-1].body)
    run.secrets.append(verify)
    run.post(client, "auth/verify", {"token": verify})
    run.post(client, "auth/signin", {"email": EMAIL, "password": PASSWORD})
    run.session_cookie = client.cookies.get("ecofate_session")
    assert run.session_cookie
    run.secrets.append(run.session_cookie)
    run.post(
        client,
        "auth/signin",
        {"email": EMAIL, "password": "wrong-" + PASSWORD},  # pragma: allowlist secret
    )  # pragma: allowlist secret
    run.post(
        client,
        "auth/signup",
        {"email": EMAIL, "password": "short"},  # pragma: allowlist secret
    )  # pragma: allowlist secret
    run.post(client, "auth/forgot", {"email": EMAIL})
    reset = token_in(mailer.sent[-1].body)
    run.secrets.append(reset)
    run.post(client, "auth/reset", {"token": reset, "password": NEW_PASSWORD})
    run.post(client, "auth/signin", {"email": EMAIL, "password": NEW_PASSWORD})
    body = {"current_password": NEW_PASSWORD, "new_password": PASSWORD}
    run.post(client, "account/password", body)
    run.post(client, "auth/verify", {"token": "x" * 40})  # a bad token must not be echoed either
    run.secrets.append("x" * 40)
    run.post(
        client,
        "account/delete",
        {"password": "wrong-" + PASSWORD},  # pragma: allowlist secret
    )  # pragma: allowlist secret
    run.post(client, "auth/signout", {})
    return run


def test_no_secret_appears_in_a_log_record_even_at_debug_level(
    anonymous: TestClient,
    mailer: RecordingMailer,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG):
        run = _lifecycle(anonymous, mailer)
    logged = caplog.text + "\n".join(
        str(arg) for record in caplog.records for arg in (record.args or ())
    )
    for secret in run.secrets:
        assert secret not in logged, secret[:8]


def test_no_secret_appears_in_a_response_body_or_header_but_the_session_cookie_it_sets(
    anonymous: TestClient,
    mailer: RecordingMailer,
) -> None:
    run = _lifecycle(anonymous, mailer)
    others = [s for s in run.secrets if s != run.session_cookie]
    for response in run.responses:
        headers = {k: v for k, v in response.headers.items() if k != "set-cookie"}
        blob = response.text + str(headers)
        for secret in others:
            assert secret not in blob, (response.request.url, secret[:8])
        assert run.session_cookie not in blob


def test_the_session_token_is_only_ever_set_in_the_cookie_header(
    anonymous: TestClient,
    mailer: RecordingMailer,
) -> None:
    run = _lifecycle(anonymous, mailer)
    carriers = [r for r in run.responses if run.session_cookie in r.headers.get("set-cookie", "")]
    assert carriers and all(r.request.url.path.endswith("/signin") for r in carriers)


def test_a_validation_error_does_not_echo_the_submitted_password(anonymous: TestClient) -> None:
    response = anonymous.post(
        "/api/v1/auth/signup",
        json={"email": EMAIL, "password": "tiny"},  # pragma: allowlist secret
        headers=OWN,
    )
    assert response.status_code == 422 and "tiny" not in response.text
    odd = anonymous.post(
        "/api/v1/auth/signin",
        json={"email": EMAIL, "password": PASSWORD, "extra": "field"},
        headers=OWN,
    )
    assert odd.status_code == 422 and PASSWORD not in odd.text


def test_no_endpoint_takes_a_token_in_the_url(app: FastAPI) -> None:
    for path, item in app.openapi()["paths"].items():
        for operation in item.values():
            for parameter in operation.get("parameters", []):
                name = str(parameter["name"]).lower()
                assert not (parameter["in"] == "query" and "token" in name), path
    assert all("{token}" not in path for path in app.openapi()["paths"])


def test_the_emailed_links_keep_the_token_out_of_the_query_string(
    anonymous: TestClient,
    mailer: RecordingMailer,
) -> None:
    anonymous.post("/api/v1/auth/signup", json={"email": EMAIL, "password": PASSWORD}, headers=OWN)
    anonymous.post("/api/v1/auth/forgot", json={"email": EMAIL}, headers=OWN)
    for mail in mailer.sent:
        link = next(line for line in mail.body.splitlines() if line.startswith("http"))
        assert "?" not in link and "#" in link and link.split("#", 1)[0].endswith("/")


def test_password_fields_are_secret_strings_in_the_models() -> None:
    from api.schemas.auth import SignInRequest

    shown = repr(SignInRequest(email=EMAIL, password=PASSWORD))  # type: ignore[arg-type]
    assert PASSWORD not in shown
