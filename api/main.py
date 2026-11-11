"""FastAPI app factory: own-origin CORS, Origin/Host guard, sanitised errors, static frontend."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis

from api.core.config import ui_settings
from api.core.exceptions import install_exception_handlers
from api.core.origin_guard import OriginGuard
from api.core.static import FrontendFiles
from api.routers import (
    v1_account,
    v1_auth,
    v1_chat,
    v1_facilities,
    v1_health,
    v1_monitoring,
    v1_settings,
    v1_usage,
)
from api.services.agent_runner import RelayTiming
from api.services.auth.mailer import Mailer, SmtpMailer
from api.services.auth.runtime import build_auth_runtime
from api.services.auth.smtp import MailSetupError, smtp_server
from api.services.auth.stores import Accounts
from api.services.auth.tokens import SecretSetupError, load_session_secret
from api.services.database import open_database
from api.services.key_setup import (
    KeyServices,
    build_key_services,
    load_key_config,
    protect_process_secrets,
)
from api.services.quota import QuotaService, QuotaStore, UncountedQuota
from api.services.threads import ThreadStore
from api.services.turn_queue import QueueSetup
from app.process_secrets import process_secret_values
from app.redaction import install_redaction
from app.task_queue import (
    BrokerSetupError,
    CeleryEnqueuer,
    TurnEnqueuer,
    build_celery,
    redis_url,
)
from app.telemetry import flush_telemetry
from app.turns import FailureReason
from app.turns.bus import MemoryBus, RedisStreamBus, TurnEventBus
from app.turns.recording import BackgroundSettings
from config.agent import get_agent_settings
from config.auth import get_auth_settings
from config.database import DatabaseSettings, get_database_settings
from config.limits import get_limit_settings
from config.mail import MailSettings, get_mail_settings
from config.telemetry import get_telemetry_settings
from config.ui import UiSettings
from config.worker import WorkerSettings, get_worker_settings
from storage.purge import UsagePurgeable, UsageRetention, purge_periodically

logger = logging.getLogger(__name__)


async def _always_ok() -> bool:
    return True


@asynccontextmanager
async def _purging(
    threads: ThreadStore,
    settings: DatabaseSettings,
    usage: UsageRetention,
) -> AsyncGenerator[None]:
    task = asyncio.create_task(purge_periodically(threads, settings, usage=usage))
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


def _quota_service(store: QuotaStore) -> QuotaService:
    """The daily quota over ``store``, as ``[limits]`` configures it."""
    return QuotaService(store, get_limit_settings())


def _usage_retention(store: UsagePurgeable) -> UsageRetention:
    """Daily usage rows older than ``[limits].retention_days`` go in the idle purge."""
    return UsageRetention(store, timedelta(days=get_limit_settings().retention_days))


async def _recover_turns(threads: ThreadStore, setup: QueueSetup) -> None:
    """Turns whose process stopped become resumable (``worker_lost``): with turns run in this
    process, every open one; with a worker, only running turns whose heartbeat is stale (a
    restart of the API never touches turns the worker is running)."""
    turns = threads.turns
    if setup.enqueuer is None:
        recovered = await turns.interrupt_all_open(FailureReason.WORKER_LOST)
    else:
        recovered = await turns.interrupt_stale(setup.timing.stale_after, FailureReason.WORKER_LOST)
    for key in recovered:
        await threads.release(key)
    if recovered:
        logger.info("Interrupted %d turn(s) whose process stopped", len(recovered))


def _relay_timing(settings: WorkerSettings) -> RelayTiming:
    return RelayTiming(
        block_seconds=settings.relay_block_seconds,
        grace_seconds=settings.broker_timeout_seconds,
        stale_after=timedelta(seconds=settings.stale_after_seconds),
    )


def queue_setup(bus: TurnEventBus, enqueuer: TurnEnqueuer | None) -> QueueSetup:
    """The queue over ``bus`` and ``enqueuer`` (None: turns run in this process), timed as
    ``[worker]`` and ``[agent]`` say."""
    settings = get_worker_settings()
    background = BackgroundSettings.from_config(
        settings,
        get_agent_settings().max_resumes_per_turn,
    )
    return QueueSetup(bus, enqueuer, _relay_timing(settings), background)


def _redis_client(url: str, settings: WorkerSettings) -> Redis:
    """This process's Redis client; a blocking read may wait the relay block plus the timeout."""
    return Redis.from_url(
        url,
        decode_responses=True,
        socket_connect_timeout=settings.broker_timeout_seconds,
        socket_timeout=settings.relay_block_seconds + settings.broker_timeout_seconds,
    )


