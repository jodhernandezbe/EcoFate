"""Tests for the origin guard with a public origin (production behind a proxy)."""

from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from api.core.origin_guard import OriginGuard

PUBLIC = "https://ecofate.org"


async def _ok(_request: object) -> PlainTextResponse:
    return PlainTextResponse("ok")


def _client(origin: str = PUBLIC) -> TestClient:
    routes = [
        Route("/api/x", _ok, methods=["GET", "POST"]),
    ]
    app = Starlette(routes=routes)
    app.add_middleware(OriginGuard, origin=origin)
    return TestClient(app, base_url="https://ecofate.org")


def test_the_public_host_is_served() -> None:
    assert _client().get("/api/x").status_code == 200


@pytest.mark.parametrize(
    "host",
    ["evil.example", "127.0.0.1:8000", "ecofate.org.evil.example", "www.ecofate.org"],
)
def test_any_other_host_is_refused(host: str) -> None:
    assert _client().get("/api/x", headers={"host": host}).status_code == 403


def test_a_state_change_from_the_public_origin_is_served() -> None:
    assert _client().post("/api/x", headers={"origin": PUBLIC}).status_code == 200


@pytest.mark.parametrize(
    "origin",
    ["http://127.0.0.1:8000", "http://ecofate.org", "https://evil.example"],
)
def test_a_state_change_from_another_origin_is_refused(origin: str) -> None:
    assert _client().post("/api/x", headers={"origin": origin}).status_code == 403
