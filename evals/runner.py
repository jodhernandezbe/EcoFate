"""Run the production agent on one scenario and capture what it did as a ``RunRecord``."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from typing import Any, cast
from uuid import UUID, uuid4

import openai
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.errors import GraphRecursionError

from agent.graph import build_agent
from agent.state import AgentState
from app.run import Agent, completion_guard, run_config
from app.turns.follow_up import follow_up_messages
from config.agent import AgentSettings
from evals.cassette import UNRECORDED_KEY, Cassette
from evals.jobs import MemoryJobPort, ended_job
from evals.record import RunRecord, ToolCall
from tools.jobs.port import provided_port, scope_config
from tools.schemas import ConfirmationRequest

# Failures that end a run early but still produce a record (the scenario then fails).
EXPECTED_ERRORS = (GraphRecursionError, openai.APIError)


def _text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        blocks = cast(list[object], content)
        return "".join(_block_text(block) for block in blocks)
    return str(content)


def _block_text(block: object) -> str:
    if isinstance(block, dict):
        return str(cast(dict[str, object], block).get("text", ""))
    return str(block)


def _parse(content: object) -> object:
    text = _text(content)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _is_unrecorded(output: object) -> bool:
    return isinstance(output, dict) and output.get(UNRECORDED_KEY) is True  # type: ignore[union-attr]


def extract_calls(messages: Sequence[AnyMessage]) -> tuple[ToolCall, ...]:
    """Pair each tool call of the model with its tool output, in call order."""
    outputs = {m.tool_call_id: _parse(m.content) for m in messages if isinstance(m, ToolMessage)}
    calls: list[ToolCall] = []
    for message in messages:
        if isinstance(message, AIMessage):
            for tc in message.tool_calls:
                output = outputs.get(tc["id"] or "")
                calls.append(ToolCall(tc["name"], dict(tc["args"]), output, _is_unrecorded(output)))
    return tuple(calls)


def final_report(messages: Sequence[AnyMessage]) -> str:
    """Text of the last model message that requested no tool call ('' if none)."""
    for message in reversed(messages):
        if isinstance(message, AIMessage) and not message.tool_calls:
            return _text(message.content)
    return ""


def _run_turn(
    agent: Agent,
    inputs: dict[str, Any],
    config: RunnableConfig,
) -> tuple[dict[str, Any], str | None]:
    """Stream one turn; returns its last state (its input if no step finished) and any error."""
    last: dict[str, Any] = dict(inputs)
    try:
        for state in agent.stream(cast(AgentState, inputs), config=config, stream_mode="values"):
            last = dict(state)
    except EXPECTED_ERRORS as exc:
        return last, f"{type(exc).__name__}: {exc}"
    return last, None


def _declined_note(entry_ids: Sequence[str]) -> str:
    """What the program tells the model when the user answers an open request with a new
    message instead (``api/services/confirmation.py``): every entry counts as proceed without."""
    return (
        "The user did not answer the open request. The user chose to proceed without these "
        f"values; report them as absent and do not ask again: {', '.join(entry_ids)}."
    )


def _follow_up_turn(
    state: dict[str, Any],
    follow_up: str,
    settings: AgentSettings,
) -> tuple[dict[str, Any], RunnableConfig]:
    """The input and configuration of the follow-up turn, as the program would send them: the
    conversation so far plus the message, and every open entry declined for the tools."""
    request = cast(ConfirmationRequest, state["pending"])
    declined = sorted(entry["entry_id"] for entry in request["entries"])
    config = run_config(settings)
    config["configurable"] = {"user_values": {"supplied": {}, "declined": declined}}
    messages = [*state["messages"], HumanMessage(content=follow_up)]
    return {"messages": messages, "answers_note": _declined_note(declined)}, config


async def _arun_turn(
    agent: Agent,
    inputs: dict[str, Any],
    config: RunnableConfig,
) -> tuple[dict[str, Any], str | None]:
    """The async twin of ``_run_turn`` (job tools start their jobs from async code)."""
    last: dict[str, Any] = dict(inputs)
    try:
        stream = agent.astream(cast(AgentState, inputs), config=config, stream_mode="values")
        async for state in stream:
            last = dict(state)
    except EXPECTED_ERRORS as exc:
        return last, f"{type(exc).__name__}: {exc}"
    return last, None


def _scoped(settings: AgentSettings, owner: UUID, automatic: bool) -> RunnableConfig:
    """The run configuration of a turn of the evaluation thread, as the program scopes it."""
    config = run_config(settings)
    config["configurable"] = scope_config(owner, "eval-thread", automatic)
    return config


async def _explain_jobs(
    agent: Agent,
    messages: list[AnyMessage],
    port: MemoryJobPort,
    cassette: Cassette,
    config: RunnableConfig,
) -> tuple[list[AnyMessage], str | None]:
    """One automatic follow-up turn per queued job, each given the job's recorded end."""
    error: str | None = None
    for submitted in port.jobs:
        inputs: dict[str, Any] = {
            "messages": [*messages, *follow_up_messages(ended_job(submitted, cassette))],
        }
        state, error = await _arun_turn(agent, inputs, config)
        messages = list(state.get("messages", inputs["messages"]))
        if error is not None:
            break
    return messages, error


