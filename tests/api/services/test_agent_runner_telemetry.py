"""Tests that each chat turn is recorded as one trace, tagged with the thread."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolCall
from langchain_core.tools import tool
from logfire.testing import TestExporter
from opentelemetry.sdk.trace import ReadableSpan

from api.schemas.chat import ChatRequest, StreamEvent
from api.services.agent_runner import AgentRuntime, run_turn
from api.services.threads import ThreadStore
from app.key_vault import default_service_keys
from app.telemetry import flush_telemetry
from config.telemetry import TelemetrySettings
from tests.app.test_usage_meter import PRICING
from tests.fakes import OPENAI_ENTRY, FakeCredentialStore, ScriptedChatModel, reply

pytestmark = pytest.mark.anyio
KEY = "sk-proj-" + "k1L2m3N4o5" * 3  # pragma: allowlist secret


@tool
def lookup(cas: str) -> str:
    """Look up a CAS number."""
    return f"name of {cas}"


def _runtime(model: BaseChatModel, monitoring: TelemetrySettings) -> AgentRuntime:
    return AgentRuntime(
        lambda key: model,
        10,
        model_name="m",
        pricing=PRICING,
        telemetry=monitoring,
    )


def _turn(
    message: str,
    threads: ThreadStore,
    runtime: AgentRuntime,
    thread_id: str = "t1",
) -> AsyncGenerator[StreamEvent]:
    store = FakeCredentialStore()
    store.entries[OPENAI_ENTRY] = KEY
    return run_turn(
        ChatRequest(thread_id=thread_id, message=message),
        keys=default_service_keys(store),
        threads=threads,
        runtime=runtime,
    )


async def _run(
    message: str,
    threads: ThreadStore,
    runtime: AgentRuntime,
    thread_id: str = "t1",
) -> list[StreamEvent]:
    events = _turn(message, threads, runtime, thread_id)
    return [event async for event in events]


def _turn_spans(exporter: TestExporter, monitoring: TelemetrySettings) -> list[ReadableSpan]:
    return [
        s
        for s in exporter.exported_spans
        if s.name == monitoring.spans.web_turn
        and (s.attributes or {}).get("logfire.span_type") != "pending_span"
    ]


async def test_a_turn_is_one_span_tagged_with_the_thread_and_its_totals(
    monitoring: TelemetrySettings,
    exporter: TestExporter,
) -> None:
    model = ScriptedChatModel([reply("hello", 100, 20), reply("again", 50, 10)])
    threads, runtime = ThreadStore(), _runtime(model, monitoring)
    await _run("Assess benzene", threads, runtime)
    await _run("And toluene?", threads, runtime)
    first, second = _turn_spans(exporter, monitoring)
    names, one, two = monitoring.attributes, first.attributes or {}, second.attributes or {}
    assert (one[names.session_id], two[names.session_id]) == ("t1", "t1")
    assert (one[names.question], one[names.model], one[names.outcome]) == (
        "Assess benzene",
        "m",
        "ok",
    )
    assert one[f"{names.usage_prefix}input_tokens"] == 100
    assert one[f"{names.session_usage_prefix}input_tokens"] == 100
    assert two[f"{names.usage_prefix}input_tokens"] == 50
    assert two[f"{names.session_usage_prefix}input_tokens"] == 150  # the thread so far


async def test_a_missing_key_ends_the_turn_span_as_an_error(
    monitoring: TelemetrySettings,
    exporter: TestExporter,
) -> None:
    runtime = _runtime(ScriptedChatModel([reply("never", 1, 1)]), monitoring)
    events = run_turn(
        ChatRequest(thread_id="t9", message="hi"),
        keys=default_service_keys(FakeCredentialStore()),  # no OpenAI key stored
        threads=ThreadStore(),
        runtime=runtime,
    )
    assert [e.type for e in [e async for e in events]][-1] == "turn_finished"
    (span,) = _turn_spans(exporter, monitoring)
    assert (span.attributes or {})[monitoring.attributes.outcome] == "error"


async def test_a_model_failure_ends_the_turn_span_as_an_error(
    monitoring: TelemetrySettings,
    exporter: TestExporter,
) -> None:
    runtime = _runtime(ScriptedChatModel([]), monitoring)  # out of script: the model raises
    await _run("hi", ThreadStore(), runtime)
    (span,) = _turn_spans(exporter, monitoring)
    assert (span.attributes or {})[monitoring.attributes.outcome] == "error"


async def test_tool_calls_nest_in_the_turn_trace(
    monkeypatch: pytest.MonkeyPatch,
    monitoring: TelemetrySettings,
    exporter: TestExporter,
) -> None:
    monkeypatch.setattr("agent.graph.get_all_tools", lambda: [lookup])
    call = AIMessage(
        content="",
        tool_calls=[ToolCall(name="lookup", args={"cas": "71-43-2"}, id="c")],
    )
    model = ScriptedChatModel([call, reply("done", 20, 2)])
    await _run("Assess 71-43-2", ThreadStore(), _runtime(model, monitoring))
    flush_telemetry(monitoring)
    (turn,) = _turn_spans(exporter, monitoring)
    tools = [s for s in exporter.exported_spans if (s.attributes or {}).get("gen_ai.tool.name")]
    assert [str((s.attributes or {})["gen_ai.tool.name"]) for s in tools] == ["lookup"]
    assert {s.context.trace_id for s in tools if s.context} == {
        turn.context.trace_id if turn.context else None,
    }


async def test_closing_the_stream_early_still_ends_the_span_cleanly(
    monitoring: TelemetrySettings,
    exporter: TestExporter,
    caplog: pytest.LogCaptureFixture,
) -> None:
    runtime = _runtime(ScriptedChatModel([reply("hello there", 10, 2)]), monitoring)
    events = _turn("hi", ThreadStore(), runtime)
    with caplog.at_level(logging.WARNING):
        await events.__anext__()
        await events.aclose()
    (span,) = _turn_spans(exporter, monitoring)
    assert (span.attributes or {})[monitoring.attributes.outcome] == "error"
    assert not [r for r in caplog.records if r.name.startswith("opentelemetry")]
