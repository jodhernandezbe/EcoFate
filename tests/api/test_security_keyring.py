"""Security audit of the OpenAI key handling: keychain calls, log scrubbing, no plaintext GET."""

from __future__ import annotations

import io
import logging
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.core.logging_filter import REDACTED, SecretRedactionFilter
from app.key_vault import default_service_keys
from tests.api.conftest import ORIGIN, signed_in
from tests.fakes import FakeCredentialStore

KEY = "sk-proj-" + "Zx9Cv8Bn7M" * 3  # pragma: allowlist secret
OWN = {"Origin": ORIGIN}


@pytest.fixture
def client(admin_client: TestClient) -> TestClient:
    """These tests manage the server's keys, which only an administrator may change."""
    return admin_client


def _logger_with_filter() -> tuple[logging.Logger, io.StringIO]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(SecretRedactionFilter())
    logger = logging.getLogger("tests.security")
    logger.handlers = [handler]
    logger.setLevel(logging.DEBUG)
    return logger, stream


def _get_paths(app: FastAPI) -> list[str]:
    """Every parameterless GET path the app serves, from its OpenAPI document."""
    paths = cast(dict[str, dict[str, object]], app.openapi()["paths"])
    return [path for path, ops in paths.items() if "get" in ops and "{" not in path]


def test_save_load_and_delete_use_the_configured_keychain_entry() -> None:
    store = FakeCredentialStore()
    vault = default_service_keys(store).vault("openai")
    vault.save(KEY)
    loaded = vault.load()
    vault.clear()
    assert loaded is not None
    assert loaded.get_secret_value() == KEY
    assert store.calls == [
        ("set", "epa-chemical-risk-agent", "openai_api_key"),
        ("get", "epa-chemical-risk-agent", "openai_api_key"),
        ("delete", "epa-chemical-risk-agent", "openai_api_key"),
    ]
    assert store.entries == {}


def test_shipped_settings_use_the_required_keychain_names() -> None:
    from config.ui import get_ui_settings

    names = get_ui_settings().keyring
    assert names.service == "epa-chemical-risk-agent"
    assert names.accounts["openai"] == "openai_api_key"


def test_redaction_covers_records_arguments_and_exception_messages() -> None:
    logger, stream = _logger_with_filter()
    logger.info("plain %s", KEY)
    logger.info(f"fstring {KEY}")
    try:
        raise RuntimeError(f"provider echoed {KEY}")
    except RuntimeError:
        logger.exception("failed")
    output = stream.getvalue()
    assert KEY not in output
    assert output.count(REDACTED) == 3  # argument, message, and the exception in the traceback


def test_no_get_endpoint_returns_the_key(app: FastAPI, store: FakeCredentialStore) -> None:
    default_service_keys(store).vault("openai").save(KEY)
    get_paths = _get_paths(app)
    assert "/api/v1/settings/openai-key" in get_paths
    with signed_in(app) as client:
        for path in get_paths:
            assert KEY not in client.get(path).text, path


def test_status_is_only_a_boolean(app: FastAPI, store: FakeCredentialStore) -> None:
    default_service_keys(store).vault("openai").save(KEY)
    with signed_in(app) as client:
        body = client.get("/api/v1/settings/openai-key").json()
    assert body == {"configured": True}
    assert KEY[-4:] not in str(body)


def test_saving_never_echoes_or_logs_the_key(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    response = client.post("/api/v1/settings/openai-key", json={"api_key": KEY}, headers=OWN)
    assert KEY not in response.text
    assert KEY not in caplog.text


def test_no_get_endpoint_returns_any_of_the_three_keys(
    app: FastAPI,
    store: FakeCredentialStore,
) -> None:
    secrets = {
        "openai": KEY,
        "census": "c3n5u5k3y" + "7f" * 16,  # pragma: allowlist secret
        "comptox": "ct0x-" + "9d" * 14,  # pragma: allowlist secret
    }
    keys = default_service_keys(store)
    for name, secret in secrets.items():
        keys.vault(name).save(secret)  # pyright: ignore[reportArgumentType]
    with signed_in(app) as client:
        for path in _get_paths(app):
            for secret in secrets.values():
                assert secret not in client.get(path).text, path
