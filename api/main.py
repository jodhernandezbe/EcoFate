"""FastAPI app factory: own-origin CORS, Origin/Host guard, sanitised errors, static frontend."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.core.config import ui_settings
from api.core.exceptions import install_exception_handlers
from api.core.logging_filter import install_redaction, protect_secrets
from api.core.origin_guard import OriginGuard
from api.routers import v1_chat, v1_facilities, v1_monitoring, v1_settings
from api.services.threads import ThreadStore
from app.telemetry import flush_telemetry
from config.agent import get_agent_settings
from config.loader import get_comptox_settings
from config.population import get_population_settings
from config.telemetry import get_telemetry_settings
from config.ui import UiSettings


def _environment_keys() -> list[str]:
    """The values of the API-key environment variables that are set (never logged)."""
    monitoring = get_telemetry_settings()
    names = (
        get_agent_settings().api_key_env_var,
        get_population_settings().api_key_env_var,
        get_comptox_settings().api_key_env_var,
        monitoring.write_token_env_var,
        monitoring.read_token_env_var,
    )
    return [value.strip() for name in names if (value := os.environ.get(name))]


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None]:
    install_redaction()
    with protect_secrets(_environment_keys()):  # keys from .env, which the vaults do not cover
        yield
    await asyncio.to_thread(flush_telemetry, get_telemetry_settings())  # queued spans go out


def _mount_frontend(app: FastAPI, dist: Path) -> None:
    if (dist / "index.html").is_file():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")


def create_app(settings: UiSettings | None = None) -> FastAPI:
    """Build the API for ``settings`` (the shipped ``[ui]`` settings by default)."""
    ui = settings if settings is not None else ui_settings()
    app = FastAPI(title="EcoFate API", lifespan=_lifespan, docs_url=None, redoc_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[ui.origin],
        allow_methods=["GET", "POST", "DELETE"],
    )
    app.add_middleware(OriginGuard, origin=ui.origin)  # outermost: runs before CORS and routes
    app.state.threads = ThreadStore(max_threads=ui.max_threads)
    install_exception_handlers(app)
    app.include_router(v1_settings.router)
    app.include_router(v1_chat.router)
    app.include_router(v1_facilities.router)
    app.include_router(v1_monitoring.router)
    _mount_frontend(app, ui.frontend_dist)
    return app
