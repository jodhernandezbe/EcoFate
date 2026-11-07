"""Shared fixtures: an app wired to an in-memory credential store, never the real keychain."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.dependencies import get_service_keys
from api.main import create_app
from app.key_vault import default_service_keys
from config.ui import UiSettings, get_ui_settings
from tests.fakes import FakeCredentialStore, InMemoryThreadStore

ORIGIN = "http://127.0.0.1:8000"


@pytest.fixture
def store() -> FakeCredentialStore:
    return FakeCredentialStore()


@pytest.fixture
def settings(tmp_path: Path) -> UiSettings:
    return replace(get_ui_settings(), frontend_dist=tmp_path / "dist")


@pytest.fixture
def app(store: FakeCredentialStore, settings: UiSettings) -> FastAPI:
    api = create_app(settings, threads=InMemoryThreadStore())
    keys = default_service_keys(store)
    api.dependency_overrides[get_service_keys] = lambda: keys
    return api


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, base_url=ORIGIN, raise_server_exceptions=False) as test_client:
        yield test_client
