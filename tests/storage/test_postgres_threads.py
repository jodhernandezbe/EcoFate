"""PostgreSQL behaviour of the store and the migrations (``postgres`` marker; make test-db).

Each test works in its own schema (``tests/postgres.py``), dropped afterwards.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from api.schemas.workspace import WorkspaceState
from app.checkpointer import open_checkpointer
from app.usage_meter import CallUsage
from storage.engine import create_engine
from storage.revisions import current_revision, head_revision
from storage.tables import TABLES
from storage.threads import PostgresThreadStore
from tests.postgres import SETTINGS, Database, database, migrated_schema, run_alembic, test_url

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]
THREAD = "pg-thread"
_SCHEMA_SNAPSHOT = text(
    """
    SELECT 'column', table_name || '.' || column_name || ' ' || data_type || ' ' || is_nullable
      FROM information_schema.columns WHERE table_schema = current_schema()
    UNION ALL
    SELECT 'constraint',
           conrelid::regclass::text || ' ' || conname || ' ' || pg_get_constraintdef(oid)
      FROM pg_constraint WHERE connamespace = current_schema()::regnamespace
    UNION ALL
    SELECT 'index', indexdef FROM pg_indexes WHERE schemaname = current_schema()
    ORDER BY 1, 2
    """,
)


async def _snapshot(engine: AsyncEngine) -> list[tuple[str, str]]:
    async with engine.connect() as connection:
        return [(row[0], row[1]) for row in await connection.execute(_SCHEMA_SNAPSHOT)]


async def _tables(engine: AsyncEngine) -> set[str]:
    query = text(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()",
    )
    async with engine.connect() as connection:
        return {row[0] for row in await connection.execute(query)}


async def _run(engine: AsyncEngine, action: str, revision: str) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(run_alembic, action, revision)


async def _sql(db: Database, statement: str, **values: object) -> None:
    async with db.engine.begin() as connection:
        await connection.execute(text(statement), values)


async def _turn(store: PostgresThreadStore[WorkspaceState], words: str) -> None:
    def reply(state: MessagesState) -> dict[str, list[AIMessage]]:
        return {"messages": [AIMessage(f"seen {len(state['messages'])}")]}

    graph = StateGraph(MessagesState)
    graph.add_node("reply", reply)
    graph.add_edge(START, "reply")
    graph.add_edge("reply", END)
    agent = graph.compile(checkpointer=store.checkpointer)
    await agent.ainvoke(
        {"messages": [HumanMessage(words)]},
        {"configurable": {"thread_id": THREAD}},
    )


# --- migrations -----------------------------------------------------------------------------


async def test_migrations_create_every_table_at_head() -> None:
    async with migrated_schema(test_url()) as engine:
        assert {table.name for table in TABLES} | {"alembic_version"} == await _tables(engine)
        async with engine.connect() as connection:
            assert await connection.run_sync(current_revision) == head_revision()


async def test_migrations_round_trip_to_the_same_schema() -> None:
    async with migrated_schema(test_url()) as engine:
        first = await _snapshot(engine)
        await _run(engine, "downgrade", "base")
        assert await _tables(engine) == {"alembic_version"}
        await _run(engine, "upgrade", "head")
        assert await _snapshot(engine) == first


# --- leases ---------------------------------------------------------------------------------


async def test_concurrent_claims_from_two_processes_let_exactly_one_win() -> None:
    async with database() as db:
        other = create_engine(db.url, SETTINGS, search_path=db.schema)
        try:
            second = PostgresThreadStore(
                async_sessionmaker(other),
                db.checkpointer,
                SETTINGS,
                WorkspaceState,
            )
            for trial in range(10):
                thread = f"race-{trial}"
                results = await asyncio.gather(db.store.claim(thread), second.claim(thread))
                assert sorted(results) == [False, True], thread
        finally:
            await other.dispose()


async def test_an_expired_lease_can_be_claimed() -> None:
    async with database() as db:
        assert await db.store.claim(THREAD)
        assert not await db.store.claim(THREAD)
        await _sql(
            db,
            "UPDATE threads SET busy_until = now() - interval '1 second' WHERE id = :id",
            id=THREAD,
        )
        assert not await db.store.running(THREAD)
        assert await db.store.claim(THREAD)


# --- retention ------------------------------------------------------------------------------


async def test_purge_deletes_old_idle_threads_with_their_checkpoints_and_keeps_busy_ones() -> None:
    async with database() as db:
        await _turn(db.store, "one")
        await db.store.add_usage(THREAD, [CallUsage("m", 1, 0, 1)])
        await db.store.record_answers(THREAD, {"a": 1.0}, ["b"])
        await db.store.claim("busy")
        await db.store.touch("recent")
        await _sql(
            db,
            "UPDATE threads SET last_used_at = now() - interval '40 days' WHERE id <> 'recent'",
        )
        purged = await db.store.purge_idle(timedelta(days=30))
        assert purged == [THREAD]
        assert not await db.store.holds(THREAD)
        assert await db.checkpointer.aget_tuple({"configurable": {"thread_id": THREAD}}) is None
        assert await db.store.session_calls(THREAD) == []
        assert await db.store.answers(THREAD) == ({}, frozenset())
        assert await db.store.holds("busy")
        assert await db.store.holds("recent")


# --- untrusted rows -------------------------------------------------------------------------


async def test_a_malformed_workspace_reads_as_absent_with_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async with database() as db:
        await db.store.touch(THREAD)
        await _sql(
            db,
            "INSERT INTO thread_workspaces (thread_id, state) VALUES (:id, CAST(:state AS jsonb))",
            id=THREAD,
            state='{"framing_version": "not a number"}',
        )
        with caplog.at_level(logging.WARNING, logger="storage.codec"):
            assert await db.store.workspace(THREAD) is None
        assert THREAD in caplog.text


async def test_a_nan_supplied_value_is_not_returned() -> None:
    async with database() as db:
        await db.store.record_answers(THREAD, {"good": 2.0}, [])
        await _sql(
            db,
            "INSERT INTO thread_answers (thread_id, key, value, declined) "
            "VALUES (:id, 'bad', 'NaN', false)",
            id=THREAD,
        )
        assert await db.store.answers(THREAD) == ({"good": 2.0}, frozenset())


async def test_a_failing_statement_does_not_show_its_values() -> None:
    async with database() as db:
        with pytest.raises(IntegrityError) as failed:
            await _sql(
                db,
                "INSERT INTO thread_answers (thread_id, key, value) VALUES (:id, 'k', :value)",
                id="no-such-thread",
                value=987654.321,
            )
        assert "987654.321" not in str(failed.value)
        assert "no-such-thread" not in str(failed.value).split("[SQL:")[-1]


# --- durability -----------------------------------------------------------------------------


async def test_a_new_engine_and_checkpointer_see_the_thread_written_by_the_first() -> None:
    async with database() as db:
        await _turn(db.store, "one")
        await _turn(db.store, "two")
        await db.store.set_workspace(THREAD, WorkspaceState(framing_version=4))
        await db.store.add_usage(THREAD, [CallUsage("m", 3, 1, 2)])
        restarted = create_engine(db.url, SETTINGS, search_path=db.schema)
        try:
            async with open_checkpointer(db.url, SETTINGS, search_path=db.schema) as saver:
                store = PostgresThreadStore(
                    async_sessionmaker(restarted),
                    saver,
                    SETTINGS,
                    WorkspaceState,
                )
                assert [m.content for m in await store.messages(THREAD)] == [
                    "one",
                    "seen 1",
                    "two",
                    "seen 3",
                ]
                assert await store.workspace(THREAD) == WorkspaceState(framing_version=4)
                assert await store.session_calls(THREAD) == [CallUsage("m", 3, 1, 2)]
                await _turn(store, "three")
                assert len(await store.messages(THREAD)) == 6
        finally:
            await restarted.dispose()
