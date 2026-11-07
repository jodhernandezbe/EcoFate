"""Whether the database answers: ``SELECT 1`` within a time limit."""

from __future__ import annotations

import asyncio
import logging
from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol

from sqlalchemy import text

from storage.errors import DATABASE_ERRORS

logger = logging.getLogger(__name__)


class Connectable(Protocol):
    """The part of ``AsyncEngine`` the check uses."""

    def connect(self) -> AbstractAsyncContextManager[Any]: ...


async def database_answers(engine: Connectable, timeout_seconds: float) -> bool:
    """True when the database answers ``SELECT 1`` within ``timeout_seconds``.

    A failure is logged by its class only (never its text, which may name the host or user).
    """
    try:
        async with asyncio.timeout(timeout_seconds), engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except DATABASE_ERRORS as error:
        logger.warning("Database health check failed: %s", type(error).__name__)
        return False
    return True
