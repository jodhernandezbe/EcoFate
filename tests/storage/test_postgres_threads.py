"""PostgreSQL behaviour of the store and the migrations (``postgres`` marker; make test-db).

Each test works in its own schema (``tests/postgres.py``), dropped afterwards.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from uuid import UUID

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
from storage.keys import ThreadKey
from storage.revisions import current_revision, head_revision
from storage.tables import TABLES
from storage.threads import PostgresThreadStore
from storage.turns import TurnRepository
from tests.postgres import SETTINGS, Database, database, migrated_schema, run_alembic, test_url

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]
THREAD_ID = "pg-thread"
OWNER = UUID(int=1)
KEY = ThreadKey(OWNER, THREAD_ID)
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
        {"configurable": {"thread_id": KEY.checkpoint_id}},
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
    async with database([OWNER]) as db:
        other = create_engine(db.url, SETTINGS, search_path=db.schema)
        try:
            second = PostgresThreadStore(
                async_sessionmaker(other),
                db.checkpointer,
                SETTINGS,
                WorkspaceState,
            )
            for trial in range(10):
                thread = ThreadKey(OWNER, f"race-{trial}")
                results = await asyncio.gather(db.store.claim(thread), second.claim(thread))
                assert sorted(results) == [False, True], thread
        finally:
            await other.dispose()


async def test_an_expired_lease_can_be_claimed() -> None:
    async with database([OWNER]) as db:
        assert await db.store.claim(KEY)
        assert not await db.store.claim(KEY)
        await _sql(
            db,
            "UPDATE threads SET busy_until = now() - interval '1 second' WHERE id = :id",
            id=THREAD_ID,
        )
        assert not await db.store.running(KEY)
        assert await db.store.claim(KEY)


async def test_concurrent_turns_from_two_processes_open_exactly_one() -> None:
    async with database([OWNER]) as db:
        other = create_engine(db.url, SETTINGS, search_path=db.schema)
        try:
            second = TurnRepository(async_sessionmaker(other))
            for trial in range(10):
                thread = ThreadKey(OWNER, f"turn-race-{trial}")
                results = await asyncio.gather(db.store.turns.begin(thread), second.begin(thread))
                assert sorted(result is None for result in results) == [False, True], thread
        finally:
            await other.dispose()


async def test_the_database_refuses_a_second_open_turn_written_directly() -> None:
    async with database([OWNER]) as db:
        assert await db.store.turns.begin(KEY) is not None
        with pytest.raises(IntegrityError):
            await _sql(
                db,
                "INSERT INTO turns (id, user_id, thread_id, status) "
                "VALUES ('direct', :owner, :id, 'queued')",
                owner=OWNER,
                id=THREAD_ID,
            )


# --- retention ------------------------------------------------------------------------------


async def test_purge_deletes_old_idle_threads_with_their_checkpoints_and_keeps_busy_ones() -> None:
    async with database([OWNER]) as db:
        await _turn(db.store, "one")
        await db.store.add_usage(KEY, [CallUsage("m", 1, 0, 1)])
        await db.store.record_answers(KEY, {"a": 1.0}, ["b"])
        await db.store.claim(ThreadKey(OWNER, "busy"))
        await db.store.touch(ThreadKey(OWNER, "recent"))
        await _sql(
            db,
            "UPDATE threads SET last_used_at = now() - interval '40 days' WHERE id <> 'recent'",
        )
        purged = await db.store.purge_idle(timedelta(days=30))
        assert purged == [KEY]
        assert not await db.store.holds(KEY)
        assert (
            await db.checkpointer.aget_tuple({"configurable": {"thread_id": KEY.checkpoint_id}})
            is None
        )
        assert await db.store.session_calls(KEY) == []
        assert await db.store.answers(KEY) == ({}, frozenset())
        assert await db.store.holds(ThreadKey(OWNER, "busy"))
        assert await db.store.holds(ThreadKey(OWNER, "recent"))


# --- untrusted rows -------------------------------------------------------------------------


async def test_a_malformed_workspace_reads_as_absent_with_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async with database([OWNER]) as db:
        await db.store.touch(KEY)
        await _sql(
            db,
            "INSERT INTO thread_workspaces (owner_id, thread_id, state) "
            "VALUES (:owner, :id, CAST(:state AS jsonb))",
            owner=OWNER,
            id=THREAD_ID,
            state='{"framing_version": "not a number"}',
        )
        with caplog.at_level(logging.WARNING, logger="storage.codec"):
            assert await db.store.workspace(KEY) is None
        assert THREAD_ID in caplog.text


async def test_a_nan_supplied_value_is_not_returned() -> None:
    async with database([OWNER]) as db:
        await db.store.record_answers(KEY, {"good": 2.0}, [])
        await _sql(
            db,
            "INSERT INTO thread_answers (owner_id, thread_id, key, value, declined) "
            "VALUES (:owner, :id, 'bad', 'NaN', false)",
            owner=OWNER,
            id=THREAD_ID,
        )
        assert await db.store.answers(KEY) == ({"good": 2.0}, frozenset())


async def test_a_failing_statement_does_not_show_its_values() -> None:
    async with database([OWNER]) as db:
        with pytest.raises(IntegrityError) as failed:
            await _sql(
                db,
                "INSERT INTO thread_answers (owner_id, thread_id, key, value) "
                "VALUES (:owner, :id, 'k', :value)",
                owner=OWNER,
                id="no-such-thread",
                value=987654.321,
            )
        assert "987654.321" not in str(failed.value)
        assert "no-such-thread" not in str(failed.value).split("[SQL:")[-1]


# --- durability -----------------------------------------------------------------------------


async def test_a_new_engine_and_checkpointer_see_the_thread_written_by_the_first() -> None:
    async with database([OWNER]) as db:
        await _turn(db.store, "one")
        await _turn(db.store, "two")
        await db.store.set_workspace(KEY, WorkspaceState(framing_version=4))
        await db.store.add_usage(KEY, [CallUsage("m", 3, 1, 2)])
        restarted = create_engine(db.url, SETTINGS, search_path=db.schema)
        try:
            async with open_checkpointer(db.url, SETTINGS, search_path=db.schema) as saver:
                store = PostgresThreadStore(
                    async_sessionmaker(restarted),
                    saver,
                    SETTINGS,
                    WorkspaceState,
                )
                assert [m.content for m in await store.messages(KEY)] == [
                    "one",
                    "seen 1",
                    "two",
                    "seen 3",
                ]
                assert await store.workspace(KEY) == WorkspaceState(framing_version=4)
                assert await store.session_calls(KEY) == [CallUsage("m", 3, 1, 2)]
                await _turn(store, "three")
                assert len(await store.messages(KEY)) == 6
        finally:
            await restarted.dispose()
