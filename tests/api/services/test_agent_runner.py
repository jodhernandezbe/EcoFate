"""Tests for running one turn and translating the agent's stream into contract events."""

from __future__ import annotations

import asyncio
import io
import logging
import os
from collections.abc import Callable
from datetime import date

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolCall
from langchain_core.tools import StructuredTool, ToolException, tool
from pydantic import SecretStr

from agent.guardrails import ScopeGuard
from api.core.logging_filter import LITERAL_REDACTED, SecretRedactionFilter
from api.schemas.chat import (
    AssistantMessage,
    ChatRequest,
    ErrorEvent,
    GuardrailPivotResponse,
    ScopeDecision,
    StreamEvent,
    Token,
    ToolStatus,
    Usage,
)
from api.services.agent_runner import NO_KEY_MESSAGE, AgentRuntime, ModelFactory, run_turn
from api.services.threads import ThreadStore
from app.key_vault import ServiceKeys, default_service_keys
from config.ui import ModelPrice
from tests.fakes import (
    CENSUS_ENTRY,
    COMPTOX_ENTRY,
    OPENAI_ENTRY,
    FakeCredentialStore,
    ScriptedChatModel,
    reply,
    scripted,
    verdict,
)
from tools.credentials import CENSUS_KEY, COMPTOX_KEY, PROVIDER_KEY

pytestmark = pytest.mark.anyio
KEY = "sk-proj-" + "k1L2m3N4o5" * 3  # pragma: allowlist secret


def _keys(store: FakeCredentialStore, *, with_key: bool = True) -> ServiceKeys:
    if with_key:
        store.entries[OPENAI_ENTRY] = KEY
    return default_service_keys(store)


async def _run(
    message: str,
    store: FakeCredentialStore,
    build_model: ModelFactory,
    threads: ThreadStore | None = None,
    *,
    thread_id: str = "t1",
    with_key: bool = True,
) -> list[StreamEvent]:
    events = run_turn(
        ChatRequest(thread_id=thread_id, message=message),
        keys=_keys(store, with_key=with_key),
        threads=threads or ThreadStore(),
        runtime=AgentRuntime(build_model, 10),
    )
    return [event async for event in events]


def _factory(model: BaseChatModel) -> Callable[[SecretStr], BaseChatModel]:
    return lambda key: model


async def test_turn_streams_tokens_then_the_final_message() -> None:
    events = await _run("hi", FakeCredentialStore(), _factory(scripted("hello there world")))
    assert [e.type for e in events][0] == "turn_started"
    assert [e.type for e in events][-1] == "turn_finished"
    assert [e.seq for e in events] == list(range(len(events)))
    tokens = "".join(e.text for e in events if isinstance(e, Token))
    assert tokens == "hello there world"
    final = [e for e in events if isinstance(e, AssistantMessage)]
    assert [e.text for e in final] == ["hello there world"]


async def test_missing_key_is_a_user_message_and_builds_no_model() -> None:
    built: list[SecretStr] = []

    def build(key: SecretStr) -> BaseChatModel:
        built.append(key)
        return scripted("never")

    events = await _run("hi", FakeCredentialStore(), build, with_key=False)
    errors = [e for e in events if isinstance(e, ErrorEvent)]
    assert [e.message for e in errors] == [NO_KEY_MESSAGE]
    assert built == []
    assert events[-1].type == "turn_finished"


async def test_unavailable_keychain_is_reported_safely() -> None:
    events = await _run(
        "hi",
        FakeCredentialStore(fail=True),
        _factory(scripted("x")),
        with_key=False,
    )
    errors = [e for e in events if isinstance(e, ErrorEvent)]
    assert errors[0].message == "The OS keychain is unavailable."
    assert events[-1].type == "turn_finished"


async def test_the_key_is_read_once_and_handed_to_the_model_factory() -> None:
    store = FakeCredentialStore()
    seen: list[str] = []

    def build(key: SecretStr) -> BaseChatModel:
        seen.append(key.get_secret_value())
        return scripted("ok")

    await _run("hi", store, build)
    reads = [call[1:] for call in store.calls if call[0] == "get"]
    assert sorted(reads) == sorted([OPENAI_ENTRY, CENSUS_ENTRY, COMPTOX_ENTRY])  # each key, once
    assert seen == [KEY]


