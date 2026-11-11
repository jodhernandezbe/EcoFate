"""The settings of a web chat turn, built once from configuration for every process that runs
or inspects one (the API and the background worker), so both build exactly the same agent."""

from __future__ import annotations

from agent.completion import CompletionGuard
from agent.graph import DEFAULT_SYSTEM_PROMPT
from agent.guardrails import ScopeGuard
from app.turns.runner import TurnSettings
from config.agent import AgentSettings, get_agent_settings
from config.telemetry import get_telemetry_settings
from config.ui import UiSettings, get_ui_settings
from prompts.registry import load_prompt


def scope_guard(ui: UiSettings) -> ScopeGuard:
    """The on-topic check of each user message, from the prompts ``[ui]`` names."""
    names = ui.prompts
    return ScopeGuard(
        classifier_prompt=load_prompt(names.classifier),
        fallback_reply=load_prompt(names.fallback),
        history_window=names.history_window,
    )


def completion_guard(ui: UiSettings) -> CompletionGuard | None:
    """The check that sends an announcing reply back to work; None when nudges are off."""
    names = ui.prompts
    if names.max_nudges == 0:
        return None
    return CompletionGuard(
        classifier_prompt=load_prompt(names.completion),
        nudge=load_prompt(names.nudge),
        max_nudges=names.max_nudges,
    )


def web_system_prompt(ui: UiSettings) -> str:
    """The agent's standard prompt followed by the web program's addendum."""
    return f"{load_prompt(DEFAULT_SYSTEM_PROMPT)}\n\n{load_prompt(ui.prompts.addendum)}"


def web_turn_settings(
    agent: AgentSettings | None = None,
    ui: UiSettings | None = None,
) -> TurnSettings:
    """The runner's settings of a web turn: step limit, model and prices, both guards, the web
    prompt and monitoring (the shipped ``[agent]`` and ``[ui]`` settings by default)."""
    agent_settings = agent if agent is not None else get_agent_settings()
    ui_settings = ui if ui is not None else get_ui_settings()
    return TurnSettings(
        recursion_limit=agent_settings.recursion_limit,
        model_name=agent_settings.model,
        pricing=ui_settings.pricing,
        scope_guard=scope_guard(ui_settings),
        completion_guard=completion_guard(ui_settings),
        system_prompt=web_system_prompt(ui_settings),
        telemetry=get_telemetry_settings(),
    )
