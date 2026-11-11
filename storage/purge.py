"""The periodic deletion of idle threads (retention by idle time)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

from config.database import DatabaseSettings
from storage.errors import DATABASE_ERRORS
from storage.keys import ThreadKey

logger = logging.getLogger(__name__)
_SECONDS_PER_MINUTE = 60


class Purgeable(Protocol):
    """A thread store that can delete its idle threads."""

    async def purge_idle(self, older_than: timedelta) -> list[ThreadKey]: ...


class UsagePurgeable(Protocol):
    """A quota store that can delete its old daily usage rows."""

    async def purge_usage(self, older_than: timedelta) -> int: ...


@dataclass(frozen=True)
class UsageRetention:
    """Which quota store to purge and how old a usage row may get.

    Attributes:
        store: The quota store.
        older_than: Rows for days before today minus this are deleted.
    """

    store: UsagePurgeable
    older_than: timedelta


async def purge_usage_once(retention: UsageRetention) -> int:
    """Delete usage rows past the retention; the number deleted (0 on a failure)."""
    try:
        return await retention.store.purge_usage(retention.older_than)
    except DATABASE_ERRORS as error:
        logger.warning("Daily usage purge failed: %s", type(error).__name__)
        return 0


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
    usage: UsageRetention | None = None,
) -> None:
    """Purge now, then every ``purge_interval_minutes``, until cancelled.

    Old daily usage rows go in the same pass when ``usage`` is given.
    """
    while True:
        await purge_once(store, settings)
        if usage is not None:
            await purge_usage_once(usage)
        await sleep(settings.purge_interval_minutes * _SECONDS_PER_MINUTE)
