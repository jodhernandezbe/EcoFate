"""Tests for the app factory: origin guard, sanitised errors and the static frontend."""

from __future__ import annotations

import base64
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.redaction as redaction
from api.main import create_app
from api.services.key_setup import load_key_config
from app.redaction import redact
from config.auth import get_auth_settings
from config.byok import get_byok_settings
from config.mail import get_mail_settings
from config.telemetry import get_telemetry_settings
from config.ui import UiSettings
from tests.api.auth_support import build_app
from tests.api.conftest import ORIGIN, make_user, sign_in_as
from tests.fakes import InMemoryThreadStore

KEK = bytes(range(32))
WRITE_TOKEN = "write-token-" + "w" * 20  # pragma: allowlist secret
READ_TOKEN = "read-token-" + "r" * 20  # pragma: allowlist secret
SESSION_SECRET = "session-secret-" + "s" * 20  # pragma: allowlist secret
SMTP_PASSWORD = "smtp-password-" + "p" * 20  # pragma: allowlist secret
KEK_TEXT = base64.urlsafe_b64encode(KEK).decode()
KEY = "sk-proj-" + "m3N4b5V6c7" * 3  # pragma: allowlist secret
BODY = {"api_key": "sk-" + "a" * 20}  # pragma: allowlist secret


@pytest.fixture
def client(admin_client: TestClient) -> TestClient:
    """These tests manage the server's keys, which only an administrator may change."""
    return admin_client


def test_foreign_origin_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/settings/openai-key",
        json=BODY,
        headers={"Origin": "https://example.com"},
    )
    assert response.status_code == 403


def test_missing_origin_is_rejected_for_writes(client: TestClient) -> None:
    assert client.post("/api/v1/settings/openai-key", json=BODY).status_code == 403
    assert client.delete("/api/v1/settings/openai-key").status_code == 403


def test_referer_of_own_origin_is_accepted(client: TestClient) -> None:
    response = client.delete("/api/v1/settings/openai-key", headers={"Referer": ORIGIN + "/page"})
    assert response.status_code == 200


def test_own_origin_is_accepted(client: TestClient) -> None:
    response = client.post("/api/v1/settings/openai-key", json=BODY, headers={"Origin": ORIGIN})
    assert response.status_code == 200


def test_rebinding_host_is_rejected(app: FastAPI) -> None:
    with TestClient(app, base_url="http://evil.example:8000") as client:
        assert client.get("/api/v1/settings/openai-key").status_code == 403


def test_validation_errors_do_not_echo_values(client: TestClient) -> None:
    response = client.post(
        "/api/v1/settings/openai-key",
        json={"api_key": 5, "other": KEY},
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == 422
    assert KEY not in response.text
    assert {"loc", "msg"} == set(response.json()["fields"][0])


def test_unhandled_errors_are_generic_and_logged_redacted(
    app: FastAPI,
    caplog: pytest.LogCaptureFixture,
) -> None:
    @app.get("/api/boom")
    def boom() -> None:
        raise RuntimeError(f"provider said {KEY}")

    with TestClient(app, base_url=ORIGIN, raise_server_exceptions=False) as client:
        response = client.get("/api/boom")
    body = response.json()
    assert response.status_code == 500
    assert set(body) == {"error", "correlation_id"}
    assert KEY not in response.text
    assert body["correlation_id"] in caplog.text


def test_frontend_is_served_when_built(settings: UiSettings, tmp_path: Path) -> None:
    dist = tmp_path / "built"
    dist.mkdir()
    (dist / "index.html").write_text("<html>shell</html>")
    app = build_app(replace(settings, frontend_dist=dist), threads=InMemoryThreadStore())
    with TestClient(app, base_url=ORIGIN) as client:
        assert "shell" in client.get("/").text  # the static shell needs no session
        assert client.get("/api/v1/settings/openai-key").status_code == 401  # the API does
        sign_in_as(app, client, make_user(app))
        assert client.get("/api/v1/settings/openai-key").status_code == 200


def test_process_secrets_are_kept_out_of_the_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    monitoring = get_telemetry_settings()
    secrets = {
        monitoring.write_token_env_var: WRITE_TOKEN,
        monitoring.read_token_env_var: READ_TOKEN,
        get_auth_settings().session_secret_env_var: SESSION_SECRET,
        get_mail_settings().variables.password: SMTP_PASSWORD,
    }
    empty: set[str] = set()
    monkeypatch.setattr(redaction, "_PROCESS_LITERALS", empty)
    environ = {**secrets, get_byok_settings().kek_env_var: KEK_TEXT}
    load_key_config(environ)
    for value in secrets.values():
        assert value not in redact(f"leaked {value}")


@pytest.mark.anyio
async def test_without_an_injected_store_start_up_needs_the_database_url(
    settings: UiSettings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv(get_byok_settings().kek_env_var, KEK_TEXT)
    app = create_app(settings)
    with pytest.raises(SystemExit) as stopped:
        async with app.router.lifespan_context(app):
            pytest.fail("must not serve")
    assert "DATABASE_URL" in str(stopped.value.code)


SMTP_ENV = {
    "SMTP_HOST": "127.0.0.1",
    "SMTP_PORT": "1025",
    "SMTP_SECURITY": "none",
    "SMTP_FROM": "EcoFate <no-reply@example.com>",
}


def _app_with_real_mailer(settings: UiSettings, container: bool) -> FastAPI:
    from api import main as main_module
    from tests.fakes import InMemoryThreadStore, KeyBench
    from tests.fakes_accounts import FakeClock, in_memory_accounts

    return main_module.create_app(
        settings,
        keys_from_environment=container,
        threads=InMemoryThreadStore(),
        accounts=in_memory_accounts(FakeClock()),
        keys=KeyBench().services,
        session_secret=b"s" * 40,
    )


@pytest.mark.parametrize("container", [False, True])
def test_the_smtp_server_comes_from_the_environment_and_a_container_reaches_mailpit(
    settings: UiSettings,
    monkeypatch: pytest.MonkeyPatch,
    container: bool,
) -> None:
    from api.services.auth.smtp import Security
    from config.mail import get_mail_settings

    for name, value in SMTP_ENV.items():
        monkeypatch.setenv(name, value)
    app = _app_with_real_mailer(settings, container)
    server = app.state.auth.mailer._server  # noqa: SLF001
    expected = get_mail_settings().container_loopback_host if container else "127.0.0.1"
    assert (server.host, server.port, server.security) == (expected, 1025, Security.NONE)


def test_without_the_smtp_variables_the_app_refuses_to_start(
    settings: UiSettings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in SMTP_ENV:
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(SystemExit) as stopped:
        _app_with_real_mailer(settings, False)
    assert "SMTP_HOST" in str(stopped.value.code)


@pytest.mark.anyio
@pytest.mark.parametrize("value", [None, "", "not base64 !!", "c2hvcnQ"])
async def test_a_missing_or_malformed_kek_stops_start_up_naming_the_variable(
    settings: UiSettings,
    monkeypatch: pytest.MonkeyPatch,
    value: str | None,
) -> None:
    variable = get_byok_settings().kek_env_var
    if value is None:
        monkeypatch.delenv(variable, raising=False)
    else:
        monkeypatch.setenv(variable, value)
    app = create_app(settings)
    with pytest.raises(SystemExit) as stopped:
        async with app.router.lifespan_context(app):
            pytest.fail("must not serve")
    message = str(stopped.value.code)
    assert variable in message
    assert value is None or value == "" or value not in message