@asynccontextmanager
async def _worker_queue(environ: Mapping[str, str]) -> AsyncGenerator[QueueSetup]:
    """Redis streams and the Celery queue of the worker; in-process when ``[worker].eager``.

    Raises:
        SystemExit: With a message naming the variable when the Redis URL is not set.
    """
    settings = get_worker_settings()
    if settings.eager:
        yield queue_setup(MemoryBus(), None)
        return
    try:
        url = redis_url(environ, settings)
    except BrokerSetupError as error:
        raise SystemExit(str(error)) from None
    client = _redis_client(url, settings)
    enqueuer = CeleryEnqueuer(build_celery(settings, url), settings, process_secret_values(environ))
    try:
        yield queue_setup(RedisStreamBus(client, settings.event_stream_max_length), enqueuer)
    finally:
        await client.aclose()


def _smtp_mailer(app: FastAPI, mail: MailSettings) -> SmtpMailer:
    """The SMTP mailer the environment configures (container mode: a loopback host is Mailpit)."""
    container = bool(app.state.keys_from_environment)
    server = smtp_server(os.environ, mail, container=container)
    return SmtpMailer(server, mail, os.environ)


def _install_auth(app: FastAPI, threads: ThreadStore, accounts: Accounts) -> None:
    """Build the account services over the stores and the app's mailer and session secret.

    Without an injected secret, the one named in ``[auth]`` is read from the environment; the
    app does not start without it. Without an injected mailer, SMTP is used as configured.
    """
    settings, mail = get_auth_settings(), get_mail_settings()
    try:
        secret = app.state.session_secret or load_session_secret(os.environ, settings)
        mailer: Mailer = app.state.mailer or _smtp_mailer(app, mail)
    except (SecretSetupError, MailSetupError) as error:
        raise SystemExit(str(error)) from None
    app.state.auth = build_auth_runtime(
        accounts=accounts,
        threads=threads,
        mailer=mailer,
        secret=secret,
        settings=settings,
        base_url=mail.app_base_url,
    )


@asynccontextmanager
async def _thread_state(app: FastAPI) -> AsyncGenerator[None]:
    """Open the database, its thread store and accounts, unless they were injected (tests), and
    recover the turns a stopped server left running."""
    if app.state.threads is not None:  # injected (tests): the account services exist already
        await _recover_turns(app.state.threads, app.state.turn_queue)
        yield
        return
    keks, operator = load_key_config(os.environ)  # before the database: names a bad variable
    settings = get_database_settings()
    async with (
        open_database(os.environ, settings) as database,
        _worker_queue(os.environ) as queue,
        _purging(database.threads, settings, _usage_retention(database.quota)),
    ):
        _set_state(app, turn_queue=queue, threads=database.threads)
        _set_state(app, health_check=database.health_check, quota=_quota_service(database.quota))
        app.state.keys = build_key_services(keks, operator, database.credentials)
        _install_auth(app, database.threads, database.accounts)
        await _recover_turns(database.threads, queue)
        yield


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None]:
    install_redaction()
    protect_process_secrets(os.environ, app.state.keys)  # also when the stores are injected
    async with _thread_state(app):
        yield
        await _stop_running(app.state.turn_queue)
    await asyncio.to_thread(flush_telemetry, get_telemetry_settings())  # queued spans go out


async def _stop_running(setup: QueueSetup | None) -> None:
    """Cancel turns still running in this process; they are recovered as ``worker_lost``."""
    if setup is None:
        return
    for task in list(setup.running):
        task.cancel()
    await asyncio.gather(*setup.running, return_exceptions=True)


def _mount_frontend(app: FastAPI, dist: Path) -> None:
    if (dist / "index.html").is_file():
        app.mount("/", FrontendFiles(directory=dist, html=True), name="frontend")


