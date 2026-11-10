"""FastAPI ``Depends()`` providers; tests override them with fakes."""

from __future__ import annotations

import os
from typing import cast

from fastapi import Request

from agent.completion import CompletionGuard
from agent.graph import DEFAULT_SYSTEM_PROMPT
from agent.guardrails import ScopeGuard
from api.core.config import ui_settings
from api.core.security_keyring import default_service_keys
from api.core.session_guard import auth_runtime
from api.services.agent_runner import AgentRuntime
from api.services.auth.throttle import client_address
from api.services.monitoring.service import MonitoringService
from api.services.projectors.rules import WorkspaceRules
from api.services.threads import ThreadStore
from app.chat_model import build_chat_model
from app.key_vault import ServiceKeys, environment_service_keys
from config.agent import get_agent_settings
from config.loader import get_comptox_settings
from config.population import get_population_settings
from config.telemetry import get_telemetry_settings
from config.ui import KeyName, UiSettings
from prompts.registry import load_prompt


def get_settings() -> UiSettings:
    """The UI settings."""
    return ui_settings()


def key_variables() -> dict[KeyName, str]:
    """Key name -> the environment variable that holds it when no keychain is used."""
    return {
        "openai": get_agent_settings().api_key_env_var,
        "census": get_population_settings().api_key_env_var,
        "comptox": get_comptox_settings().api_key_env_var,
    }


def get_service_keys(request: Request) -> ServiceKeys:
    """The vaults of every key; keys are read from them once per turn, never cached.

    The OS keychain natively; the environment (``.env``) when the app was built for a
    container (``python -m api --container``), where no keychain exists.
    """
    if getattr(request.app.state, "keys_from_environment", False):
        return environment_service_keys(key_variables())
    return default_service_keys()


def _scope_guard(ui: UiSettings) -> ScopeGuard:
    names = ui.prompts
    return ScopeGuard(
        classifier_prompt=load_prompt(names.classifier),
        fallback_reply=load_prompt(names.fallback),
        history_window=names.history_window,
    )


def _completion_guard(ui: UiSettings) -> CompletionGuard | None:
    names = ui.prompts
    if names.max_nudges == 0:
        return None
    return CompletionGuard(
        classifier_prompt=load_prompt(names.completion),
        nudge=load_prompt(names.nudge),
        max_nudges=names.max_nudges,
    )


def _workspace_rules(ui: UiSettings) -> WorkspaceRules:
    return WorkspaceRules(
        thresholds=ui.thresholds,
        coordinate_tolerance_deg=ui.map.coordinate_tolerance_deg,
        default_radius_km=get_population_settings().default_radius_km,
        sector_half_angle_deg=ui.map.sector_half_angle_deg,
        vertex_spacing_deg=ui.map.vertex_spacing_deg,
        graph=ui.exposure_graph,
    )


def get_runtime() -> AgentRuntime:
    """The configured chat model factory, step limit, labels, prices, guard, prompt and rules."""
    settings = get_agent_settings()
    ui = ui_settings()
    return AgentRuntime(
        build_model=lambda key: build_chat_model(settings, api_key=key),
        recursion_limit=settings.recursion_limit,
        step_labels=ui.step_labels,
        model_name=settings.model,
        pricing=ui.pricing,
        scope_guard=_scope_guard(ui),
        completion_guard=_completion_guard(ui),
        system_prompt=f"{load_prompt(DEFAULT_SYSTEM_PROMPT)}\n\n{load_prompt(ui.prompts.addendum)}",
        workspace_rules=_workspace_rules(ui),
        telemetry=get_telemetry_settings(),
        max_resumes_per_turn=settings.max_resumes_per_turn,
    )


def get_max_resumes() -> int:
    """How many times one interrupted turn may be resumed (``[agent].max_resumes_per_turn``)."""
    return get_agent_settings().max_resumes_per_turn


def get_threads(request: Request) -> ThreadStore:
    """The thread store of this app (PostgreSQL in production, a fake in tests)."""
    return cast(ThreadStore, request.app.state.threads)


def get_monitoring(request: Request) -> MonitoringService:
    """The monitoring service; it finds the Logfire read token in the server's environment and
    resolves the accounts of the sessions through the application database."""
    emails = auth_runtime(request).accounts.users.emails
    settings = get_telemetry_settings()
    return MonitoringService(settings, ui_settings().step_labels, os.environ, emails=emails)


def get_client_address(request: Request) -> str:
    """The address the request came from: the socket peer, or the ``X-Forwarded-For`` entry the
    configured number of trusted proxies vouch for (none by default)."""
    hops = auth_runtime(request).settings.trusted_proxy_hops
    peer = request.client.host if request.client else None
    return client_address(peer, request.headers.get("x-forwarded-for"), hops)