async def test_model_failure_is_generic_and_leaks_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def build(key: SecretStr) -> BaseChatModel:
        raise RuntimeError(f"provider rejected {KEY}")

    events = await _run("hi", FakeCredentialStore(), build)
    error = next(e for e in events if isinstance(e, ErrorEvent))
    assert KEY not in error.model_dump_json()
    assert error.message == "Something went wrong. Try again."
    assert error.correlation_id in caplog.text
    assert events[-1].type == "turn_finished"


async def test_failure_mid_run_still_finishes_the_stream() -> None:
    events = await _run("hi", FakeCredentialStore(), _factory(scripted()))
    assert any(isinstance(e, ErrorEvent) for e in events)
    assert events[-1].type == "turn_finished"


async def test_follow_up_turn_sees_the_earlier_history() -> None:
    threads = ThreadStore()
    model = scripted("first answer", "second answer")
    store = FakeCredentialStore()
    await _run("one", store, _factory(model), threads)
    await _run("two", store, _factory(model), threads)
    saved = threads.checkpointer.get_tuple({"configurable": {"thread_id": "t1"}})
    assert saved is not None
    texts = [m.content for m in saved.checkpoint["channel_values"]["messages"]]
    assert texts == ["one", "first answer", "two", "second answer"]


@tool
def probe_key() -> str:
    """Report the key this tool can see (test double for a tool that calls the provider)."""
    key = PROVIDER_KEY.get()
    return key.get_secret_value() if key is not None else "none"


def _calling_probe() -> BaseChatModel:
    call = AIMessage(content="", tool_calls=[{"name": "probe_key", "args": {}, "id": "c1"}])
    return ScriptedChatModel([call, AIMessage(content="done")])


async def test_tools_see_the_turns_key_and_it_is_cleared_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("agent.graph.get_all_tools", lambda: [probe_key])
    threads = ThreadStore()
    await _run("go", FakeCredentialStore(), _factory(_calling_probe()), threads)
    saved = threads.checkpointer.get_tuple({"configurable": {"thread_id": "t1"}})
    assert saved is not None
    tool_messages = [m for m in saved.checkpoint["channel_values"]["messages"] if m.type == "tool"]
    assert [m.content for m in tool_messages] == [KEY]
    assert PROVIDER_KEY.get() is None
    assert KEY not in os.environ.values()


async def test_concurrent_turns_keep_their_own_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("agent.graph.get_all_tools", lambda: [probe_key])
    threads = ThreadStore()
    seen: dict[str, str] = {}

    async def turn(thread_id: str, key: str) -> None:
        store = FakeCredentialStore()
        store.entries[OPENAI_ENTRY] = key
        keys = default_service_keys(store)
        request = ChatRequest(thread_id=thread_id, message="go")
        events = run_turn(
            request,
            keys=keys,
            threads=threads,
            runtime=AgentRuntime(_factory(_calling_probe()), 10),
        )
        [event async for event in events]
        saved = threads.checkpointer.get_tuple({"configurable": {"thread_id": thread_id}})
        assert saved is not None
        messages = saved.checkpoint["channel_values"]["messages"]
        seen[thread_id] = next(m.content for m in messages if m.type == "tool")

    await asyncio.gather(turn("a", "sk-key-for-a-0123456789"), turn("b", "sk-key-for-b-0123456789"))
    assert seen == {"a": "sk-key-for-a-0123456789", "b": "sk-key-for-b-0123456789"}


def _fail() -> str:
    raise ToolException("the service said no")


flaky = StructuredTool.from_function(
    _fail,
    name="flaky",
    description="A tool that reports a handled error.",
    handle_tool_error=True,
)


def _calling(*names: str) -> BaseChatModel:
    calls = [ToolCall(name=name, args={}, id=f"c{i}") for i, name in enumerate(names)]
    return ScriptedChatModel(
        [AIMessage(content="", tool_calls=calls), AIMessage(content="all done")],
    )


async def _tool_events(
    monkeypatch: pytest.MonkeyPatch,
    model: BaseChatModel,
    labels: dict[str, str],
) -> list[StreamEvent]:
    monkeypatch.setattr("agent.graph.get_all_tools", lambda: [probe_key, flaky])
    run = run_turn(
        ChatRequest(thread_id="t1", message="go"),
        keys=_keys(FakeCredentialStore()),
        threads=ThreadStore(),
        runtime=AgentRuntime(_factory(model), 10, labels),
    )
    return [event async for event in run]


