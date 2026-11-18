"""Health checks behind ``GET /api/health``: each answers True or False, never raises or reveals."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from redis.exceptions import RedisError

logger = logging.getLogger(__name__)
HealthCheck = Callable[[], Awaitable[bool]]


async def always_healthy() -> bool:
    """The check of a dependency this process does not use (no Redis in eager mode, tests)."""
    return True


def redis_health_check(
    ping: Callable[[], Awaitable[object]],
    timeout_seconds: float,
) -> HealthCheck:
    """True when ``ping`` answers within ``timeout_seconds``; any Redis or network failure, or the
    timeout, is False and logged by its class name only."""

    async def check() -> bool:
        try:
            async with asyncio.timeout(timeout_seconds):
                await ping()
        except (RedisError, OSError, TimeoutError) as error:
            logger.warning("Redis health check failed: %s", type(error).__name__)
            return False
        return True

    return check


def all_healthy(*checks: HealthCheck) -> HealthCheck:
    """True only when every check is; the checks run concurrently."""

    async def check() -> bool:
        return all(await asyncio.gather(*(each() for each in checks)))

    return check
