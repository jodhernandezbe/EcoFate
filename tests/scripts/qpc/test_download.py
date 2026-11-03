"""Tests for scripts.qpc.download (mock transport, no network)."""

from __future__ import annotations

import httpx
import pytest

from scripts.qpc.download import fetch_workbook
from scripts.qpc.errors import QpcDownloadError
from scripts.qpc.release import Release

URL = "https://h.example/2026/q2.xlsx"
RELEASE = Release(2026, 2)
ZIP = b"PK\x03\x04" + b"0" * 20


def _fetch(handler: httpx.MockTransport, max_bytes: int = 1000) -> bytes:
    with httpx.Client(transport=handler) as client:
        return fetch_workbook(
            URL,
            RELEASE,
            client=client,
            host="h.example",
            timeout=5,
            max_bytes=max_bytes,
        )


def test_returns_the_body() -> None:
    assert _fetch(httpx.MockTransport(lambda r: httpx.Response(200, content=ZIP))) == ZIP


def test_404_names_release_and_url() -> None:
    with pytest.raises(QpcDownloadError, match=r"2026Q2.*not published.*q2\.xlsx"):
        _fetch(httpx.MockTransport(lambda r: httpx.Response(404)))


def test_server_error_is_an_error() -> None:
    with pytest.raises(QpcDownloadError, match="HTTP 500"):
        _fetch(httpx.MockTransport(lambda r: httpx.Response(500)))


def test_html_with_status_200_is_not_a_workbook() -> None:
    page = httpx.Response(200, content=b"<html>maintenance</html>")
    with pytest.raises(QpcDownloadError, match="not a ZIP"):
        _fetch(httpx.MockTransport(lambda r: page))


def test_oversized_body_is_abandoned() -> None:
    with pytest.raises(QpcDownloadError, match="cap"):
        _fetch(httpx.MockTransport(lambda r: httpx.Response(200, content=ZIP * 100)), 100)


def test_declared_oversize_is_refused_before_reading() -> None:
    big = httpx.Response(200, content=ZIP, headers={"content-length": "5000"})
    with pytest.raises(QpcDownloadError, match="5000 bytes"):
        _fetch(httpx.MockTransport(lambda r: big), 100)


def test_timeout_is_an_error() -> None:
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("too slow", request=request)

    with pytest.raises(QpcDownloadError, match="could not download"):
        _fetch(httpx.MockTransport(slow))


def test_redirect_off_the_host_is_refused() -> None:
    def hop(request: httpx.Request) -> httpx.Response:
        if request.url.host == "h.example":
            return httpx.Response(302, headers={"location": "https://evil.example/x.xlsx"})
        return httpx.Response(200, content=ZIP)

    with pytest.raises(QpcDownloadError, match="redirected away"):
        _fetch(httpx.MockTransport(hop))