async def test_each_tool_call_is_a_started_and_a_finished_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = await _tool_events(monkeypatch, _calling("probe_key"), {"probe_key": "Probed the key"})
    steps = [e for e in events if isinstance(e, ToolStatus)]
    assert [(e.phase, e.label, e.status) for e in steps] == [
        ("started", "Probed the key", None),
        ("finished", "Probed the key", "ok"),
    ]
    assert steps[0].call_id == steps[1].call_id == "c0"
    kinds = [e.type for e in events]
    assert (
        kinds.index("tool_status") < kinds.index("assistant_message") < kinds.index("turn_finished")
    )
    assert [e.seq for e in events] == list(range(len(events)))


async def test_an_unlabelled_tool_is_shown_by_its_name(monkeypatch: pytest.MonkeyPatch) -> None:
    events = await _tool_events(monkeypatch, _calling("probe_key"), {})
    labels = {e.label for e in events if isinstance(e, ToolStatus)}
    assert labels == {"probe_key"}


async def test_a_failing_tool_finishes_with_error_status(monkeypatch: pytest.MonkeyPatch) -> None:
    events = await _tool_events(monkeypatch, _calling("flaky"), {})
    finished = [e for e in events if isinstance(e, ToolStatus) and e.phase == "finished"]
    assert [(e.tool_name, e.status) for e in finished] == [("flaky", "error")]
    assert events[-1].type == "turn_finished"
    assert not any(isinstance(e, ErrorEvent) for e in events)  # the agent carried on


async def test_parallel_calls_are_all_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    events = await _tool_events(monkeypatch, _calling("probe_key", "flaky"), {})
    steps = [e for e in events if isinstance(e, ToolStatus)]
    assert sorted((e.phase, e.call_id) for e in steps) == [
        ("finished", "c0"),
        ("finished", "c1"),
        ("started", "c0"),
        ("started", "c1"),
    ]


async def test_tool_payloads_never_reach_the_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    events = await _tool_events(monkeypatch, _calling("probe_key", "flaky"), {})
    stream = "".join(e.model_dump_json() for e in events)
    assert KEY not in stream  # probe_key returns the key as its result
    assert "the service said no" not in stream


PRICING = {
    "m": ModelPrice(
        input_usd_per_mtok=2.0,
        cached_input_usd_per_mtok=0.5,
        output_usd_per_mtok=8.0,
        priced_on=date(2026, 1, 2),
        source_url="https://example.test/pricing",
    ),
}


async def _usage_run(model: BaseChatModel, threads: ThreadStore, thread_id: str = "t1") -> Usage:
    run = run_turn(
        ChatRequest(thread_id=thread_id, message="go"),
        keys=_keys(FakeCredentialStore()),
        threads=threads,
        runtime=AgentRuntime(_factory(model), 10, model_name="m", pricing=PRICING),
    )
    events = [event async for event in run]
    assert events[-1].type == "turn_finished"
    usage = events[-2]
    assert isinstance(usage, Usage)
    return usage


async def test_usage_is_reported_for_every_model_call_of_the_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("agent.graph.get_all_tools", lambda: [probe_key])
    call = AIMessage(
        content="",
        tool_calls=[ToolCall(name="probe_key", args={}, id="c1")],
        usage_metadata=reply("", 100, 20, cached=40).usage_metadata,
    )
    model = ScriptedChatModel([call, reply("done", 150, 30)])
    usage = await _usage_run(model, ThreadStore())
    assert (usage.turn.calls, usage.turn.input_tokens, usage.turn.output_tokens) == (2, 250, 50)
    assert usage.turn.cached_input_tokens == 40
    assert usage.turn.complete is True
    assert usage.turn.cost_status == "estimate"
    assert usage.turn.cost_usd == pytest.approx(
        ((60 + 150) * 2.0 + 40 * 0.5 + 50 * 8.0) / 1_000_000,
    )


