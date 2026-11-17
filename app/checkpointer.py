"""The agent's message history in PostgreSQL: LangGraph's ``AsyncPostgresSaver`` on its own pool.

The checkpoint library owns its tables and migrates them itself (an idempotent ``setup()``);
they are not part of the Alembic migrations. ``setup()`` is not safe to run concurrently: on a
fresh database the API and every worker process start together, so each runs it under one
PostgreSQL advisory lock and the later ones find the tables already there. ``agent/`` receives
the saver as the ``checkpointer`` argument of ``build_agent`` and knows nothing about PostgreSQL.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any, Protocol

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from commons.database_url import libpq_url
from config.database import DatabaseSettings

_MS_PER_SECOND = 1000
# Names the advisory lock that serialises ``setup()`` across processes (hashed by PostgreSQL).
_SETUP_LOCK = "ecofate.checkpointer.setup"

SetupLock = Callable[[str, DatabaseSettings, str | None], AbstractAsyncContextManager[None]]


class _Pool(Protocol):
    """The part of ``AsyncConnectionPool`` this module uses."""

    async def open(self, wait: bool = ..., timeout: float = ...) -> None: ...

    async def close(self) -> None: ...


class _Saver(Protocol):
    async def setup(self) -> None: ...


def _connection_kwargs(settings: DatabaseSettings, search_path: str | None) -> dict[str, Any]:
    """Connection options the checkpoint library requires, plus the statement time limit."""
    options = f"-c statement_timeout={round(settings.statement_timeout_seconds * _MS_PER_SECOND)}"
    if search_path is not None:
        options += f" -c search_path={search_path}"
    return {"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row, "options": options}


def _new_pool(url: str, settings: DatabaseSettings, search_path: str | None) -> AsyncConnectionPool:
    return AsyncConnectionPool(
        libpq_url(url),
        kwargs=_connection_kwargs(settings, search_path),
        max_size=settings.pool_size,
        timeout=settings.pool_timeout_seconds,
        open=False,
    )


async def _try_lock(connection: AsyncConnection[Any]) -> bool:
    cursor = await connection.execute(
        "SELECT pg_try_advisory_lock(hashtext(%s)) AS ok",
        (_SETUP_LOCK,),
    )
    row = await cursor.fetchone()
    return bool(row and row["ok"] is True)


async def _wait_for_lock(connection: AsyncConnection[Any], settings: DatabaseSettings) -> None:
    """Try the lock until it is free, sleeping between tries (never blocking in a statement:
    the setup's ``CREATE INDEX CONCURRENTLY`` waits for every open statement, including a
    blocked lock wait, which would deadlock with the holder).

    Raises:
        TimeoutError: If the lock is still held after ``setup_lock_timeout_seconds``.
    """
    async with asyncio.timeout(settings.setup_lock_timeout_seconds):
        while not await _try_lock(connection):
            await asyncio.sleep(settings.setup_lock_poll_seconds)


@asynccontextmanager
async def _advisory_setup_lock(
    url: str,
    settings: DatabaseSettings,
    search_path: str | None,
) -> AsyncGenerator[None]:
    """Hold the setup advisory lock on a connection of its own (never one the saver needs).

    The lock is released on exit, and by PostgreSQL when the connection closes (a holder that
    dies never leaves it behind).
    """
    async with await AsyncConnection.connect(
        libpq_url(url),
        connect_timeout=max(1, round(settings.pool_timeout_seconds)),
        **_connection_kwargs(settings, search_path),
    ) as connection:
        await _wait_for_lock(connection, settings)
        try:
            yield
        finally:
            await connection.execute("SELECT pg_advisory_unlock(hashtext(%s))", (_SETUP_LOCK,))


@asynccontextmanager
async def open_checkpointer(
    url: str,
    settings: DatabaseSettings,
    *,
    search_path: str | None = None,
    pool_factory: Callable[[str, DatabaseSettings, str | None], _Pool] = _new_pool,
    saver_factory: Callable[[Any], _Saver] = AsyncPostgresSaver,
    setup_lock: SetupLock = _advisory_setup_lock,
) -> AsyncGenerator[Any]:
    """Open a connection pool and the checkpoint saver on it; close the pool on exit.

    Args:
        url: The connection URL (``postgresql://`` or ``postgresql+psycopg://``).
        settings: Pool size, pool timeout and statement timeout.
        search_path: Schema every connection works in (tests isolate themselves with it).
        pool_factory: Builds the (closed) pool; replaced in tests.
        saver_factory: Builds the saver on the opened pool; replaced in tests.
        setup_lock: Serialises ``setup()`` across processes; replaced in tests.

    Yields:
        The saver, with its tables set up; pass it to ``build_agent(checkpointer=...)``.
    """
    pool = pool_factory(url, settings, search_path)
    await pool.open(wait=True, timeout=settings.pool_timeout_seconds)
    try:
        saver = saver_factory(pool)
        async with setup_lock(url, settings, search_path):
            await saver.setup()
        yield saver
    finally:
        await pool.close()
