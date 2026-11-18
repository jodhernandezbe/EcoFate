"""Tests for the container health check: loopback request carrying the site's own Host."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from api.container_health import check, health_request
from config.ui import UiSettings, load_ui_settings


class _Health(BaseHTTPRequestHandler):
    status = 200
    hosts: list[str] = []

    def do_GET(self) -> None:
        _Health.hosts.append(self.headers.get("Host", ""))
        self.send_response(_Health.status if self.path == "/api/health" else 404)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002  # silence test output
        return


@pytest.fixture
def server() -> Iterator[HTTPServer]:
    _Health.status, _Health.hosts = 200, []
    httpd = HTTPServer(("127.0.0.1", 0), _Health)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def _ui(port: int, public_origin: str | None = None) -> UiSettings:
    return replace(
        load_ui_settings(),
        port=port,
        public_origin=public_origin,
        container_health_timeout_seconds=2.0,
    )


def test_healthy_api_exits_zero_and_sends_the_local_host(server: HTTPServer) -> None:
    port = server.server_address[1]
    assert check(_ui(port)) == 0
    assert _Health.hosts == [f"127.0.0.1:{port}"]


def test_in_production_the_public_host_is_sent(server: HTTPServer) -> None:
    assert check(_ui(server.server_address[1], "https://ecofate.org")) == 0
    assert _Health.hosts == ["ecofate.org"]


def test_an_unhealthy_api_exits_one(server: HTTPServer) -> None:
    _Health.status = 503
    assert check(_ui(server.server_address[1])) == 1


def test_no_api_listening_exits_one(server: HTTPServer) -> None:
    port = server.server_address[1]
    server.shutdown()
    server.server_close()
    assert check(_ui(port)) == 1


def test_the_request_always_goes_to_loopback() -> None:
    request = health_request(_ui(8000, "https://ecofate.org"))
    assert request.full_url == "http://127.0.0.1:8000/api/health"
    assert request.get_header("Host") == "ecofate.org"
