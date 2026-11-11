"""Turns whose worker is gone become resumable (``interrupted``), never stuck ``running``.

Run in the worker's main process: at start-up every running turn whose heartbeat is older than
``[worker].stale_after_seconds`` is interrupted (``worker_lost``), and when a task ends because
its child was lost or killed at the hard time limit, its turn is interrupted (``worker_lost`` or
``time_limit``) and its thread released. Nothing is re-run: the user resumes. The ``*_env``
functions open and dispose a short-lived engine each (the main process keeps no connections
across forks); the logic itself takes its stores.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import timedelta
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.task_queue import TurnJob
from app.turns.failures import FailureReason
from config.database import get_database_settings
from config.worker import get_worker_settings
from storage.engine import create_engine, database_url
from storage.keys import ThreadKey
from storage.threads import release_lease
from storage.turn_model import Turn
from storage.turns import TurnRepository

logger = logging.getLogger("worker")
_LOST_CHILD = "WorkerLostError"
_HARD_LIMIT = "TimeLimitExceeded"
_JOB_ARGS = 2  # the turn id and the owner id
Release = Callable[[ThreadKey], Awaitable[None]]


class RecoveryTurns(Protocol):
    """The turn records recovery moves (``storage.turns.TurnRepository``)."""

    async def interrupt_stale(
        self,
        older_than: timedelta,
        reason: str,
        key: ThreadKey | None = None,
    ) -> list[ThreadKey]: ...

    async def abandon(self, owner_id: UUID, turn_id: str, reason: str) -> bool: ...

    async def get(self, owner_id: UUID, turn_id: str) -> Turn | None: ...


async def sweep_stale(turns: RecoveryTurns, release: Release, stale_after: timedelta) -> int:
    """Interrupt every running turn whose heartbeat is stale and release its thread; how many."""
    keys = await turns.interrupt_stale(stale_after, FailureReason.WORKER_LOST)
    for key in keys:
        await release(key)
    if keys:
        logger.info("Interrupted %d turn(s) whose worker was lost", len(keys))
    return len(keys)


async def interrupt_lost(
    turns: RecoveryTurns,
    release: Release,
    job: TurnJob,
    reason: FailureReason,
) -> bool:
    """Interrupt the job's turn if it is still open and release its thread; whether it was."""
    if not await turns.abandon(job.owner_id, job.turn_id, reason):
        return False
    turn = await turns.get(job.owner_id, job.turn_id)
    if turn is not None:
        await release(turn.key)
    return True


def lost_reason(exception: BaseException | None) -> FailureReason | None:
    """The reason a failed task's turn is interrupted: a lost child or the hard time limit;
    None for a failure the job itself already recorded."""
    names: set[str] = set()
    if exception is not None:
        names = {cls.__name__ for cls in type(exception).__mro__}
    if _HARD_LIMIT in names:
        return FailureReason.TIME_LIMIT
    if _LOST_CHILD in names:
        return FailureReason.WORKER_LOST
    return None


def job_of(args: Sequence[object] | None) -> TurnJob | None:
    """The job a failed task named (its arguments are untrusted); None when they do not fit."""
    if args is None or len(args) != _JOB_ARGS:
        return None
    try:
        return TurnJob.from_payload(args[0], args[1])
    except ValueError:
        return None


# --- wired to PostgreSQL ------------------------------------------------------------------------


def _engine(environ: Mapping[str, str]) -> AsyncEngine:
    settings = get_database_settings()
    return create_engine(database_url(environ, settings), settings)


def _stores(engine: AsyncEngine) -> tuple[TurnRepository, Release]:
    sessions: async_sessionmaker[AsyncSession] = async_sessionmaker(engine, expire_on_commit=False)

    async def release(key: ThreadKey) -> None:
        await release_lease(sessions, key)

    return TurnRepository(sessions), release


async def sweep_stale_env(environ: Mapping[str, str]) -> int:
    """``sweep_stale`` against the database the environment names."""
    engine = _engine(environ)
    try:
        stale_after = timedelta(seconds=get_worker_settings().stale_after_seconds)
        return await sweep_stale(*_stores(engine), stale_after)
    finally:
        await engine.dispose()


async def interrupt_lost_env(
    job: TurnJob,
    reason: FailureReason,
    environ: Mapping[str, str],
) -> bool:
    """``interrupt_lost`` against the database the environment names."""
    engine = _engine(environ)
    try:
        return await interrupt_lost(*_stores(engine), job, reason)
    finally:
        await engine.dispose()