async def test_session_totals_add_up_and_a_reset_clears_them() -> None:
    threads = ThreadStore()
    model = ScriptedChatModel([reply("one", 100, 10), reply("two", 200, 20)])
    first = await _usage_run(model, threads)
    second = await _usage_run(model, threads)
    assert second.turn.input_tokens == 200
    assert second.session.input_tokens == first.turn.input_tokens + 200 == 300
    assert second.session.calls == 2
    threads.reset("t1")
    assert threads.session_calls("t1") == []


async def test_a_failed_turn_still_reports_the_calls_it_made(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("agent.graph.get_all_tools", lambda: [probe_key])
    call = AIMessage(
        content="",
        tool_calls=[ToolCall(name="probe_key", args={}, id="c1")],
        usage_metadata=reply("", 100, 20).usage_metadata,
    )
    usage = await _usage_run(ScriptedChatModel([call]), ThreadStore())  # the 2nd call fails
    assert usage.turn.calls == 1
    assert usage.turn.input_tokens == 100


async def test_a_model_that_reports_no_usage_makes_the_turn_incomplete() -> None:
    usage = await _usage_run(scripted("answer"), ThreadStore())
    assert usage.turn.calls == 1
    assert usage.turn.complete is False
    assert usage.turn.cost_status == "lower_bound"
    assert usage.turn.input_tokens == 0


async def test_a_turn_with_no_key_reports_zero_usage() -> None:
    events = await _run("hi", FakeCredentialStore(), _factory(scripted("x")), with_key=False)
    usage = next(e for e in events if isinstance(e, Usage))
    assert (usage.turn.calls, usage.session.calls) == (0, 0)


async def test_an_unpriced_model_still_reports_tokens() -> None:
    run = run_turn(
        ChatRequest(thread_id="t1", message="go"),
        keys=_keys(FakeCredentialStore()),
        threads=ThreadStore(),
        runtime=AgentRuntime(_factory(ScriptedChatModel([reply("a", 5, 6)])), 10, model_name="x"),
    )
    usage = next(e for e in [event async for event in run] if isinstance(e, Usage))
    assert (usage.turn.input_tokens, usage.turn.cost_usd, usage.turn.cost_status) == (
        5,
        None,
        "unpriced",
    )


# --- the Census and CompTox keys ------------------------------------------------------------

CENSUS = "c3n5u5k3y" + "7f" * 16  # pragma: allowlist secret
COMPTOX = "ct0x-" + "9d" * 14  # pragma: allowlist secret
tool_log = logging.getLogger("tests.service_tool")


@tool
def probe_census() -> str:
    """Report the Census key this tool can see, and log it as a careless tool might."""
    key = CENSUS_KEY.get()
    value = key.get_secret_value() if key is not None else "none"
    tool_log.warning("census call with %s", value)
    return value


@tool
def probe_comptox() -> str:
    """Report the CompTox key this tool can see."""
    key = COMPTOX_KEY.get()
    return key.get_secret_value() if key is not None else "none"


def _service_probe_model() -> BaseChatModel:
    calls = [
        ToolCall(name="probe_census", args={}, id="c1"),
        ToolCall(name="probe_comptox", args={}, id="c2"),
    ]
    return ScriptedChatModel([AIMessage(content="", tool_calls=calls), AIMessage(content="done")])


async def _probe_turn(
    monkeypatch: pytest.MonkeyPatch,
    store: FakeCredentialStore,
    threads: ThreadStore | None = None,
) -> dict[str, str]:
    monkeypatch.setattr("agent.graph.get_all_tools", lambda: [probe_census, probe_comptox])
    threads = threads or ThreadStore()
    run = run_turn(
        ChatRequest(thread_id="t1", message="go"),
        keys=default_service_keys(store),
        threads=threads,
        runtime=AgentRuntime(_factory(_service_probe_model()), 10),
    )
    [event async for event in run]
    saved = threads.checkpointer.get_tuple({"configurable": {"thread_id": "t1"}})
    assert saved is not None
    messages = saved.checkpoint["channel_values"]["messages"]
    return {m.name: m.content for m in messages if m.type == "tool"}


async def test_tools_see_the_stored_census_and_comptox_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FakeCredentialStore()
    store.entries.update({OPENAI_ENTRY: KEY, CENSUS_ENTRY: CENSUS, COMPTOX_ENTRY: COMPTOX})
    seen = await _probe_turn(monkeypatch, store)
    assert seen == {"probe_census": CENSUS, "probe_comptox": COMPTOX}
    assert CENSUS_KEY.get() is None and COMPTOX_KEY.get() is None
    assert CENSUS not in os.environ.values() and COMPTOX not in os.environ.values()


async def test_the_turn_runs_with_only_the_model_key(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeCredentialStore()
    store.entries[OPENAI_ENTRY] = KEY
    seen = await _probe_turn(monkeypatch, store)
    assert seen == {"probe_census": "none", "probe_comptox": "none"}  # the tools report it missing


async def test_one_missing_service_key_does_not_hide_the_other(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FakeCredentialStore()
    store.entries.update({OPENAI_ENTRY: KEY, COMPTOX_ENTRY: COMPTOX})
    seen = await _probe_turn(monkeypatch, store)
    assert seen == {"probe_census": "none", "probe_comptox": COMPTOX}


async def test_a_service_key_is_redacted_from_logs_during_the_turn_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(SecretRedactionFilter())
    tool_log.addHandler(handler)
    try:
        store = FakeCredentialStore()
        store.entries.update({OPENAI_ENTRY: KEY, CENSUS_ENTRY: CENSUS})
        await _probe_turn(monkeypatch, store)
        during = stream.getvalue()
        tool_log.warning("after the turn %s", CENSUS)
    finally:
        tool_log.removeHandler(handler)
    assert CENSUS not in during
    assert LITERAL_REDACTED in during
    assert f"after the turn {CENSUS}" in stream.getvalue()  # protection ended with the turn


async def test_concurrent_turns_keep_their_own_service_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("agent.graph.get_all_tools", lambda: [probe_census, probe_comptox])
    threads = ThreadStore()
    seen: dict[str, str] = {}

    async def turn(thread_id: str, census: str) -> None:
        store = FakeCredentialStore()
        store.entries.update({OPENAI_ENTRY: KEY, CENSUS_ENTRY: census})
        run = run_turn(
            ChatRequest(thread_id=thread_id, message="go"),
            keys=default_service_keys(store),
            threads=threads,
            runtime=AgentRuntime(_factory(_service_probe_model()), 10),
        )
        [event async for event in run]
        saved = threads.checkpointer.get_tuple({"configurable": {"thread_id": thread_id}})
        assert saved is not None
        tools = [m for m in saved.checkpoint["channel_values"]["messages"] if m.type == "tool"]
        seen[thread_id] = next(m.content for m in tools if m.name == "probe_census")

    await asyncio.gather(
        turn("a", "census-key-for-a-0123456789"),
        turn("b", "census-key-for-b-0123456789"),
    )
    assert seen == {"a": "census-key-for-a-0123456789", "b": "census-key-for-b-0123456789"}


async def test_an_unavailable_keychain_stops_the_turn_with_a_safe_message() -> None:
    events = await _run(
        "hi",
        FakeCredentialStore(fail=True),
        _factory(scripted("x")),
        with_key=False,
    )
    errors = [e for e in events if isinstance(e, ErrorEvent)]
    assert [e.message for e in errors] == ["The OS keychain is unavailable."]


# --- the scope guardrail in the web program --------------------------------------------------

GUARD = ScopeGuard(classifier_prompt="CLASSIFY", fallback_reply="FALLBACK", history_window=4)
PIVOT = "I can't help with that, but we can explore TRI releases or the map."


def _guarded(model: BaseChatModel) -> AgentRuntime:
    return AgentRuntime(_factory(model), 10, model_name="m", pricing=PRICING, scope_guard=GUARD)


async def _guarded_turn(model: ScriptedChatModel, message: str = "hello") -> list[StreamEvent]:
    run = run_turn(
        ChatRequest(thread_id="t1", message=message),
        keys=_keys(FakeCredentialStore()),
        threads=ThreadStore(),
        runtime=_guarded(model),
    )
    return [event async for event in run]


async def test_an_in_scope_turn_reports_the_scope_then_runs_the_agent() -> None:
    model = ScriptedChatModel(
        [reply("an answer", 50, 5)],
        classifier=[verdict(True, usage=(20, 4))],
    )
    events = await _guarded_turn(model)
    kinds = [e.type for e in events]
    assert kinds[:2] == ["turn_started", "scope"]
    scope = events[1]
    assert isinstance(scope, ScopeDecision) and scope.in_scope is True
    assert "guardrail_pivot" not in kinds
    assert "".join(e.text for e in events if isinstance(e, Token)) == "an answer"
    assert model.calls == 1


async def test_an_off_topic_turn_streams_the_pivot_and_runs_no_agent_or_tool() -> None:
    model = ScriptedChatModel([reply("never", 1, 1)], classifier=[verdict(False, PIVOT)])
    events = await _guarded_turn(model, "write a snake game")
    assert [e.type for e in events] == [
        "turn_started",
        "scope",
        "guardrail_pivot",
        "usage",
        "turn_finished",
    ]
    scope, pivot = events[1], events[2]
    assert isinstance(scope, ScopeDecision) and scope.in_scope is False
    assert isinstance(pivot, GuardrailPivotResponse) and pivot.text == PIVOT
    assert model.calls == 0  # the agent model never ran
    assert not any(isinstance(e, (Token, ToolStatus, ErrorEvent)) for e in events)


async def test_the_classifier_call_is_part_of_the_turns_usage() -> None:
    model = ScriptedChatModel(
        [reply("an answer", 50, 5)],
        classifier=[verdict(True, usage=(20, 4))],
    )
    usage = next(e for e in await _guarded_turn(model) if isinstance(e, Usage))
    assert usage.turn.calls == 2  # the scope check and the agent
    assert (usage.turn.input_tokens, usage.turn.output_tokens) == (70, 9)
    assert usage.turn.complete is True


async def test_a_redirected_turn_is_billed_for_the_one_classifier_call() -> None:
    model = ScriptedChatModel([], classifier=[verdict(False, PIVOT, usage=(30, 12))])
    usage = next(e for e in await _guarded_turn(model, "a recipe") if isinstance(e, Usage))
    assert usage.turn.calls == 1
    assert (usage.turn.input_tokens, usage.turn.output_tokens) == (30, 12)
    assert usage.turn.cost_usd is not None and usage.turn.cost_usd > 0


async def test_the_classifier_tokens_are_not_shown_as_the_assistants_answer() -> None:
    model = ScriptedChatModel([reply("the answer", 5, 5)], classifier=[verdict(True)])
    events = await _guarded_turn(model)
    streamed = "".join(e.text for e in events if isinstance(e, Token))
    assert streamed == "the answer"
    assert "in_scope" not in streamed


async def test_a_failing_classifier_does_not_stop_the_turn() -> None:
    model = ScriptedChatModel([reply("an answer", 5, 5)], classifier=[])  # its call raises
    events = await _guarded_turn(model)
    scope = next(e for e in events if isinstance(e, ScopeDecision))
    assert scope.in_scope is True
    assert any(isinstance(e, AssistantMessage) or isinstance(e, Token) for e in events)
    assert not any(isinstance(e, ErrorEvent) for e in events)


async def test_a_turn_without_a_guard_emits_no_scope_event() -> None:
    events = await _run("hi", FakeCredentialStore(), _factory(scripted("an answer")))
    assert "scope" not in [e.type for e in events]


# --- provider failures are explained ------------------------------------------------------------


class _OutOfCredits(Exception):
    status_code = 429
    body = {"error": {"code": "credit_balance_exhausted", "message": "raw text with sk-secret"}}


async def test_a_provider_without_credits_is_explained_not_generic(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def build(key: SecretStr) -> BaseChatModel:
        raise _OutOfCredits("You have no credits remaining")

    events = await _run("hi", FakeCredentialStore(), build)
    error = next(e for e in events if isinstance(e, ErrorEvent))
    assert "no credits" in error.message and "billing" in error.message
    assert "sk-secret" not in error.model_dump_json()
    assert error.correlation_id in caplog.text
    assert "Traceback" not in caplog.text  # a known failure needs no stack trace
    assert [e.type for e in events][-2:] == ["usage", "turn_finished"]


async def test_an_unknown_failure_is_still_generic_with_a_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def build(key: SecretStr) -> BaseChatModel:
        raise RuntimeError("boom")

    events = await _run("hi", FakeCredentialStore(), build)
    assert (
        next(e for e in events if isinstance(e, ErrorEvent)).message
        == "Something went wrong. Try again."
    )
    assert "RuntimeError" in caplog.text
