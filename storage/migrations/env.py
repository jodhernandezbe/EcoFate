"""Alembic environment: asynchronous, URL only from the environment (or a test's connection)."""

from __future__ import annotations

import asyncio
import os

from alembic import context
from sqlalchemy.engine import Connection

from config.database import get_database_settings
from storage.engine import create_engine, database_url
from storage.tables import metadata

config = context.config


def _migrate(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def _migrate_from_environment() -> None:
    settings = get_database_settings()
    engine = create_engine(database_url(os.environ, settings), settings)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_migrate)
    finally:
        await engine.dispose()


def run() -> None:
    """Run on the connection a caller handed over, else on the database in the environment."""
    handed_over = config.attributes.get("connection")
    if handed_over is not None:
        _migrate(handed_over)
    else:
        asyncio.run(_migrate_from_environment())


run()
