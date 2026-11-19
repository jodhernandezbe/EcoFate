"""``PostgresJobStore``: every background tool job's durable record in PostgreSQL.

Every method names the owner in its ``WHERE``: a job of another user is never found (and answers
as an unknown id does). Recording a job is atomic per owner: a transaction-scoped advisory lock on
the owner serialises the count of the owner's open jobs and the insert, so concurrent calls, even
in other processes, never exceed the cap. Each call is one transaction; a status change is one
guarded ``UPDATE``, so a second claim or a late finish changes nothing. The only call across users
is ``interrupt_stale`` (recovery), which returns the jobs it interrupted.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from uuid import UUID

from sqlalchemy import ColumnElement, RowMapping, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql import Executable

from storage.job_codec import job_from_row
from storage.job_model import OPEN_STATUSES, Job, JobOutcome, JobStatus, JsonObject
from storage.keys import ThreadKey
from storage.tables import jobs

Sessions = async_sessionmaker[AsyncSession]
_OPEN = jobs.c.status.in_([status.value for status in OPEN_STATUSES])
_RUNNING = jobs.c.status == JobStatus.RUNNING.value
_QUEUED = jobs.c.status == JobStatus.QUEUED.value


def _decoded(row: RowMapping | None) -> Job | None:
    return None if row is None else job_from_row({str(k): v for k, v in row.items()})


def _mine(owner_id: UUID, job_id: str) -> ColumnElement[bool]:
    return (jobs.c.id == job_id) & (jobs.c.owner_id == owner_id)


def _owner_lock(owner_id: UUID) -> Executable:
    """Wait for the owner's lock (held to the end of the transaction)."""
    return select(func.pg_advisory_xact_lock(func.hashtextextended(f"jobs:{owner_id}", 0)))


def _open_count(owner_id: UUID) -> Executable:
    return select(func.count()).select_from(jobs).where(jobs.c.owner_id == owner_id, _OPEN)


def _insert(key: ThreadKey, tool: str, job_input: JsonObject) -> Executable:
    return (
        pg_insert(jobs)
        .values(
            id=uuid.uuid4().hex,
            owner_id=key.owner_id,
            thread_id=key.thread_id,
            tool=tool,
            input=dict(job_input),
            status=JobStatus.QUEUED.value,
        )
        .returning(*jobs.c)
    )


def _ended(status: JobStatus, reason: str | None) -> dict[str, object]:
    return {"status": status.value, "failure_reason": reason, "ended_at": func.now()}


class PostgresJobStore:
    """Records jobs and moves them through their statuses.

    Args:
        sessions: Factory of async sessions (one transaction per call).
    """

    def __init__(self, sessions: Sessions) -> None:
        self._sessions = sessions

    async def create(
        self,
        key: ThreadKey,
        tool: str,
        job_input: JsonObject,
        max_open: int,
    ) -> Job | None:
        """Record a queued job of the thread unless its owner already has ``max_open`` open
        ones (nothing is recorded then). The thread must exist (a job starts inside a turn)."""
        async with self._sessions.begin() as session:
            await session.execute(_owner_lock(key.owner_id))
            if (await session.execute(_open_count(key.owner_id))).scalar_one() >= max_open:
                return None
            return _decoded(
                (await session.execute(_insert(key, tool, job_input))).mappings().first(),
            )

    async def get(self, owner_id: UUID, job_id: str) -> Job | None:
        """The owner's job; None when the owner has no such job (or it does not decode)."""
        query = select(jobs).where(_mine(owner_id, job_id))
        async with self._sessions() as session:
            return _decoded((await session.execute(query)).mappings().first())

    async def _change(
        self,
        where: ColumnElement[bool],
        values: dict[str, object],
    ) -> list[Job]:
        statement = update(jobs).where(where).values(**values).returning(*jobs.c)
        async with self._sessions.begin() as session:
            rows = (await session.execute(statement)).mappings().all()
        return [job for job in map(_decoded, rows) if job is not None]

    async def claim(self, owner_id: UUID, job_id: str) -> Job | None:
        """Move the owner's queued job to running with a first heartbeat; None when it is not
        queued (cancelled, interrupted or already claimed by another delivery)."""
        values: dict[str, object] = {
            "status": JobStatus.RUNNING.value,
            "started_at": func.now(),
            "heartbeat_at": func.now(),
        }
        return next(iter(await self._change(_mine(owner_id, job_id) & _QUEUED, values)), None)

    async def heartbeat(self, owner_id: UUID, job_id: str) -> bool:
        """Record that the owner's running job is alive; whether it is still running."""
        changed = await self._change(
            _mine(owner_id, job_id) & _RUNNING,
            {"heartbeat_at": func.now()},
        )
        return bool(changed)

    async def request_cancel(self, owner_id: UUID, job_id: str) -> bool:
        """Ask the owner's open job to stop; whether it was open (safe to repeat)."""
        changed = await self._change(_mine(owner_id, job_id) & _OPEN, {"cancel_requested": True})
        return bool(changed)

    async def cancel_requested(self, owner_id: UUID, job_id: str) -> bool:
        """Whether the user asked the owner's job to stop."""
        query = select(jobs.c.cancel_requested).where(_mine(owner_id, job_id))
        async with self._sessions() as session:
            return (await session.execute(query)).scalar_one_or_none() is True

    async def finish(self, owner_id: UUID, job_id: str, outcome: JobOutcome) -> Job | None:
        """End the owner's running job with ``outcome``; None (nothing changed) when it is not
        running (a recovery sweep may have interrupted it already)."""
        values = _ended(outcome.status, outcome.reason) | {
            "result_content": None if outcome.content is None else dict(outcome.content),
            "result_artifact": None if outcome.artifact is None else dict(outcome.artifact),
        }
        return next(iter(await self._change(_mine(owner_id, job_id) & _RUNNING, values)), None)

    async def interrupt(self, owner_id: UUID, job_id: str, reason: str) -> Job | None:
        """Interrupt the owner's open job (its worker is gone); None when it is not open."""
        values = _ended(JobStatus.INTERRUPTED, reason)
        return next(iter(await self._change(_mine(owner_id, job_id) & _OPEN, values)), None)

    async def interrupt_stale(self, older_than: timedelta, reason: str) -> list[Job]:
        """Interrupt the running jobs of every user whose heartbeat is older than
        ``older_than`` (their worker was lost); the jobs interrupted."""
        beat = func.coalesce(jobs.c.heartbeat_at, jobs.c.started_at, jobs.c.queued_at)
        stale = _RUNNING & (beat < func.now() - older_than)
        return await self._change(stale, _ended(JobStatus.INTERRUPTED, reason))

    async def for_thread(self, key: ThreadKey) -> list[Job]:
        """The owner's jobs of one thread, oldest first."""
        query = (
            select(jobs)
            .where(jobs.c.owner_id == key.owner_id, jobs.c.thread_id == key.thread_id)
            .order_by(jobs.c.queued_at, jobs.c.id)
        )
        async with self._sessions() as session:
            rows = (await session.execute(query)).mappings().all()
        return [job for job in map(_decoded, rows) if job is not None]
