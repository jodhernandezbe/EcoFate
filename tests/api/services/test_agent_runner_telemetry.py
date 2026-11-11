"""Tests that each chat turn is recorded as one trace, tagged with the thread."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from typing import cast

import logfire
import pytest
from celery.signals import before_task_publish
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolCall
from langchain_core.tools import tool
from logfire.testing import TestExporter
from opentelemetry.instrumentation.celery import CeleryInstrumentor
from opentelemetry.sdk.trace import ReadableSpan

from api.schemas.chat import ChatRequest, StreamEvent
from api.services.agent_runner import AgentRuntime
from api.services.key_setup import turn_key_loader
from api.services.threads import ThreadStore
from app.task_queue import TASK_NAME, build_celery
from app.telemetry import flush_telemetry, instrument_task_queue
from commons.key_patterns import KEY_PATTERNS
from config.telemetry import TelemetrySettings
from config.worker import get_worker_settings
from storage.turn_model import TurnStatus
from tests.api.keys import OTHER_OWNER, OWNER, owned
from tests.api.streams import begun_turn
from tests.app.test_usage_meter import PRICING
from tests.fakes import (
    InMemoryThreadStore,
    KeyBench,
    ScriptedChatModel,
    reply,
)

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
    bench = KeyBench()
    bench.give(KEY)
    return begun_turn(
        ChatRequest(thread_id=thread_id, message=message),
        keys=turn_key_loader(bench.services, OWNER),
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
    threads, runtime = InMemoryThreadStore(), _runtime(model, monitoring)
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
    events = begun_turn(
        ChatRequest(thread_id="t9", message="hi"),
        keys=turn_key_loader(KeyBench().services, OWNER),  # no OpenAI key stored
        threads=InMemoryThreadStore(),
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
    await _run("hi", InMemoryThreadStore(), runtime)
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
    await _run("Assess 71-43-2", InMemoryThreadStore(), _runtime(model, monitoring))
    flush_telemetry(monitoring)
    (turn,) = _turn_spans(exporter, monitoring)
    tools = [s for s in exporter.exported_spans if (s.attributes or {}).get("gen_ai.tool.name")]
    assert [str((s.attributes or {})["gen_ai.tool.name"]) for s in tools] == ["lookup"]
    assert {s.context.trace_id for s in tools if s.context} == {
        turn.context.trace_id if turn.context else None,
    }


async def test_a_reader_that_leaves_early_does_not_stop_the_turn(
    monitoring: TelemetrySettings,
    exporter: TestExporter,
    caplog: pytest.LogCaptureFixture,
) -> None:
    threads = InMemoryThreadStore()
    runtime = _runtime(ScriptedChatModel([reply("hello there", 10, 2)]), monitoring)
    events = _turn("hi", threads, runtime)
    with caplog.at_level(logging.WARNING):
        await events.__anext__()
        await events.aclose()  # the browser left; the worker keeps running the turn
        for _ in range(200):
            latest = await threads.turns.latest(owned("t1"))
            if latest is not None and latest.status is TurnStatus.COMPLETED:
                break
            await asyncio.sleep(0.01)
    (span,) = _turn_spans(exporter, monitoring)
    assert (span.attributes or {})[monitoring.attributes.outcome] == "ok"
    assert not [r for r in caplog.records if r.name.startswith("opentelemetry")]


async def test_a_web_turn_span_carries_the_users_opaque_id_and_no_email(
    monitoring: TelemetrySettings,
    exporter: TestExporter,
) -> None:
    runtime = _runtime(ScriptedChatModel([reply("hello", 10, 2)]), monitoring)
    await _run("Assess ana@example.com's plant", InMemoryThreadStore(), runtime)
    (span,) = _turn_spans(exporter, monitoring)
    attributes = span.attributes or {}
    assert attributes[monitoring.attributes.user_id] == str(OWNER)
    assert attributes[monitoring.attributes.session_id] == "t1"  # still the plain thread id
    assert "@" not in str(attributes[monitoring.attributes.user_id])


async def test_the_checkpoint_of_a_turn_is_scoped_to_its_owner(
    monitoring: TelemetrySettings,
) -> None:
    threads = InMemoryThreadStore()
    runtime = _runtime(ScriptedChatModel([reply("one", 1, 1), reply("two", 1, 1)]), monitoring)
    await _run("first user", threads, runtime)
    mine = await threads.messages(owned("t1"))
    theirs = await threads.messages(owned("t1", OTHER_OWNER))
    assert [m.content for m in mine][0] == "first user" and theirs == []


# --- across the queue -----------------------------------------------------------------------


def _named(exporter: TestExporter, name: str) -> list[ReadableSpan]:
    return [
        s
        for s in exporter.exported_spans
        if s.name == name and (s.attributes or {}).get("logfire.span_type") != "pending_span"
    ]


async def test_the_worker_turn_span_is_a_child_of_the_enqueue_span(
    monitoring: TelemetrySettings,
    exporter: TestExporter,
) -> None:
    runtime = _runtime(ScriptedChatModel([reply("hello", 10, 2)]), monitoring)
    await _run("Assess 71-43-2", InMemoryThreadStore(), runtime)
    (enqueue,) = _named(exporter, monitoring.spans.web_enqueue)
    (turn,) = _turn_spans(exporter, monitoring)
    assert enqueue.context is not None and turn.context is not None
    assert turn.context.trace_id == enqueue.context.trace_id
    assert turn.parent is not None and turn.parent.span_id == enqueue.context.span_id
    names, attributes = monitoring.attributes, turn.attributes or {}
    assert attributes[names.session_id] == "t1" == (enqueue.attributes or {})[names.session_id]
    wait = attributes[names.queue_wait_seconds]
    assert isinstance(wait, float) and wait >= 0


async def test_no_span_of_a_queued_turn_carries_a_key(
    monitoring: TelemetrySettings,
    exporter: TestExporter,
) -> None:
    runtime = _runtime(ScriptedChatModel([reply("hello", 10, 2)]), monitoring)
    await _run("Assess 71-43-2", InMemoryThreadStore(), runtime)
    flush_telemetry(monitoring)
    values = [str(v) for s in exporter.exported_spans for v in (s.attributes or {}).values()]
    assert values
    assert not [v for v in values if KEY in v or any(p.search(v) for p in KEY_PATTERNS)]


def test_the_trace_context_travels_in_the_task_headers_not_its_arguments(
    monitoring: TelemetrySettings,
    exporter: TestExporter,
) -> None:
    seen: list[tuple[object, object]] = []

    def capture(body: object = None, headers: object = None, **_: object) -> None:
        seen.append((body, headers))

    app = build_celery(get_worker_settings(), "memory://")
    instrument_task_queue(monitoring)
    before_task_publish.connect(capture, weak=False)
    try:
        with logfire.span("enqueue"):
            app.send_task(TASK_NAME, args=["a" * 32, str(OWNER)], retry=False)  # pyright: ignore[reportUnknownMemberType]
    finally:
        before_task_publish.disconnect(capture)
        CeleryInstrumentor().uninstrument()
    ((body, headers),) = seen
    assert "traceparent" in cast(dict[str, object], headers)
    assert "traceparent" not in json.dumps(body, default=str)
