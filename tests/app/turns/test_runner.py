"""The turn runner: its event sequence, its failures and the life of the turn's keys."""

from __future__ import annotations

import asyncio
import io
import logging
from collections.abc import Callable, Sequence
from dataclasses import replace

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolCall
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import SecretStr

from agent.guardrails import ScopeGuard
from app.redaction import SecretRedactionFilter, redact
from app.turns import (
    AgentStarted,
    FailureReason,
    KeysUnavailableError,
    ScopePassed,
    ScopeRedirect,
    TextDelta,
    ToolCalls,
    ToolFinished,
    ToolResults,
    ToolStarted,
    TurnBegan,
    TurnDone,
    TurnEvent,
    TurnFailed,
    TurnKeys,
    TurnRequest,
    TurnServices,
    TurnSettings,
    TurnUsage,
    execute_turn,
)
from app.turns.runner import UserValues
from app.usage_meter import CallUsage
from tests.fakes import ScriptedChatModel, reply, verdict
from tools.credentials import CENSUS_KEY, PROVIDER_KEY

pytestmark = pytest.mark.anyio
MODEL_KEY = "sk-proj-" + "z9Y8x7W6v5" * 3  # pragma: allowlist secret
SERVICE_KEY = "census-key-" + "4c" * 12  # pragma: allowlist secret
KEYS = TurnKeys(openai=SecretStr(MODEL_KEY), census=SecretStr(SERVICE_KEY))
REQUEST = TurnRequest(thread_id="r1", question="Assess 1-1-1", message="Assess 1-1-1")


@tool
def lookup(cas_number: str) -> str:
    """Look up a CAS number."""
    return f"seen key: {PROVIDER_KEY.get() is not None}"


class Usages:
    """An in-memory usage store: the thread's calls so far."""

    def __init__(self) -> None:
        self.calls: list[CallUsage] = []

    async def record(self, calls: Sequence[CallUsage]) -> Sequence[CallUsage]:
        self.calls.extend(calls)
        return list(self.calls)


async def _no_values() -> UserValues:
    return {}, frozenset()


def _services(
    model: BaseChatModel,
    *,
    load_keys: Callable[[], TurnKeys] = lambda: KEYS,
    usages: Usages | None = None,
) -> TurnServices:
    return TurnServices(
        load_keys=load_keys,
        build_model=lambda key: model,
        checkpointer=InMemorySaver(),
        user_values=_no_values,
        record_usage=(usages or Usages()).record,
    )


async def _run(services: TurnServices, settings: TurnSettings | None = None) -> list[TurnEvent]:
    run = execute_turn(REQUEST, services, settings or TurnSettings(recursion_limit=10))
    return [event async for event in run]


def _kinds(events: Sequence[TurnEvent]) -> list[str]:
    return [type(event).__name__ for event in events]


def _released() -> bool:
    """No holder has a key and the logs no longer protect the turn's service key."""
    no_holder = PROVIDER_KEY.get() is None and CENSUS_KEY.get() is None
    return no_holder and SERVICE_KEY in redact(SERVICE_KEY)


def _call() -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[ToolCall(name="lookup", args={"cas_number": "1-1-1"}, id="c0")],
    )


async def test_a_tool_turn_yields_the_full_sequence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("agent.graph.get_all_tools", lambda: [lookup])
    events = await _run(_services(ScriptedChatModel([_call(), reply("All done", 5, 1)])))
    assert _kinds(events) == [
        "TurnBegan",
        "AgentStarted",
        "ToolStarted",
        "ToolCalls",
        "ToolFinished",
        "ToolResults",
        "TextDelta",
        "TextDelta",
        "TextDelta",
        "AssistantText",
        "TurnUsage",
        "TurnDone",
    ]
    finished = next(e for e in events if isinstance(e, ToolFinished))
    assert (finished.call_id, finished.tool_name, finished.failed) == ("c0", "lookup", False)
    assert finished.message.content == "seen key: True"  # the tool saw the turn's key
    assert "".join(e.text for e in events if isinstance(e, TextDelta)) == "All done"
    assert isinstance(events[3], ToolCalls) and isinstance(events[5], ToolResults)
    assert isinstance(events[2], ToolStarted) and events[2].call_id == "c0"
    assert _released()


async def test_usage_covers_the_turn_and_the_thread_so_far() -> None:
    usages = Usages()
    await _run(_services(ScriptedChatModel([reply("one", 10, 1)]), usages=usages))
    events = await _run(_services(ScriptedChatModel([reply("two", 20, 2)]), usages=usages))
    usage = next(e for e in events if isinstance(e, TurnUsage))
    assert [c.input_tokens for c in usage.turn] == [20]
    assert [c.input_tokens for c in usage.session] == [10, 20]


async def test_a_redirected_turn_ends_with_usage_and_done() -> None:
    guard = ScopeGuard(classifier_prompt="C", fallback_reply="F", history_window=4)
    model = ScriptedChatModel([], classifier=[verdict(False, "Back to chemicals.")])
    settings = TurnSettings(recursion_limit=10, scope_guard=guard)
    events = await _run(_services(model), settings)
    assert _kinds(events) == ["TurnBegan", "AgentStarted", "ScopeRedirect", "TurnUsage", "TurnDone"]
    assert events[2] == ScopeRedirect(("Back to chemicals.",))


