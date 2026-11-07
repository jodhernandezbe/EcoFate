"""FastAPI app factory: own-origin CORS, Origin/Host guard, sanitised errors, static frontend."""

from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.core.config import ui_settings
from api.core.exceptions import install_exception_handlers
from api.core.logging_filter import install_redaction, protect_secrets
from api.core.origin_guard import OriginGuard
from api.dependencies import key_variables
from api.routers import v1_chat, v1_facilities, v1_health, v1_monitoring, v1_settings
from api.services.database import open_database
from api.services.threads import ThreadStore
from app.telemetry import flush_telemetry
from config.database import DatabaseSettings, get_database_settings
from config.telemetry import get_telemetry_settings
from config.ui import UiSettings
from storage.purge import purge_periodically


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


@asynccontextmanager
async def _thread_state(app: FastAPI) -> AsyncGenerator[None]:
    """Open the database and its thread store, unless a store was injected (tests)."""
    if app.state.threads is not None:
        yield
        return
    settings = get_database_settings()
    async with (
        open_database(os.environ, settings) as database,
        _purging(database.threads, settings),
    ):
        app.state.threads = database.threads
        app.state.health_check = database.health_check
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


def create_app(
    settings: UiSettings | None = None,
    *,
    keys_from_environment: bool = False,
    threads: ThreadStore | None = None,
    health_check: Callable[[], Awaitable[bool]] | None = None,
) -> FastAPI:
    """Build the API for ``settings`` (the shipped ``[ui]`` settings by default).

    Args:
        settings: The UI settings.
        keys_from_environment: Read every key from its environment variable instead of the OS
            keychain (containers, which have none); keys then cannot be saved in Settings.
        threads: A thread store to use instead of opening the database (tests); None opens
            PostgreSQL at start-up and refuses to start without a migrated database.
        health_check: Replaces the database check of ``GET /api/health`` (tests).
    """
    ui = settings if settings is not None else ui_settings()
    app = FastAPI(title="EcoFate API", lifespan=_lifespan, docs_url=None, redoc_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[ui.origin],
        allow_methods=["GET", "POST", "DELETE"],
    )
    app.add_middleware(OriginGuard, origin=ui.origin)  # outermost: runs before CORS and routes
    app.state.threads = threads
    app.state.health_check = health_check or _always_ok
    app.state.keys_from_environment = keys_from_environment
    install_exception_handlers(app)
    for module in (v1_health, v1_settings, v1_chat, v1_facilities, v1_monitoring):
        app.include_router(module.router)
    _mount_frontend(app, ui.frontend_dist)
    return app
