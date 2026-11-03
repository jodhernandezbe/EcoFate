"""Tests for the PubChem response cache and the cached client (no network, no real waits)."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

from config.pubchem import PubchemSettings
from tests.tools.informatics.helpers.pubchem.fakes import FakeClock, FakeJson, settings_in
from tools.http import HttpRequestError, RetryingClient
from tools.informatics.helpers.pubchem.cache import ResponseCache
from tools.informatics.helpers.pubchem.transport import CachedJsonClient, build_client

URL = "https://example.test/a"
PAYLOAD = {"IdentifierList": {"CID": [1]}}


def _cache(tmp_path: Path, clock: FakeClock, days: float = 1.0) -> ResponseCache:
    return ResponseCache(tmp_path / "db" / "c.sqlite", days, clock)


def test_missing_file_is_a_miss_and_creates_nothing(tmp_path: Path) -> None:
    cache = _cache(tmp_path, FakeClock())
    assert cache.get(URL) is None
    assert not (tmp_path / "db").exists()


def test_answer_round_trips(tmp_path: Path) -> None:
    cache = _cache(tmp_path, FakeClock())
    cache.put_ok(URL, PAYLOAD)
    answer = cache.get(URL)
    assert answer is not None and answer.status == 200 and answer.payload == PAYLOAD


def test_not_found_is_cached(tmp_path: Path) -> None:
    cache = _cache(tmp_path, FakeClock())
    cache.put_not_found(URL)
    answer = cache.get(URL)
    assert answer is not None and answer.status == 404


def test_expired_entry_is_ignored_and_replaced(tmp_path: Path) -> None:
    clock = FakeClock()
    cache = _cache(tmp_path, clock, days=1.0)
    cache.put_ok(URL, {"v": 1})
    clock.now += 86_400.0 + 1
    assert cache.get(URL) is None
    cache.put_ok(URL, {"v": 2})
    answer = cache.get(URL)
    assert answer is not None and answer.payload == {"v": 2}


def test_corrupt_file_is_a_miss_with_one_warning(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    path = tmp_path / "c.sqlite"
    path.write_bytes(b"this is not a database" * 50)
    cache = ResponseCache(path, 1.0, FakeClock())
    with caplog.at_level(logging.WARNING):
        assert cache.get(URL) is None
        cache.put_ok(URL, PAYLOAD)
        assert cache.get(URL) is None
    assert len([r for r in caplog.records if "cache" in r.message]) == 1


def test_unwritable_location_does_not_raise(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x")
    cache = ResponseCache(blocker / "sub" / "c.sqlite", 1.0, FakeClock())
    cache.put_ok(URL, PAYLOAD)
    assert cache.get(URL) is None


def test_undecodable_body_is_a_miss(tmp_path: Path) -> None:
    path = tmp_path / "c.sqlite"
    cache = ResponseCache(path, 1.0, FakeClock())
    cache.put_ok(URL, PAYLOAD)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE responses SET body = '{broken'")
    assert cache.get(URL) is None


def test_unserializable_payload_is_not_stored(tmp_path: Path) -> None:
    cache = _cache(tmp_path, FakeClock())
    cache.put_ok(URL, {1, 2})
    assert cache.get(URL) is None


def test_repeated_request_calls_the_service_once(tmp_path: Path) -> None:
    inner = FakeJson({URL: PAYLOAD})
    client = CachedJsonClient(inner, _cache(tmp_path, FakeClock()))
    assert client.get_json(URL) == PAYLOAD
    assert client.get_json(URL) == PAYLOAD
    assert inner.calls == [URL]


def test_cached_not_found_raises_404_without_a_request(tmp_path: Path) -> None:
    inner = FakeJson({})
    client = CachedJsonClient(inner, _cache(tmp_path, FakeClock()))
    for _ in range(2):
        with pytest.raises(HttpRequestError) as caught:
            client.get_json(URL)
        assert caught.value.status_code == 404
    assert inner.calls == [URL]


def test_failure_is_not_cached(tmp_path: Path) -> None:
    inner = FakeJson({URL: HttpRequestError("boom", 500)})
    client = CachedJsonClient(inner, _cache(tmp_path, FakeClock()))
    for _ in range(2):
        with pytest.raises(HttpRequestError):
            client.get_json(URL)
    assert inner.calls == [URL, URL]


def test_expired_entry_calls_the_service_again(tmp_path: Path) -> None:
    clock = FakeClock()
    inner = FakeJson({URL: PAYLOAD})
    client = CachedJsonClient(inner, _cache(tmp_path, clock))
    client.get_json(URL)
    clock.now += 2 * 86_400.0
    client.get_json(URL)
    assert inner.calls == [URL, URL]


def test_no_cache_always_asks(tmp_path: Path) -> None:
    inner = FakeJson({URL: PAYLOAD})
    client = CachedJsonClient(inner, None)
    client.get_json(URL)
    client.get_json(URL)
    assert inner.calls == [URL, URL]
    assert list(tmp_path.iterdir()) == []


@dataclass
class Built:
    client: CachedJsonClient
    requests: list[httpx.Request]
    waits: list[float]
    settings: PubchemSettings


def _build(tmp_path: Path, *responses: httpx.Response, enabled: bool = True) -> Built:
    requests: list[httpx.Request] = []
    waits: list[float] = []
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return queue.pop(0)

    settings = settings_in(tmp_path, enabled)
    transport = httpx.MockTransport(handler)
    client = build_client(settings, waits.append, FakeClock(), transport)
    return Built(client, requests, waits, settings)


def test_every_request_waits_the_configured_delay_and_names_the_application(
    tmp_path: Path,
) -> None:
    run = _build(tmp_path, httpx.Response(200, json={"a": 1}), httpx.Response(200, json={"b": 2}))
    run.client.get_json("https://example.test/one")
    run.client.get_json("https://example.test/two")
    assert run.waits == [run.settings.delay_seconds] * 2
    assert run.settings.delay_seconds >= 0.2
    assert all(r.headers["User-Agent"] == run.settings.user_agent for r in run.requests)


def test_throttled_once_then_success(tmp_path: Path) -> None:
    run = _build(tmp_path, httpx.Response(429), httpx.Response(200, json={"ok": True}))
    assert run.client.get_json(URL) == {"ok": True}
    assert len(run.requests) == 2
    assert run.waits[:2] == [run.settings.delay_seconds, run.settings.backoff_seconds]


def test_retry_after_is_honoured(tmp_path: Path) -> None:
    run = _build(
        tmp_path,
        httpx.Response(503, headers={"Retry-After": "3"}),
        httpx.Response(200, json={}),
    )
    run.client.get_json(URL)
    assert run.waits[1] == min(3.0, run.settings.timeout_seconds)


def test_still_failing_gives_up_after_the_configured_retries(tmp_path: Path) -> None:
    settings = settings_in(tmp_path)
    failing = [httpx.Response(503)] * (settings.max_retries + 1)
    run = _build(tmp_path, *failing)
    with pytest.raises(HttpRequestError, match="after"):
        run.client.get_json(URL)
    assert len(run.requests) == settings.max_retries + 1


def test_not_found_is_final_and_cached(tmp_path: Path) -> None:
    run = _build(tmp_path, httpx.Response(404))
    for _ in range(2):
        with pytest.raises(HttpRequestError) as caught:
            run.client.get_json(URL)
        assert caught.value.status_code == 404
    assert len(run.requests) == 1


def test_disabled_cache_creates_no_file(tmp_path: Path) -> None:
    run = _build(
        tmp_path,
        httpx.Response(200, json={}),
        httpx.Response(200, json={}),
        enabled=False,
    )
    run.client.get_json(URL)
    run.client.get_json(URL)
    assert len(run.requests) == 2
    assert not (tmp_path / "cache.sqlite").exists()


def test_a_slow_service_counts_as_a_failed_attempt(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    settings = settings_in(tmp_path)
    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = CachedJsonClient(RetryingClient(settings, http, lambda _s: None), None)
    with pytest.raises(HttpRequestError, match="ReadTimeout"):
        client.get_json(URL)
