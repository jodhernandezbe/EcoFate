"""What each worker child process opens once and uses for every turn it runs.

A prefork child gets its own event loop, database engine, checkpointer pool, Redis client, key
vault and operator keys, opened in ``worker_process_init`` (never inherited across the fork) and
closed when the child stops. Every task of the child runs on that loop.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from contextlib import AsyncExitStack
from dataclasses import dataclass
from functools import partial

from celery import Celery
from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, SecretStr
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from agent.jobs import job_runners
from app.chat_model import build_chat_model
from app.checkpointer import open_checkpointer
from app.jobs.gateway import JobGateway
from app.jobs.lifecycle import JobLifecycle
from app.jobs.runner import run_background_job
from app.jobs.services import JobServices, JobSettings
from app.operator_keys import OperatorKeys, load_operator_keys
from app.process_secrets import process_secret_values
from app.task_queue import (
    CeleryEnqueuer,
    CeleryToolJobEnqueuer,
    ToolJob,
    TurnJob,
    build_celery,
    redis_url,
)
from app.turns.bus import RedisStreamBus
from app.turns.follow_up import FollowUps
from app.turns.job import run_background_turn
from app.turns.keys import load_turn_keys
from app.turns.recording import BackgroundServices, BackgroundSettings
from app.turns.thread_bus import RedisThreadBus
from app.user_key_vault import UserKeyVault, load_keks
from app.web_turn import web_turn_settings
from config.agent import AgentSettings, get_agent_settings
from config.byok import get_byok_settings
from config.database import get_database_settings
from config.loader import get_comptox_settings
from config.population import get_population_settings
from config.ui import get_ui_settings
from config.worker import WorkerSettings, get_worker_settings
from storage.engine import DatabaseSetupError, create_engine, database_url
from storage.jobs import PostgresJobStore
from storage.quota import QuotaRepository
from storage.revisions import is_at_head
from storage.threads import PostgresThreadStore
from storage.user_credentials import CredentialRepository

logger = logging.getLogger("worker")
NOT_MIGRATED = "The database is not at the latest migration. Run `make migrate` first."


@dataclass(frozen=True)
class WorkerServices:
    """What one child runs its two tasks with: the turn's services and the job's."""

    turns: BackgroundServices
    jobs: JobServices


@dataclass
class ChildRuntime:
    """One child's loop, its services and what closes them."""

    loop: asyncio.AbstractEventLoop
    services: WorkerServices
    stack: AsyncExitStack

    def run(self, job: TurnJob) -> None:
        """Run one turn on the child's loop (returns when its stream has ended)."""
        self.loop.run_until_complete(run_background_turn(job, self.services.turns))

    def run_job(self, job: ToolJob) -> None:
        """Run one background tool job on the child's loop (returns when it has ended)."""
        self.loop.run_until_complete(run_background_job(job, self.services.jobs))

    def close(self) -> None:
        """Close the services and the loop."""
        self.loop.run_until_complete(self.stack.aclose())
        self.loop.close()


def open_child(environ: Mapping[str, str]) -> ChildRuntime:
    """Open a child's services on a new loop.

    Raises:
        DatabaseSetupError: The database URL is missing or the database is not migrated.
        BrokerSetupError: The Redis URL is missing.
        KekConfigurationError: A key-encryption key is missing or malformed.
    """
    loop = asyncio.new_event_loop()
    stack = AsyncExitStack()
    services = loop.run_until_complete(open_services(environ, stack))
    return ChildRuntime(loop, services, stack)


async def open_services(environ: Mapping[str, str], stack: AsyncExitStack) -> WorkerServices:
    """The worker's collaborators over PostgreSQL and Redis, closed by ``stack``."""
    database, worker = get_database_settings(), get_worker_settings()
    url = database_url(environ, database)
    engine = create_engine(url, database)
    stack.push_async_callback(engine.dispose)
    await _require_latest_migration(engine)
    saver = await stack.enter_async_context(open_checkpointer(url, database))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    # The worker never reads a workspace, so no workspace model is needed to validate one.
    threads = PostgresThreadStore(sessions, saver, database, BaseModel)
    redis = await _redis(environ, worker, stack)
    queue = _Queue(redis, build_celery(worker, redis_url(environ, worker)), worker, environ)
    operator = _operator_keys(environ)
    jobs = _job_services(threads.jobs, operator, queue, _follow_ups(threads, queue))
    turns = _turn_services(threads, _vault(environ, sessions), operator, queue, sessions)
    return WorkerServices(turns, jobs)


