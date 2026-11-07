"""A real PostgreSQL for ``postgres``-marked tests: one fresh, migrated schema per test.

Skipped unless ``ECOFATE_TEST_DATABASE_URL`` is set (``make test-db`` sets it). The schema is
dropped afterwards, checkpoints included.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from api.schemas.workspace import WorkspaceState
from app.checkpointer import open_checkpointer
from config.database import DatabaseSettings
from storage.engine import create_engine
from storage.revisions import alembic_config
from storage.threads import PostgresThreadStore

URL_VARIABLE = "ECOFATE_TEST_DATABASE_URL"
SETTINGS = DatabaseSettings(
    url_env_var=URL_VARIABLE,
    pool_size=4,
    pool_timeout_seconds=10.0,
    statement_timeout_seconds=30.0,
    health_timeout_seconds=2.0,
    turn_lease_seconds=600.0,
    thread_retention_days=30,
    purge_interval_minutes=60,
)


def test_url() -> str:
    """The test database URL, or skip the test when none is configured."""
    url = os.environ.get(URL_VARIABLE, "").strip()
    if not url:
        pytest.skip(f"{URL_VARIABLE} is not set (run make test-db)")
    return url


test_url.__test__ = False  # type: ignore[attr-defined]  # not a test, despite its name


def run_alembic(connection: Connection, action: str, revision: str) -> None:
    """Run ``alembic <action> <revision>`` on an open connection (its schema)."""
    config = alembic_config()
    config.attributes["connection"] = connection
    getattr(command, action)(config, revision)


@dataclass
class Database:
    """One isolated schema: its engine, store and checkpointer."""

    url: str
    schema: str
    engine: AsyncEngine
    store: PostgresThreadStore[WorkspaceState]
    checkpointer: Any


async def _execute(url: str, statement: str) -> None:
    admin = create_engine(url, SETTINGS)
    try:
        async with admin.begin() as connection:
            await connection.execute(text(statement))
    finally:
        await admin.dispose()


@asynccontextmanager
async def migrated_schema(url: str, schema: str | None = None) -> AsyncGenerator[AsyncEngine]:
    """A new schema migrated to head (dropped on exit); yields an engine bound to it."""
    name = schema or f"test_{uuid4().hex[:16]}"
    await _execute(url, f'CREATE SCHEMA "{name}"')
    engine = create_engine(url, SETTINGS, search_path=name)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(run_alembic, "upgrade", "head")
        yield engine
    finally:
        await engine.dispose()
        await _execute(url, f'DROP SCHEMA "{name}" CASCADE')


@asynccontextmanager
async def database() -> AsyncGenerator[Database]:
    """A migrated schema with a store and checkpointer on it."""
    url = test_url()
    schema = f"test_{uuid4().hex[:16]}"
    async with (
        migrated_schema(url, schema) as engine,
        open_checkpointer(url, SETTINGS, search_path=schema) as saver,
    ):
        store = PostgresThreadStore(async_sessionmaker(engine), saver, SETTINGS, WorkspaceState)
        yield Database(url, schema, engine, store, saver)