async def test_an_in_scope_turn_passes_the_scope_check() -> None:
    guard = ScopeGuard(classifier_prompt="C", fallback_reply="F", history_window=4)
    model = ScriptedChatModel([reply("ok", 1, 1)], classifier=[verdict(True)])
    events = await _run(_services(model), TurnSettings(recursion_limit=10, scope_guard=guard))
    assert isinstance(events[2], ScopePassed)


async def test_a_failure_carries_a_reason_never_the_text(caplog: pytest.LogCaptureFixture) -> None:
    def build(key: SecretStr) -> BaseChatModel:
        raise RuntimeError(f"provider rejected {MODEL_KEY}")

    events = await _run(replace(_services(ScriptedChatModel([])), build_model=build))
    assert _kinds(events) == ["TurnBegan", "TurnFailed", "TurnUsage", "TurnDone"]
    failure = events[1]
    assert isinstance(failure, TurnFailed) and failure.reason == FailureReason.UNEXPECTED
    assert "rejected" not in repr(events) and MODEL_KEY not in repr(events)
    assert failure.correlation_id in caplog.text and "RuntimeError" in caplog.text
    assert _released()


async def test_a_failure_inside_the_graph_releases_the_keys() -> None:
    events = await _run(_services(ScriptedChatModel([])))  # out of script: the model raises
    assert _kinds(events)[-3:] == ["TurnFailed", "TurnUsage", "TurnDone"]
    assert _released()


async def test_missing_keys_fail_with_their_reason_and_log_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def no_key() -> TurnKeys:
        raise KeysUnavailableError(FailureReason.NO_KEY)

    with caplog.at_level(logging.INFO, logger="app.turns"):
        events = await _run(_services(ScriptedChatModel([]), load_keys=no_key))
    assert _kinds(events) == ["TurnBegan", "TurnFailed", "TurnUsage", "TurnDone"]
    assert isinstance(events[1], TurnFailed) and events[1].reason == FailureReason.NO_KEY
    assert not [r for r in caplog.records if r.name == "app.turns"]


async def test_a_failure_thrown_in_by_the_caller_is_the_turns_failure() -> None:
    run = execute_turn(REQUEST, _services(ScriptedChatModel([reply("x", 1, 1)])), TurnSettings(10))
    assert isinstance(await anext(run), TurnBegan)
    assert isinstance(await anext(run), AgentStarted)
    failure = await run.athrow(OSError("the database refused"))
    assert isinstance(failure, TurnFailed) and failure.reason == FailureReason.UNEXPECTED
    rest = [event async for event in run]
    assert _kinds(rest) == ["TurnUsage", "TurnDone"]
    assert _released()


async def test_a_usage_store_failure_still_ends_the_turn() -> None:
    async def refuse(calls: Sequence[CallUsage]) -> Sequence[CallUsage]:
        raise OSError("connection refused")

    events = await _run(
        replace(_services(ScriptedChatModel([reply("x", 1, 1)])), record_usage=refuse),
    )
    assert _kinds(events)[-2:] == ["TurnFailed", "TurnDone"]
    assert "refused" not in repr(events)


async def test_keys_are_released_when_the_turn_is_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()

    @tool
    async def slow(cas_number: str) -> str:
        """Never returns in time."""
        started.set()
        await asyncio.sleep(60)
        return "late"

    monkeypatch.setattr("agent.graph.get_all_tools", lambda: [slow])
    call = AIMessage(
        content="",
        tool_calls=[ToolCall(name="slow", args={"cas_number": "1"}, id="c")],
    )
    task = asyncio.create_task(_run(_services(ScriptedChatModel([call]))))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert _released()


async def test_closing_early_releases_the_keys() -> None:
    run = execute_turn(REQUEST, _services(ScriptedChatModel([reply("x", 1, 1)])), TurnSettings(10))
    assert isinstance(await anext(run), TurnBegan)
    assert isinstance(await anext(run), AgentStarted)
    assert PROVIDER_KEY.get() is not None
    await run.aclose()
    assert _released()


async def test_every_turn_ends_with_done() -> None:
    events = await _run(_services(ScriptedChatModel([reply("x", 1, 1)])))
    assert events[-1] == TurnDone()


async def test_a_failure_is_logged_while_the_service_keys_are_still_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @tool
    def leaky(cas_number: str) -> str:
        """Fails, echoing the Census key in its error."""
        raise RuntimeError(f"census refused key={SERVICE_KEY}")

    monkeypatch.setattr("agent.graph.get_all_tools", lambda: [leaky])
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(SecretRedactionFilter())
    turn_logger = logging.getLogger("app.turns")
    turn_logger.addHandler(handler)
    try:
        call = AIMessage(
            content="",
            tool_calls=[ToolCall(name="leaky", args={"cas_number": "1"}, id="c")],
        )
        events = await _run(_services(ScriptedChatModel([call])))
    finally:
        turn_logger.removeHandler(handler)
    assert _kinds(events)[-3:] == ["TurnFailed", "TurnUsage", "TurnDone"]
    assert "census refused" in stream.getvalue()  # the failure was logged with its traceback
    assert SERVICE_KEY not in stream.getvalue()
    assert _released()
