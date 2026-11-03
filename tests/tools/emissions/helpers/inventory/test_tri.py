"""Tests for tools.emissions.helpers.inventory.tri (no network: an httpx mock transport)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace

import httpx
import pytest

from config.efservice import load_efservice_settings
from config.loader import TriSettings, load_tri_settings
from tools.emissions.helpers.efservice import EfserviceClient, EfserviceError, Row
from tools.emissions.helpers.inventory.tri import TriFetcher

CAS = "50-00-0"
CURRENT_YEAR = 2026
SETTINGS = replace(
    load_tri_settings(),
    release_path="/r/{casrn}/m/{medium}/y/{after_year}/rows/{start}:{end}/JSON",
    page_size=3,
    max_pages=4,
)
EFSERVICE = replace(
    load_efservice_settings(),
    base_url="https://tri.test",
    delay_seconds=0.5,
    max_retries=1,
    backoff_seconds=1.0,
)

Handler = Callable[[httpx.Request], httpx.Response]


def _page(n: int, offset: int = 0) -> httpx.Response:
    return httpx.Response(200, json=[{"i": offset + k} for k in range(n)])


class Run:
    """A fetcher over a scripted handler, recording requests, waits and pages."""

    def __init__(self, handler: Handler, settings: TriSettings = SETTINGS) -> None:
        self.requests: list[httpx.Request] = []
        self.sleeps: list[float] = []
        self.pages: list[Sequence[Row]] = []

        def record(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return handler(request)

        client = httpx.Client(transport=httpx.MockTransport(record))
        self.fetcher = TriFetcher(
            settings,
            EfserviceClient(EFSERVICE, client, self.sleeps.append),
            CURRENT_YEAR,
        )

    def go(self, medium: str = "AIR STACK") -> bool:
        return self.fetcher.fetch(CAS, medium, self.pages.append)

    @property
    def urls(self) -> list[str]:
        return [str(r.url) for r in self.requests]


def _script(*responses: httpx.Response | Exception) -> Handler:
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    return handler


def test_pages_until_a_short_one() -> None:
    run = Run(_script(_page(3), _page(3, 3), _page(1, 6)))
    assert run.go() is False
    assert [len(p) for p in run.pages] == [3, 3, 1]
    assert run.urls == [
        "https://tri.test/r/50-00-0/m/AIR%20STACK/y/2023/rows/0:2/JSON",
        "https://tri.test/r/50-00-0/m/AIR%20STACK/y/2023/rows/3:5/JSON",
        "https://tri.test/r/50-00-0/m/AIR%20STACK/y/2023/rows/6:8/JSON",
    ]


def test_empty_first_page_is_a_clean_end() -> None:
    run = Run(_script(_page(0)))
    assert run.go() is False
    assert run.pages == [[]]
    assert len(run.requests) == 1


def test_page_is_handed_over_as_it_arrives() -> None:
    seen: list[int] = []
    run = Run(_script(_page(3), _page(2, 3)))
    run.fetcher.fetch(CAS, "AIR STACK", lambda rows: seen.append(len(run.requests)))
    assert seen == [1, 2]


def test_page_cap_flags_possible_truncation() -> None:
    run = Run(_script(*[_page(3, 3 * i) for i in range(4)]))
    assert run.go() is True
    assert len(run.requests) == 4


def test_full_last_page_at_the_cap_is_flagged_even_if_complete() -> None:
    settings = replace(SETTINGS, max_pages=1)
    run = Run(_script(_page(3)), settings)
    assert run.go() is True


def test_medium_and_cas_are_url_encoded() -> None:
    run = Run(_script(_page(0)))
    run.fetcher.fetch("50-00-0", "AIR/STACK X", run.pages.append)
    assert "m/AIR%2FSTACK%20X/y/2023/rows" in run.urls[0]


def test_a_failing_page_raises_without_hiding_earlier_pages() -> None:
    run = Run(_script(_page(3), httpx.Response(500), httpx.Response(500)))
    with pytest.raises(EfserviceError):
        run.go()
    assert [len(p) for p in run.pages] == [3]  # the caller must discard what it folded in


def test_the_request_asks_only_for_recent_years() -> None:
    """Ten years ending with 2025 (2026 is not published yet): reports after 2015, every page."""
    run = Run(_script(_page(3), _page(1, 3)), replace(SETTINGS, recent_years=10))
    run.go()
    assert all("/y/2015/" in url for url in run.urls)


def test_a_different_window_changes_the_year_in_the_request() -> None:
    run = Run(_script(_page(0)), replace(SETTINGS, recent_years=3))
    run.go()
    assert "/y/2022/" in run.urls[0]
