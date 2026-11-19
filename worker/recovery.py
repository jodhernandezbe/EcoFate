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
from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Protocol
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.jobs.failures import JobFailure
from app.jobs.lifecycle import JobLifecycle
from app.jobs.recovery import interrupt_lost_job, sweep_stale_jobs
from app.process_secrets import process_secret_values
from app.task_queue import CeleryEnqueuer, ToolJob, TurnJob, build_celery, redis_url
from app.turns.bus import RedisStreamBus
from app.turns.failures import FailureReason
from app.turns.follow_up import FollowUps
from app.turns.recording import BackgroundSettings
from app.turns.thread_bus import RedisThreadBus
from config.agent import get_agent_settings
from config.database import get_database_settings
from config.worker import get_worker_settings
from storage.engine import create_engine, database_url
from storage.jobs import PostgresJobStore
from storage.keys import ThreadKey
from storage.threads import ThreadLeases, release_lease
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


def tool_job_of(args: Sequence[object] | None) -> ToolJob | None:
    """The job a failed ``ecofate.run_job`` task named (its arguments are untrusted); None when
    they do not fit."""
    if args is None or len(args) != _JOB_ARGS:
        return None
    try:
        return ToolJob.from_payload(args[0], args[1])
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


def _job_store(engine: AsyncEngine) -> PostgresJobStore:
    return PostgresJobStore(async_sessionmaker(engine, expire_on_commit=False))


def _follow_ups(
    environ: Mapping[str, str],
    engine: AsyncEngine,
    client: Redis,
    url: str,
) -> FollowUps:
    """The follow-up service of this process: leases and turns over ``engine``, the chat queue."""
    worker, agent = get_worker_settings(), get_agent_settings()
    leases = ThreadLeases(_sessions(engine), get_database_settings())
    queued_ttl = BackgroundSettings.from_config(worker, agent.max_resumes_per_turn)
    secrets = process_secret_values(environ)
    enqueuer = CeleryEnqueuer(build_celery(worker, url), worker, secrets)
    bus = RedisStreamBus(client, worker.event_stream_max_length)
    return FollowUps(leases, bus, enqueuer, queued_ttl.running_ttl_seconds)


def _sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def _lifecycle(
    environ: Mapping[str, str],
    engine: AsyncEngine,
) -> AsyncGenerator[JobLifecycle]:
    """What a swept or lost job tells the readers and starts: its thread event and follow-up
    turn, over a short-lived Redis client and Celery sender (closed on exit)."""
    worker = get_worker_settings()
    url = redis_url(environ, worker)
    timeout = worker.broker_timeout_seconds
    client = Redis.from_url(url, decode_responses=True, socket_timeout=timeout)
    try:
        thread_bus = RedisThreadBus(client, worker.event_stream_max_length)
        follow_ups = _follow_ups(environ, engine, client, url)
        yield JobLifecycle(thread_bus, worker.event_ttl_seconds, follow_ups)
    finally:
        await client.aclose()


async def sweep_stale_jobs_env(environ: Mapping[str, str]) -> int:
    """``sweep_stale_jobs`` against the database the environment names: running jobs with a
    stale heartbeat, and queued jobs older than the visibility timeout (a lost task message)."""
    engine = _engine(environ)
    try:
        worker = get_worker_settings()
        stale_after = timedelta(seconds=worker.stale_after_seconds)
        unclaimed = timedelta(seconds=worker.visibility_timeout_seconds)
        async with _lifecycle(environ, engine) as lifecycle:
            return await sweep_stale_jobs(
                _job_store(engine),
                stale_after,
                lifecycle.ended,
                unclaimed_after=unclaimed,
            )
    finally:
        await engine.dispose()


async def interrupt_lost_job_env(
    job: ToolJob,
    reason: FailureReason,
    environ: Mapping[str, str],
) -> bool:
    """``interrupt_lost_job`` against the database the environment names (the reason is the
    lost child's or the hard limit's, the same codes a turn uses)."""
    engine = _engine(environ)
    try:
        async with _lifecycle(environ, engine) as lifecycle:
            return await interrupt_lost_job(
                _job_store(engine),
                job,
                JobFailure(reason.value),
                lifecycle.ended,
            )
    finally:
        await engine.dispose()
