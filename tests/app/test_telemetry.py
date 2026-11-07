"""Tests for the monitoring of agent runs (Logfire spans); nothing is ever sent."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import logfire
import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langsmith import Client
from logfire.testing import TestExporter
from opentelemetry.sdk.trace import ReadableSpan

from agent.graph import build_agent
from app import telemetry
from app.telemetry import (
    SCRUBBED,
    TurnSegment,
    configure_telemetry,
    flush_telemetry,
    run_tracer,
    session_span,
    usage_fields,
)
from app.usage_meter import CallUsage
from config.telemetry import TelemetrySettings, get_telemetry_settings
from tests.app.test_usage_meter import PRICING

SETTINGS = get_telemetry_settings()
ATTRS = SETTINGS.attributes
KEY = "sk-abcdefghijklmnopqrstuvwx"  # pragma: allowlist secret


@tool
def lookup(cas: str) -> str:
    """Look up a CAS number."""
    return f"name of {cas}"


class FakeToolModel(GenericFakeChatModel):
    def bind_tools(self, tools: Any, **kwargs: Any) -> FakeToolModel:
        return self


def _usage(inp: int, out: int) -> dict[str, int]:
    return {"input_tokens": inp, "output_tokens": out, "total_tokens": inp + out}


def _agent_run(settings: TelemetrySettings, tool_result_key: bool = False) -> None:
    """One agent run: a model call asking for a tool, the tool, a final model call."""
    ask = AIMessage(
        content="",
        tool_calls=[{"name": "lookup", "args": {"cas": "71-43-2"}, "id": "c1"}],
        usage_metadata=_usage(10, 3),  # pyright: ignore[reportArgumentType]
    )
    done = AIMessage(content="done", usage_metadata=_usage(20, 2))  # pyright: ignore[reportArgumentType]
    agent = build_agent(
        FakeToolModel(messages=iter([ask, done])),
        tools=[lookup],
        system_prompt="s",
    )
    client = Client(tracing_mode="otel")
    config = {"callbacks": [run_tracer(settings, client)]}
    agent.invoke({"messages": [HumanMessage(content="q")]}, config)  # pyright: ignore[reportArgumentType]
    client.flush()


def _spans(exporter: TestExporter) -> list[ReadableSpan]:
    spans = exporter.exported_spans
    return [s for s in spans if (s.attributes or {}).get("logfire.span_type") != "pending_span"]


def _named(spans: list[ReadableSpan], name: str) -> ReadableSpan:
    (found,) = [s for s in spans if s.name == name and s.parent is None]
    return found


def _kind(span: ReadableSpan) -> object:
    return (span.attributes or {}).get("gen_ai.operation.name")


def _is_descendant(span: ReadableSpan, root: ReadableSpan, spans: list[ReadableSpan]) -> bool:
    by_id = {s.context.span_id: s for s in spans if s.context is not None}
    parent = span.parent
    while parent is not None:
        if root.context is not None and parent.span_id == root.context.span_id:
            return True
        up = by_id.get(parent.span_id)
        parent = up.parent if up is not None else None
    return False


def test_model_and_tool_calls_nest_in_one_session_trace(exporter: TestExporter) -> None:
    with session_span(SETTINGS, SETTINGS.spans.cli_session, "s1", "Assess 71-43-2", "m"):
        _agent_run(SETTINGS)
    logfire.force_flush()
    spans = _spans(exporter)
    root = _named(spans, SETTINGS.spans.cli_session)
    models = [s for s in spans if _kind(s) == "chat"]
    tools = [s for s in spans if _kind(s) == "execute_tool"]
    assert (len(models), len(tools)) == (2, 1)
    assert (tools[0].attributes or {}).get("gen_ai.tool.name") == "lookup"
    assert all(_is_descendant(s, root, spans) for s in [*models, *tools])
    assert len({s.context.trace_id for s in [root, *models, *tools] if s.context}) == 1


def test_session_span_carries_id_question_model_and_outcome(exporter: TestExporter) -> None:
    with session_span(SETTINGS, SETTINGS.spans.web_turn, "thread-7", "Assess X", "gpt-x"):
        pass
    attributes = _named(_spans(exporter), SETTINGS.spans.web_turn).attributes or {}
    assert attributes[ATTRS.session_id] == "thread-7"
    assert (attributes[ATTRS.question], attributes[ATTRS.model]) == ("Assess X", "gpt-x")
    assert attributes[ATTRS.outcome] == "ok"
    assert ATTRS.turn_id not in attributes and ATTRS.resume_index not in attributes


def test_a_web_turn_span_carries_its_turn_id_and_resume_index(exporter: TestExporter) -> None:
    segment = TurnSegment(turn_id="turn-9", resume_index=2)
    with session_span(SETTINGS, SETTINGS.spans.web_turn, "thread-7", "q", "m", segment):
        pass
    attributes = _named(_spans(exporter), SETTINGS.spans.web_turn).attributes or {}
    assert (attributes[ATTRS.turn_id], attributes[ATTRS.resume_index]) == ("turn-9", 2)
    assert attributes[ATTRS.session_id] == "thread-7"


def test_a_run_that_raises_ends_with_error_and_keeps_its_spans(exporter: TestExporter) -> None:
    with pytest.raises(RuntimeError, match="boom"):
        with session_span(SETTINGS, SETTINGS.spans.cli_session, "s1", "q", "m"):
            _agent_run(SETTINGS)
            raise RuntimeError("boom")
    logfire.force_flush()
    spans = _spans(exporter)
    assert (_named(spans, SETTINGS.spans.cli_session).attributes or {})[ATTRS.outcome] == "error"
    assert [s for s in spans if _kind(s) == "chat"]


def test_fail_marks_the_outcome_without_raising(exporter: TestExporter) -> None:
    with session_span(SETTINGS, SETTINGS.spans.web_turn, "t", "q", "m") as span:
        span.fail()
    attributes = _named(_spans(exporter), SETTINGS.spans.web_turn).attributes or {}
    assert attributes[ATTRS.outcome] == "error"


def test_disabled_records_nothing_and_adds_no_callback(exporter: TestExporter) -> None:
    off = replace(SETTINGS, enabled=False)
    assert run_tracer(off) is None
    with session_span(off, off.spans.cli_session, "s", "q", "m") as span:
        span.record_usage([CallUsage("m", 1, 0, 1)], PRICING)
    flush_telemetry(off)
    assert exporter.exported_spans == []


def test_usage_is_set_on_the_span_with_the_turn_and_session_prefixes(
    exporter: TestExporter,
) -> None:
    turn = [CallUsage("m", 100, 40, 20)]
    session = [*turn, CallUsage("m", 10, 0, 5)]
    with session_span(SETTINGS, SETTINGS.spans.web_turn, "t", "q", "m") as span:
        span.record_usage(turn, PRICING)
        span.record_usage(session, PRICING, session=True)
    attributes = _named(_spans(exporter), SETTINGS.spans.web_turn).attributes or {}
    assert attributes[f"{ATTRS.usage_prefix}input_tokens"] == 100
    assert attributes[f"{ATTRS.session_usage_prefix}input_tokens"] == 110
    assert attributes[f"{ATTRS.usage_prefix}cost_status"] == "estimate"
    assert f"{ATTRS.usage_prefix}cost_usd" in attributes


def test_usage_fields_priced_lower_bound_and_unpriced() -> None:
    priced = usage_fields([CallUsage("m", 100, 40, 20)], PRICING)
    assert (priced["cost_status"], priced["complete"]) == ("estimate", True)
    partial = usage_fields([CallUsage("m", 100, 0, 20), CallUsage("m", None, 0, None)], PRICING)
    assert (partial["cost_status"], partial["complete"]) == ("lower_bound", False)
    assert "cost_usd" in partial
    unpriced = usage_fields([CallUsage("other", 100, 0, 20)], PRICING)
    assert unpriced["cost_status"] == "unpriced"
    assert "cost_usd" not in unpriced and unpriced["input_tokens"] == 100


@pytest.mark.parametrize(
    "secret",
    [KEY, f"Authorization: Bearer {KEY[3:]}", "api_key=abcdefgh12345678", "?x=1&key=abcdef123456"],
)
def test_keys_never_reach_a_span(secret: str, exporter: TestExporter) -> None:
    with session_span(SETTINGS, SETTINGS.spans.cli_session, "s", f"question {secret}", "m") as span:
        logfire.info("tool result {r}", r=f"found {secret} in result")
        span.record_usage([], PRICING)
    logfire.force_flush()
    dumped = " ".join(str(dict(s.attributes or {})) for s in exporter.exported_spans)
    assert SCRUBBED in dumped
    assert secret.split("=")[-1].split(" ")[-1] not in dumped


def test_configure_does_nothing_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(**_: object) -> None:
        raise AssertionError("logfire.configure must not be called")

    monkeypatch.setattr(telemetry.logfire, "configure", refuse)
    configure_telemetry(replace(SETTINGS, enabled=False))


def test_configure_sends_only_with_a_token(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def record(**kwargs: object) -> None:
        seen.update(kwargs)

    monkeypatch.setattr(telemetry.logfire, "configure", record)
    configure_telemetry(SETTINGS)
    assert seen["send_to_logfire"] == "if-token-present"
    assert (seen["service_name"], seen["environment"]) == (
        SETTINGS.service_name,
        SETTINGS.environment,
    )
    assert seen["console"] is False