async def _background_run(
    agent: Agent,
    query: str,
    settings: AgentSettings,
    cassette: Cassette,
) -> tuple[list[AnyMessage], str, str | None]:
    """Both turns of a background scenario: the first queues the job, the next ones explain it.
    Returns the messages, the first turn's final reply (when a job was queued) and any error."""
    port, owner = MemoryJobPort(), uuid4()
    with provided_port(port):
        first = {"messages": [HumanMessage(content=query)]}
        state, error = await _arun_turn(agent, first, _scoped(settings, owner, False))
        messages: list[AnyMessage] = list(state.get("messages", []))
        if error is not None or not port.jobs:
            return messages, "", error
        interim = final_report(messages)
        follow = _scoped(settings, owner, True)
        messages, error = await _explain_jobs(agent, messages, port, cassette, follow)
    return messages, interim, error


def run_scenario(
    model: BaseChatModel,
    tools: Sequence[BaseTool],
    scenario: tuple[str, str],
    settings: AgentSettings,
    *,
    follow_up: str | None = None,
    background: bool = False,
    cassette: Cassette | None = None,
) -> RunRecord:
    """Run the agent on ``scenario`` (id, query) with the program's step limit.

    When the first turn ends with a request for missing values and ``follow_up`` is given, it is
    sent as the user's next message (the open entries then count as proceed without) and the
    record covers both turns. The model is built by the caller with ``app.chat_model`` from the
    same ``[agent]`` settings the program uses. Expected failures go into the record.

    With ``background`` the first turn runs async with a memory job system provided, so a heavy
    tool queues a job; each queued job is then ended from ``cassette`` (an empty one when None,
    which fails the job) and explained by an automatic follow-up turn. The record covers every
    turn and keeps the first turn's final reply as ``interim``.
    """
    scenario_id, query = scenario
    agent = build_agent(model, tools, completion_guard=completion_guard())
    if background:
        ran = asyncio.run(_background_run(agent, query, settings, cassette or Cassette()))
        messages, interim, error = ran
        calls = extract_calls(messages)
        return RunRecord(scenario_id, query, calls, final_report(messages), error, interim)
    first = {"messages": [HumanMessage(content=query)]}
    state, error = _run_turn(agent, first, run_config(settings))
    if follow_up is not None and error is None and state.get("pending"):
        state, error = _run_turn(agent, *_follow_up_turn(state, follow_up, settings))
    messages: list[AnyMessage] = list(state.get("messages", []))
    return RunRecord(scenario_id, query, extract_calls(messages), final_report(messages), error)
