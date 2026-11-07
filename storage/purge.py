"""The periodic deletion of idle threads (retention by idle time)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Protocol

from config.database import DatabaseSettings
from storage.errors import DATABASE_ERRORS

logger = logging.getLogger(__name__)
_SECONDS_PER_MINUTE = 60


class Purgeable(Protocol):
    """A thread store that can delete its idle threads."""

    async def purge_idle(self, older_than: timedelta) -> list[str]: ...


async def purge_once(store: Purgeable, settings: DatabaseSettings) -> int:
    """Delete threads idle longer than the retention; the number deleted (0 on a failure)."""
    try:
        purged = await store.purge_idle(timedelta(days=settings.thread_retention_days))
    except DATABASE_ERRORS as error:
        logger.warning("Idle-thread purge failed: %s", type(error).__name__)
        return 0
    if purged:
        logger.info("Purged %d idle thread(s)", len(purged))
    return len(purged)


async def purge_periodically(
    store: Purgeable,
    settings: DatabaseSettings,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Purge now, then every ``purge_interval_minutes``, until cancelled."""
    while True:
        await purge_once(store, settings)
        await sleep(settings.purge_interval_minutes * _SECONDS_PER_MINUTE)
