"""Run the production agent on one scenario and capture what it did as a ``RunRecord``."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import cast

import openai
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.errors import GraphRecursionError

from agent.graph import build_agent
from app.run import completion_guard, run_config
from config.agent import AgentSettings
from evals.cassette import UNRECORDED_KEY
from evals.record import RunRecord, ToolCall

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


def run_scenario(
    model: BaseChatModel,
    tools: Sequence[BaseTool],
    scenario: tuple[str, str],
    settings: AgentSettings,
) -> RunRecord:
    """Run the agent on ``scenario`` (id, query) with the program's step limit.

    The model is built by the caller with ``app.chat_model`` from the same ``[agent]``
    settings the program uses. Expected failures go into the record.
    """
    scenario_id, query = scenario
    agent = build_agent(model, tools, completion_guard=completion_guard())
    messages: list[AnyMessage] = []
    error: str | None = None
    try:
        for state in agent.stream(
            {"messages": [HumanMessage(content=query)]},
            config=run_config(settings),
            stream_mode="values",
        ):
            messages = list(state["messages"])
    except EXPECTED_ERRORS as exc:
        error = f"{type(exc).__name__}: {exc}"
    return RunRecord(scenario_id, query, extract_calls(messages), final_report(messages), error)
