"""Tests for the command line run: it uses the stored keys, falling back to the environment."""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, ToolCall
from langchain_core.tools import tool
from logfire.testing import TestExporter
from opentelemetry.sdk.trace import ReadableSpan

from app.key_vault import default_service_keys
from app.run import ask, run_config, stored_keys_provided
from app.usage_meter import CallUsage, UsageRecorder
from config.agent import get_agent_settings
from config.telemetry import TelemetrySettings
from tests.fakes import (
    CENSUS_ENTRY,
    COMPTOX_ENTRY,
    OPENAI_ENTRY,
    FakeCredentialStore,
    ScriptedChatModel,
)
from tools.credentials import CENSUS_KEY, COMPTOX_KEY, PROVIDER_KEY

STORED: dict[tuple[str, str], str] = {
    OPENAI_ENTRY: "sk-stored-" + "o" * 20,  # pragma: allowlist secret
    CENSUS_ENTRY: "stored-census-" + "c" * 20,  # pragma: allowlist secret
    COMPTOX_ENTRY: "stored-comptox-" + "t" * 20,  # pragma: allowlist secret
}


@tool
def probe_all() -> str:
    """Report which keys this tool can see (test double for tools that need keys)."""
    seen = [holder.get() for holder in (PROVIDER_KEY, CENSUS_KEY, COMPTOX_KEY)]
    return ",".join(key.get_secret_value() if key else "none" for key in seen)


def _store(*entries: tuple[str, str]) -> FakeCredentialStore:
    store = FakeCredentialStore()
    store.entries.update({entry: STORED[entry] for entry in entries})
    return store


def test_every_stored_key_reaches_the_tools_during_the_run() -> None:
    keys = default_service_keys(_store(OPENAI_ENTRY, CENSUS_ENTRY, COMPTOX_ENTRY))
    with stored_keys_provided(keys):
        assert probe_all.invoke({}) == ",".join(STORED.values())
    assert probe_all.invoke({}) == "none,none,none"


def test_a_key_that_is_not_stored_is_left_to_its_environment_variable() -> None:
    keys = default_service_keys(_store(CENSUS_ENTRY))
    with stored_keys_provided(keys):
        assert probe_all.invoke({}) == f"none,{STORED[CENSUS_ENTRY]},none"


def test_an_unavailable_keychain_provides_nothing_and_does_not_fail() -> None:
    keys = default_service_keys(FakeCredentialStore(fail=True))
    with stored_keys_provided(keys):
        assert probe_all.invoke({}) == "none,none,none"


def test_ask_gives_the_agents_tools_the_stored_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("agent.graph.get_all_tools", lambda: [probe_all])
    monkeypatch.setattr(
        "app.run.completion_guard",
        lambda: None,
    )  # the scripted model has no reviewer
    call = AIMessage(content="", tool_calls=[ToolCall(name="probe_all", args={}, id="c1")])
    model = ScriptedChatModel([call, AIMessage(content="final answer")])
    keys = default_service_keys(_store(OPENAI_ENTRY, CENSUS_ENTRY, COMPTOX_ENTRY))
    assert ask("Assess CAS 71-43-2", model, keys).answer == "final answer"
    assert CENSUS_KEY.get() is None  # nothing is left behind once the run is over


class FakeToolModel(GenericFakeChatModel):
    def bind_tools(self, tools: Any, **kwargs: Any) -> FakeToolModel:
        return self


def _usage(inp: int, out: int) -> Any:
    return {"input_tokens": inp, "output_tokens": out, "total_tokens": inp + out}


def _session(exporter: TestExporter, monitoring: TelemetrySettings) -> ReadableSpan:
    name = monitoring.spans.cli_session
    (span,) = [
        s
        for s in exporter.exported_spans
        if s.name == name and (s.attributes or {}).get("logfire.span_type") != "pending_span"
    ]
    return span


def _enabled(monkeypatch: pytest.MonkeyPatch, monitoring: TelemetrySettings) -> None:
    monkeypatch.setattr("app.run.get_telemetry_settings", lambda: monitoring)
    monkeypatch.setattr("app.run.completion_guard", lambda: None)
    monkeypatch.setattr("agent.graph.get_all_tools", lambda: [probe_all])


def test_run_config_adds_the_callbacks_only_when_there_are_some() -> None:
    settings = get_agent_settings()
    assert "callbacks" not in run_config(settings)
    handler = UsageRecorder("m")
    assert run_config(settings, [handler]).get("callbacks") == [handler]


def test_ask_records_one_session_with_the_runs_usage(
    monkeypatch: pytest.MonkeyPatch,
    monitoring: TelemetrySettings,
    exporter: TestExporter,
) -> None:
    _enabled(monkeypatch, monitoring)
    call = AIMessage(
        content="",
        tool_calls=[ToolCall(name="probe_all", args={}, id="c1")],
        usage_metadata=_usage(10, 3),
    )
    model = FakeToolModel(
        messages=iter([call, AIMessage(content="done", usage_metadata=_usage(20, 2))]),
    )
    keys = default_service_keys(_store(OPENAI_ENTRY, CENSUS_ENTRY, COMPTOX_ENTRY))
    result = ask("Assess CAS 71-43-2", model, keys)
    model_name = get_agent_settings().model
    assert result.answer == "done"
    assert result.calls == (CallUsage(model_name, 10, 0, 3), CallUsage(model_name, 20, 0, 2))
    attributes = _session(exporter, monitoring).attributes or {}
    names, prefix = monitoring.attributes, monitoring.attributes.usage_prefix
    assert len(str(attributes[names.session_id])) == 32
    assert attributes[names.question] == "Assess CAS 71-43-2"
    assert (attributes[names.model], attributes[names.outcome]) == (model_name, "ok")
    assert (attributes[f"{prefix}calls"], attributes[f"{prefix}input_tokens"]) == (2, 30)
    assert attributes[f"{prefix}cost_status"] == "estimate"


def test_a_failed_run_is_recorded_with_the_calls_made_before_it(
    monkeypatch: pytest.MonkeyPatch,
    monitoring: TelemetrySettings,
    exporter: TestExporter,
) -> None:
    _enabled(monkeypatch, monitoring)
    call = AIMessage(
        content="",
        tool_calls=[ToolCall(name="probe_all", args={}, id="c1")],
        usage_metadata=_usage(10, 3),
    )
    model = FakeToolModel(messages=iter([call]))  # the second model call has nothing to say
    keys = default_service_keys(_store(OPENAI_ENTRY, CENSUS_ENTRY, COMPTOX_ENTRY))
    with pytest.raises(Exception):  # noqa: B017 - whatever the model raised propagates
        ask("Assess CAS 71-43-2", model, keys)
    attributes = _session(exporter, monitoring).attributes or {}
    assert attributes[monitoring.attributes.outcome] == "error"
    assert attributes[f"{monitoring.attributes.usage_prefix}input_tokens"] == 10


def test_a_disabled_monitoring_leaves_the_run_unrecorded(
    monkeypatch: pytest.MonkeyPatch,
    exporter: TestExporter,
) -> None:
    monkeypatch.setattr("app.run.completion_guard", lambda: None)
    monkeypatch.setattr("agent.graph.get_all_tools", lambda: [probe_all])
    model = FakeToolModel(messages=iter([AIMessage(content="final answer")]))
    keys = default_service_keys(_store(OPENAI_ENTRY, CENSUS_ENTRY, COMPTOX_ENTRY))
    assert ask("Assess CAS 71-43-2", model, keys).answer == "final answer"
    assert exporter.exported_spans == []
