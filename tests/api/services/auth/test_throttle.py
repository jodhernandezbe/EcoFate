"""Attempt counters and the client address."""

from __future__ import annotations

import pytest

from api.services.auth.throttle import attempt_keys, client_address, email_key
from tests.api.auth_support import make_auth

pytestmark = pytest.mark.anyio


def test_without_a_trusted_proxy_the_forwarded_header_is_ignored() -> None:
    assert client_address("198.51.100.2", "6.6.6.6", 0) == "198.51.100.2"
    assert client_address(None, "6.6.6.6", 0) == "unknown"


def test_with_trusted_proxies_the_entry_that_many_from_the_right_is_the_client() -> None:
    assert client_address("10.0.0.1", "6.6.6.6, 203.0.113.9", 1) == "203.0.113.9"
    assert client_address("10.0.0.1", "6.6.6.6, 203.0.113.9, 10.0.0.2", 2) == "203.0.113.9"


def test_a_client_cannot_choose_its_address_by_prepending_entries() -> None:
    assert client_address("10.0.0.1", "1.1.1.1, 2.2.2.2, 203.0.113.9", 1) == "203.0.113.9"


def test_a_missing_or_too_short_header_falls_back_to_the_socket() -> None:
    assert client_address("10.0.0.1", None, 1) == "10.0.0.1"
    assert client_address("10.0.0.1", "", 1) == "10.0.0.1"
    assert client_address("10.0.0.1", "203.0.113.9", 2) == "10.0.0.1"


def test_keys_are_scoped_and_the_email_is_case_folded() -> None:
    assert attempt_keys("login", "Ana@Example.com", "1.2.3.4") == [
        "login-ip:1.2.3.4",
        "login-email:ana@example.com",
    ]
    assert attempt_keys("login", None, "1.2.3.4") == ["login-ip:1.2.3.4"]
    assert email_key("login", " A@B.c ") != email_key("recover", "a@b.c")


async def test_a_key_over_the_limit_must_wait_and_others_may_try() -> None:
    kit = make_auth()
    keys = attempt_keys("login", "a@example.com", "1.2.3.4")
    for _ in range(kit.settings.throttle.attempts):
        assert await kit.throttle.retry_after(keys) is None
        await kit.throttle.fail(keys)
    wait = await kit.throttle.retry_after(keys)
    assert wait is not None and 1 <= wait <= kit.settings.throttle.window_seconds
    assert await kit.throttle.retry_after(attempt_keys("login", "b@example.com", "5.6.7.8")) is None
    ip_only = attempt_keys("login", "b@example.com", "1.2.3.4")  # same address, other account
    assert await kit.throttle.retry_after(ip_only) is not None


async def test_the_window_ends_and_a_success_forgives() -> None:
    kit = make_auth()
    keys = attempt_keys("login", "a@example.com", "1.2.3.4")
    for _ in range(kit.settings.throttle.attempts):
        await kit.throttle.fail(keys)
    kit.clock.advance(kit.settings.throttle.window_seconds + 1)
    assert await kit.throttle.retry_after(keys) is None
    for _ in range(kit.settings.throttle.attempts):
        await kit.throttle.fail(keys)
    await kit.throttle.forgive(keys)
    assert await kit.throttle.retry_after(keys) is None