@dataclass(frozen=True)
class _Queue:
    """What reaches the other side of the queues from this child: Redis streams and Celery."""

    redis: Redis
    celery: Celery
    worker: WorkerSettings
    environ: Mapping[str, str]

    @property
    def secrets(self) -> list[str]:
        """Values that must never appear in a task message."""
        return list(process_secret_values(self.environ))

    @property
    def thread_bus(self) -> RedisThreadBus:
        return RedisThreadBus(self.redis, self.worker.event_stream_max_length)

    @property
    def turn_bus(self) -> RedisStreamBus:
        return RedisStreamBus(self.redis, self.worker.event_stream_max_length)


def _follow_ups(threads: PostgresThreadStore[BaseModel], queue: _Queue) -> FollowUps:
    """Records and starts the follow-up turns of ended jobs (a turn goes to the chat queue)."""
    background = BackgroundSettings.from_config(
        queue.worker,
        get_agent_settings().max_resumes_per_turn,
    )
    enqueuer = CeleryEnqueuer(queue.celery, queue.worker, queue.secrets)
    return FollowUps(threads, queue.turn_bus, enqueuer, background.running_ttl_seconds)


def _job_gateway(store: PostgresJobStore, queue: _Queue) -> JobGateway:
    enqueuer = CeleryToolJobEnqueuer(queue.celery, queue.worker, queue.secrets)
    limit = queue.worker.max_open_jobs_per_user
    return JobGateway(store, enqueuer, limit, queue.thread_bus, queue.worker.event_ttl_seconds)


def _turn_services(
    threads: PostgresThreadStore[BaseModel],
    vault: UserKeyVault,
    operator: OperatorKeys,
    queue: _Queue,
    sessions: async_sessionmaker[AsyncSession],
) -> BackgroundServices:
    """The chat turn's collaborators, with the job system the heavy tools queue their jobs in."""
    worker = queue.worker
    agent = get_agent_settings()
    return BackgroundServices(
        threads=threads,
        bus=queue.turn_bus,
        load_keys=partial(load_turn_keys, vault, operator),
        build_model=partial(_build_model, agent),
        refund=QuotaRepository(sessions).refund,
        turn_settings=web_turn_settings(),
        settings=BackgroundSettings.from_config(worker, agent.max_resumes_per_turn),
        jobs=_job_gateway(threads.jobs, queue),
        job_store=threads.jobs,
        thread_bus=queue.thread_bus,
        follow_ups=_follow_ups(threads, queue),
    )


def _job_services(
    store: PostgresJobStore,
    operator: OperatorKeys,
    queue: _Queue,
    follow_ups: FollowUps,
) -> JobServices:
    """The job runner's collaborators: the jobs table, the heavy tools and the operator's keys
    (a job never reads the user's model key, so it has no vault), and what follows a job."""
    lifecycle = JobLifecycle(queue.thread_bus, queue.worker.event_ttl_seconds, follow_ups)
    return JobServices(
        store=store,
        runners=job_runners(),
        operator=operator,
        settings=JobSettings.from_config(queue.worker),
        on_job_ended=lifecycle.ended,
        on_job_started=lifecycle.started,
    )


def _vault(environ: Mapping[str, str], sessions: async_sessionmaker[AsyncSession]) -> UserKeyVault:
    """The one decrypter of the users' OpenAI keys, under the key-encryption keys of ``[byok]``."""
    keks = load_keks(environ, get_byok_settings())
    return UserKeyVault(CredentialRepository(sessions), keks, get_ui_settings().max_key_length)


async def _require_latest_migration(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        if not await connection.run_sync(is_at_head):
            raise DatabaseSetupError(NOT_MIGRATED)


async def _redis(
    environ: Mapping[str, str],
    settings: WorkerSettings,
    stack: AsyncExitStack,
) -> Redis:
    """This child's Redis client; a blocking read may wait the relay block plus the timeout."""
    timeout = settings.broker_timeout_seconds
    client = Redis.from_url(
        redis_url(environ, settings),
        decode_responses=True,
        socket_connect_timeout=timeout,
        socket_timeout=settings.relay_block_seconds + timeout,
    )
    stack.push_async_callback(client.aclose)
    return client


def _build_model(settings: AgentSettings, key: SecretStr) -> BaseChatModel:
    return build_chat_model(settings, api_key=key)


def _operator_keys(environ: Mapping[str, str]) -> OperatorKeys:
    return load_operator_keys(
        environ,
        get_population_settings().api_key_env_var,
        get_comptox_settings().api_key_env_var,
    )
