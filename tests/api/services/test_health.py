"""Tests for the health checks behind GET /api/health (database and Redis)."""

from __future__ import annotations

import asyncio
import logging

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from api.services.health import all_healthy, always_healthy, redis_health_check

pytestmark = pytest.mark.anyio


async def _pong() -> object:
    return True


async def _refused() -> object:
    raise RedisConnectionError("redis://:s3cr3t@redis:6379 refused")  # pragma: allowlist secret


async def _network_down() -> object:
    raise OSError("no route to host")


async def _hangs() -> object:
    await asyncio.sleep(10)
    return True


async def _down() -> bool:
    return False


async def test_redis_answering_is_healthy() -> None:
    assert await redis_health_check(_pong, 1.0)() is True


@pytest.mark.parametrize("ping", [_refused, _network_down])
async def test_a_redis_or_network_error_is_unhealthy(ping: object) -> None:
    assert await redis_health_check(ping, 1.0)() is False  # pyright: ignore[reportArgumentType]


async def test_a_redis_that_does_not_answer_in_time_is_unhealthy() -> None:
    assert await redis_health_check(_hangs, 0.05)() is False


async def test_a_failure_is_logged_by_class_name_only(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        await redis_health_check(_refused, 1.0)()
    assert "ConnectionError" in caplog.text
    assert "s3cr3t" not in caplog.text and "redis://" not in caplog.text


async def test_all_healthy_needs_every_check() -> None:
    assert await all_healthy(always_healthy, always_healthy)() is True
    assert await all_healthy(always_healthy, _down)() is False
    assert await all_healthy(_down, always_healthy)() is False


async def test_the_checks_run_concurrently() -> None:
    slow = redis_health_check(_hangs, 0.2)
    started = asyncio.get_running_loop().time()
    assert await all_healthy(slow, slow, slow)() is False
    assert asyncio.get_running_loop().time() - started < 0.5
