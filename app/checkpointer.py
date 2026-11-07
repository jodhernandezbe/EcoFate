"""The agent's message history in PostgreSQL: LangGraph's ``AsyncPostgresSaver`` on its own pool.

The checkpoint library owns its tables and migrates them itself (an idempotent ``setup()``);
they are not part of the Alembic migrations. ``agent/`` receives the saver as the
``checkpointer`` argument of ``build_agent`` and knows nothing about PostgreSQL.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from typing import Any, Protocol

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from commons.database_url import libpq_url
from config.database import DatabaseSettings

_MS_PER_SECOND = 1000


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


@asynccontextmanager
async def open_checkpointer(
    url: str,
    settings: DatabaseSettings,
    *,
    search_path: str | None = None,
    pool_factory: Callable[[str, DatabaseSettings, str | None], _Pool] = _new_pool,
    saver_factory: Callable[[Any], _Saver] = AsyncPostgresSaver,
) -> AsyncGenerator[Any]:
    """Open a connection pool and the checkpoint saver on it; close the pool on exit.

    Args:
        url: The connection URL (``postgresql://`` or ``postgresql+psycopg://``).
        settings: Pool size, pool timeout and statement timeout.
        search_path: Schema every connection works in (tests isolate themselves with it).
        pool_factory: Builds the (closed) pool; replaced in tests.
        saver_factory: Builds the saver on the opened pool; replaced in tests.

    Yields:
        The saver, with its tables set up; pass it to ``build_agent(checkpointer=...)``.
    """
    pool = pool_factory(url, settings, search_path)
    await pool.open(wait=True, timeout=settings.pool_timeout_seconds)
    try:
        saver = saver_factory(pool)
        await saver.setup()
        yield saver
    finally:
        await pool.close()
