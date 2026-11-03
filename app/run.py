"""Run the agent on one question with the configured model and step limit."""

from __future__ import annotations

from collections.abc import Generator, Mapping, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from typing import cast
from uuid import uuid4

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph

from agent.completion import CompletionGuard
from agent.graph import build_agent
from agent.state import AgentState
from app.chat_model import build_chat_model
from app.key_vault import KeyringVault, ServiceKeys, default_service_keys, stored_key
from app.telemetry import flush_telemetry, run_tracer, session_span
from app.usage_meter import CallUsage, UsageRecorder
from config.agent import AgentSettings, get_agent_settings
from config.telemetry import get_telemetry_settings
from config.ui import KEY_NAMES, get_ui_settings
from prompts.registry import load_prompt
from tools.credentials import HOLDERS

Agent = CompiledStateGraph[AgentState, None, AgentState, AgentState]


def completion_guard() -> CompletionGuard | None:
    """The completion check the web program also uses, from ``[ui.prompts]``; None when off."""
    names = get_ui_settings().prompts
    if names.max_nudges == 0:
        return None
    return CompletionGuard(
        classifier_prompt=load_prompt(names.completion),
        nudge=load_prompt(names.nudge),
        max_nudges=names.max_nudges,
    )


def run_config(
    settings: AgentSettings,
    callbacks: Sequence[BaseCallbackHandler] = (),
) -> RunnableConfig:
    """LangGraph run configuration from the ``[agent]`` settings (the step limit) and the
    callbacks that observe the run, if any."""
    config: RunnableConfig = {"recursion_limit": settings.recursion_limit}
    if callbacks:
        config["callbacks"] = list(callbacks)
    return config


def program_model(
    settings: AgentSettings,
    vault: KeyringVault | None = None,
    environ: Mapping[str, str] | None = None,
) -> BaseChatModel:
    """Build the program's chat model with the key stored in the OS keychain.

    Falls back to the ``[agent]`` API-key environment variable when the keychain holds no key
    or is unavailable (headless runs such as CI).

    Raises:
        RuntimeError: If neither the keychain nor the environment variable has a key.
    """
    chosen = vault if vault is not None else default_service_keys().vault("openai")
    return build_chat_model(settings, environ, api_key=stored_key(chosen))


@contextmanager
def stored_keys_provided(keys: ServiceKeys) -> Generator[None]:
    """Give the tools the keys stored in the keychain while a run lasts (the CLI's counterpart
    of the web program's per-turn keys); a key that is not stored falls back to its variable."""
    with ExitStack() as stack:
        for name in KEY_NAMES:
            key = stored_key(keys.vault(name))
            if key is not None:
                stack.enter_context(HOLDERS[name].provide(key))
        yield


@dataclass(frozen=True)
class RunResult:
    """What one command-line run produced.

    Attributes:
        answer: The agent's final answer.
        calls: Every chat model call of the run (the agent's and the checks'), for the cost.
    """

    answer: str
    calls: tuple[CallUsage, ...]


def _answer_text(result: Mapping[str, object]) -> str:
    last = cast(list[BaseMessage], result["messages"])[-1]
    return last.text if isinstance(last, AIMessage) else str(last.content)


def _invoke(agent: Agent, question: str, config: RunnableConfig, keys: ServiceKeys) -> str:
    with stored_keys_provided(keys):
        result = agent.invoke({"messages": [HumanMessage(content=question)]}, config)
    return _answer_text(result)


def ask(
    question: str,
    model: BaseChatModel | None = None,
    keys: ServiceKeys | None = None,
) -> RunResult:
    """Run the agent on ``question`` and return its answer with the model calls it made.

    The run is recorded as one session span (see ``app.telemetry``) that ends with the run's
    token usage and estimated cost.

    Args:
        question: The user's request.
        model: Chat model to use; defaults to the one configured in ``[agent]``.
        keys: Key vaults to read; defaults to the OS keychain ones named in ``[ui.keyring]``.
    """
    settings = get_agent_settings()
    vaults = keys if keys is not None else default_service_keys()
    agent = build_agent(
        model if model is not None else program_model(settings, vaults.vault("openai")),
        completion_guard=completion_guard(),
    )
    return _traced_run(agent, question, settings, vaults)


def _traced_run(
    agent: Agent,
    question: str,
    settings: AgentSettings,
    keys: ServiceKeys,
) -> RunResult:
    """Run the agent inside the session span, metering every model call."""
    monitoring = get_telemetry_settings()
    recorder = UsageRecorder(settings.model)
    tracer = run_tracer(monitoring)
    config = run_config(settings, [recorder, *([tracer] if tracer else [])])
    name = monitoring.spans.cli_session
    try:
        with session_span(monitoring, name, uuid4().hex, question, settings.model) as span:
            try:
                answer = _invoke(agent, question, config, keys)
            finally:
                span.record_usage(recorder.calls, get_ui_settings().pricing)
    finally:
        flush_telemetry(monitoring)
    return RunResult(answer, tuple(recorder.calls))
