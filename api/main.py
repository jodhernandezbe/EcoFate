"""FastAPI app factory: own-origin CORS, Origin/Host guard, sanitised errors, static frontend."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.core.config import ui_settings
from api.core.exceptions import install_exception_handlers
from api.core.origin_guard import OriginGuard
from api.dependencies import key_variables
from api.routers import (
    v1_account,
    v1_auth,
    v1_chat,
    v1_facilities,
    v1_health,
    v1_monitoring,
    v1_settings,
)
from api.services.auth.mailer import Mailer, SmtpMailer
from api.services.auth.runtime import build_auth_runtime
from api.services.auth.smtp import MailSetupError, smtp_server
from api.services.auth.stores import Accounts
from api.services.auth.tokens import SecretSetupError, load_session_secret
from api.services.database import open_database
from api.services.threads import ThreadStore
from app.redaction import install_redaction, protect_secrets
from app.telemetry import flush_telemetry
from app.turns import FailureReason
from config.auth import get_auth_settings
from config.database import DatabaseSettings, get_database_settings
from config.mail import MailSettings, get_mail_settings
from config.telemetry import get_telemetry_settings
from config.ui import UiSettings
from storage.purge import purge_periodically

logger = logging.getLogger(__name__)


def _environment_keys() -> list[str]:
    """The values of the API-key environment variables that are set (never logged)."""
    monitoring = get_telemetry_settings()
    names = (
        *key_variables().values(),
        monitoring.write_token_env_var,
        monitoring.read_token_env_var,
        get_database_settings().url_env_var,  # the URL carries the database password
    )
    return [value.strip() for name in names if (value := os.environ.get(name))]


async def _always_ok() -> bool:
    return True


@asynccontextmanager
async def _purging(threads: ThreadStore, settings: DatabaseSettings) -> AsyncGenerator[None]:
    task = asyncio.create_task(purge_periodically(threads, settings))
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def _recover_turns(threads: ThreadStore) -> None:
    """Turns a stopped server left queued or running become resumable (``worker_lost``)."""
    recovered = await threads.turns.interrupt_all_open(FailureReason.WORKER_LOST)
    if recovered:
        logger.info("Interrupted %d turn(s) left running by a stopped server", len(recovered))


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
        await _recover_turns(app.state.threads)
        yield
        return
    settings = get_database_settings()
    async with (
        open_database(os.environ, settings) as database,
        _purging(database.threads, settings),
    ):
        app.state.threads = database.threads
        app.state.health_check = database.health_check
        _install_auth(app, database.threads, database.accounts)
        await _recover_turns(database.threads)
        yield


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None]:
    install_redaction()
    with protect_secrets(_environment_keys()):  # keys from .env, which the vaults do not cover
        async with _thread_state(app):
            yield
    await asyncio.to_thread(flush_telemetry, get_telemetry_settings())  # queued spans go out


def _mount_frontend(app: FastAPI, dist: Path) -> None:
    if (dist / "index.html").is_file():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")


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


def create_app(
    settings: UiSettings | None = None,
    *,
    keys_from_environment: bool = False,
    threads: ThreadStore | None = None,
    health_check: Callable[[], Awaitable[bool]] | None = None,
    accounts: Accounts | None = None,
    mailer: Mailer | None = None,
    session_secret: bytes | None = None,
) -> FastAPI:
    """Build the API for ``settings`` (the shipped ``[ui]`` settings by default).

    Args:
        settings: The UI settings.
        keys_from_environment: Read every key from its environment variable instead of the OS
            keychain (containers, which have none); keys then cannot be saved in Settings.
        threads: A thread store to use instead of opening the database (tests); None opens
            PostgreSQL at start-up and refuses to start without a migrated database.
        health_check: Replaces the database check of ``GET /api/health`` (tests).
        accounts: The account stores to use with an injected ``threads`` (tests); with none
            injected the database provides them.
        mailer: Sends the account emails; None sends them over the configured SMTP server.
        session_secret: The secret that keys the stored session and token hashes (tests); None
            reads the variable named in ``[auth]``, and the app refuses to start without it.
    """
    if threads is not None and accounts is None:
        raise ValueError("inject the account stores together with the thread store")
    ui = settings if settings is not None else ui_settings()
    app = FastAPI(title="EcoFate API", lifespan=_lifespan, docs_url=None, redoc_url=None)
    _add_middleware(app, ui)
    app.state.threads = threads
    app.state.accounts = accounts
    app.state.mailer = mailer
    app.state.session_secret = session_secret
    app.state.health_check = health_check or _always_ok
    app.state.keys_from_environment = keys_from_environment
    install_exception_handlers(app)
    _include_routers(app)
    if threads is not None and accounts is not None:
        _install_auth(app, threads, accounts)
    _mount_frontend(app, ui.frontend_dist)
    return app
