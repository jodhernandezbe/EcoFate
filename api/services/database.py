"""The web program's database at start-up: URL, migration check, checkpointer and thread store.

Migrations never run here (``make migrate`` does that); a database that is missing,
unreachable or behind the latest migration stops the program with a fixed message.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from functools import partial

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from api.schemas.workspace import WorkspaceState
from api.services.threads import ThreadStore
from app.checkpointer import open_checkpointer
from config.database import DatabaseSettings
from storage.engine import DatabaseSetupError, create_engine, database_url
from storage.errors import DATABASE_ERRORS
from storage.health import database_answers
from storage.revisions import is_at_head
from storage.threads import PostgresThreadStore

logger = logging.getLogger(__name__)
UNREACHABLE = (
    "Cannot reach the database named in {variable}. Start it (make db, or docker compose up) "
    "and apply the migrations with `make migrate`."
)
NOT_MIGRATED = "The database is not at the latest migration. Run `make migrate` first."


@dataclass(frozen=True)
class Database:
    """What the app keeps while it serves: the thread store and the health check."""

    threads: ThreadStore
    health_check: Callable[[], Awaitable[bool]]


async def _require_latest_migration(engine: AsyncEngine, settings: DatabaseSettings) -> None:
    try:
        async with engine.connect() as connection:
            at_head = await connection.run_sync(is_at_head)
    except DATABASE_ERRORS as error:
        logger.error("Database check failed at start-up: %s", type(error).__name__)
        raise DatabaseSetupError(UNREACHABLE.format(variable=settings.url_env_var)) from None
    if not at_head:
        raise DatabaseSetupError(NOT_MIGRATED)


@asynccontextmanager
async def _database(url: str, settings: DatabaseSettings) -> AsyncGenerator[Database]:
    engine = create_engine(url, settings)
    try:
        await _require_latest_migration(engine, settings)
        async with open_checkpointer(url, settings) as saver:
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            store = PostgresThreadStore(sessions, saver, settings, WorkspaceState)
            check = partial(database_answers, engine, settings.health_timeout_seconds)
            yield Database(threads=store, health_check=check)
    finally:
        await engine.dispose()


@asynccontextmanager
async def open_database(
    environ: Mapping[str, str],
    settings: DatabaseSettings,
) -> AsyncGenerator[Database]:
    """Open the database for the app's lifetime.

    Raises:
        SystemExit: With a fixed message (naming the variable or ``make migrate``) when the URL
            is missing, the database cannot be reached, or it is not at the latest migration.
    """
    stack = AsyncExitStack()
    try:
        database = await stack.enter_async_context(
            _database(database_url(environ, settings), settings),
        )
    except DatabaseSetupError as error:
        logger.error("%s", error)
        raise SystemExit(str(error)) from None
    async with stack:
        yield database