def _add_middleware(app: FastAPI, ui: UiSettings) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[ui.origin],
        allow_methods=["GET", "POST", "DELETE"],
    )
    app.add_middleware(OriginGuard, origin=ui.origin)  # outermost: runs before CORS and routes


def _include_routers(app: FastAPI) -> None:
    for module in (v1_health, v1_auth, v1_account, v1_settings, v1_chat, v1_facilities):
        app.include_router(module.router)
    app.include_router(v1_settings.public_router)
    app.include_router(v1_monitoring.router)
    app.include_router(v1_usage.router)


def _injected_quota(store: QuotaStore | None) -> QuotaService:
    """The quota of a test app: over its store, or switched off when none was injected."""
    if store is not None:
        return _quota_service(store)
    return QuotaService(UncountedQuota(), replace(get_limit_settings(), enabled=False))


def _require_injected_together(
    threads: ThreadStore | None,
    accounts: Accounts | None,
    keys: KeyServices | None,
) -> None:
    """Injected stores come as a set: the thread store with the accounts and the key services."""
    if threads is not None and accounts is None:
        raise ValueError("inject the account stores together with the thread store")
    if threads is not None and keys is None:
        raise ValueError("inject the key services together with the thread store")


def _set_state(app: FastAPI, **state: object) -> None:
    """Keep what the routes read (stores, services, flags) on the app, by name."""
    for name, value in state.items():
        setattr(app.state, name, value)


def create_app(
    settings: UiSettings | None = None,
    *,
    keys_from_environment: bool = False,
    keys: KeyServices | None = None,
    quota: QuotaStore | None = None,
    threads: ThreadStore | None = None,
    health_check: Callable[[], Awaitable[bool]] | None = None,
    accounts: Accounts | None = None,
    mailer: Mailer | None = None,
    session_secret: bytes | None = None,
    turn_queue: QueueSetup | None = None,
) -> FastAPI:
    """Build the API for ``settings`` (the shipped ``[ui]`` settings by default).

    Args:
        settings: The UI settings.
        keys_from_environment: The app runs in a container: a loopback SMTP host is Mailpit.
            Keys do not depend on it: each user's OpenAI key is read from their encrypted row and
            the operator's Census and CompTox keys from the environment, in every mode.
        keys: The user key vault and operator keys to use with an injected ``threads`` (tests);
            with none injected the database and the environment provide them.
        quota: The store counting daily turns, with an injected ``threads`` (tests); None then
            means no quota. With none injected the database provides it, limited as ``[limits]``
            says.
        threads: A thread store to use instead of opening the database (tests); None opens
            PostgreSQL at start-up and refuses to start without a migrated database.
        health_check: Replaces the database check of ``GET /api/health`` (tests).
        accounts: The account stores to use with an injected ``threads`` (tests); with none
            injected the database provides them.
        mailer: Sends the account emails; None sends them over the configured SMTP server.
        session_secret: The secret that keys the stored session and token hashes (tests); None
            reads the variable named in ``[auth]``, and the app refuses to start without it.
        turn_queue: The turn streams and queue to use with an injected ``threads`` (tests);
            None then runs turns in this process over in-memory streams. With none injected,
            Redis and the worker's queue (or this process, when ``[worker].eager``).
    """
    _require_injected_together(threads, accounts, keys)
    ui = settings if settings is not None else ui_settings()
    app = FastAPI(title="EcoFate API", lifespan=_lifespan, docs_url=None, redoc_url=None)
    _add_middleware(app, ui)
    _set_state(app, threads=threads, accounts=accounts, mailer=mailer)
    _set_state(app, session_secret=session_secret, health_check=health_check or _always_ok)
    _set_state(app, keys_from_environment=keys_from_environment, keys=keys)
    _set_state(app, quota=_injected_quota(quota))
    injected_queue = turn_queue or (queue_setup(MemoryBus(), None) if threads is not None else None)
    _set_state(app, turn_queue=injected_queue)
    install_exception_handlers(app)
    _include_routers(app)
    if threads is not None and accounts is not None:
        _install_auth(app, threads, accounts)
    _mount_frontend(app, ui.frontend_dist)
    return app
