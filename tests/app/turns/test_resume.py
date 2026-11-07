"""Resuming an interrupted turn from its checkpoint, and abandoning one for a new message."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolCall, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import PrivateAttr, SecretStr

from app.turns import (
    FailureReason,
    TextDelta,
    ToolFinished,
    TurnEvent,
    TurnFailed,
    TurnKeys,
    TurnRequest,
    TurnServices,
    TurnSettings,
    TurnUsage,
    execute_turn,
    pending_steps,
)
from app.turns.history import NOT_RUN, unanswered_calls
from app.turns.runner import UserValues
from app.usage_meter import CallUsage
from tests.fakes import ScriptedChatModel, reply

pytestmark = pytest.mark.anyio
THREAD = "resume-thread"
KEYS = TurnKeys(openai=SecretStr("sk-test-" + "r" * 24))  # pragma: allowlist secret
FIRST = TurnRequest(thread_id=THREAD, question="Assess 1-1-1", message="Assess 1-1-1")
RESUME = TurnRequest(thread_id=THREAD, question="Assess 1-1-1", message="", resume=True)
RUNS: list[str] = []
SEEN_VALUES: list[object] = []


@tool
def lookup(cas_number: str) -> str:
    """Look up a CAS number."""
    RUNS.append(cas_number)
    return f"found {cas_number}"


@tool
def read_values(cas_number: str, config: RunnableConfig) -> str:
    """Report the values the user supplied for this run."""
    SEEN_VALUES.append(config.get("configurable", {}).get("user_values"))
    return "read"


class QuotaError(Exception):
    """Stands in for the provider's 429 ``insufficient_quota`` (status and code only)."""

    status_code = 429
    body: Mapping[str, object] = {"error": {"code": "insufficient_quota"}}  # noqa: RUF012 - read-only stand-in


class FlakyModel(ScriptedChatModel):
    """A scripted model that raises ``QuotaError`` once, on the given call (0-based)."""

    _fail_at: set[int] = PrivateAttr(default_factory=set[int])

    def __init__(self, script: Sequence[AIMessage], fail_at: int) -> None:
        super().__init__(script)
        self._fail_at = {fail_at}

    def _next(self, messages: list[BaseMessage] | None = None) -> AIMessage:
        if self._cursor in self._fail_at:
            self._fail_at.discard(self._cursor)
            raise QuotaError("raw provider text")
        return super()._next(messages)


class Usages:
    def __init__(self) -> None:
        self.calls: list[CallUsage] = []

    async def record(self, calls: Sequence[CallUsage]) -> Sequence[CallUsage]:
        self.calls.extend(calls)
        return list(self.calls)


@pytest.fixture(autouse=True)
def _tools(monkeypatch: pytest.MonkeyPatch) -> None:
    RUNS.clear()
    SEEN_VALUES.clear()
    monkeypatch.setattr("agent.graph.get_all_tools", lambda: [lookup, read_values])


def _services(model: ScriptedChatModel, saver: InMemorySaver, usages: Usages) -> TurnServices:
    async def values() -> UserValues:
        return {"rfc": 0.5}, frozenset()

    return TurnServices(
        load_keys=lambda: KEYS,
        build_model=lambda key: model,
        checkpointer=saver,
        user_values=values,
        record_usage=usages.record,
    )


def _calls(*ids: str, name: str = "lookup") -> AIMessage:
    calls = [ToolCall(name=name, args={"cas_number": f"cas-{i}"}, id=i) for i in ids]
    return AIMessage(content="", tool_calls=calls)


async def _run(
    request: TurnRequest,
    services: TurnServices,
    recursion_limit: int = 20,
) -> list[TurnEvent]:
    run = execute_turn(request, services, TurnSettings(recursion_limit=recursion_limit))
    return [event async for event in run]


def _failure(events: Sequence[TurnEvent]) -> TurnFailed | None:
    return next((e for e in events if isinstance(e, TurnFailed)), None)


def _text(events: Sequence[TurnEvent]) -> str:
    return "".join(e.text for e in events if isinstance(e, TextDelta))


async def test_resume_after_credits_continues_without_repeating_the_message_or_tools() -> None:
    model = FlakyModel([_calls("c0", "c1"), reply("All done", 3, 1)], fail_at=1)
    saver, usages = InMemorySaver(), Usages()
    services = _services(model, saver, usages)

    first = await _run(FIRST, services)
    failure = _failure(first)
    assert failure is not None and failure.reason == FailureReason.OUT_OF_CREDITS
    assert sorted(RUNS) == ["cas-c0", "cas-c1"]  # parallel tool calls: any order
    assert await pending_steps(THREAD, services, TurnSettings(recursion_limit=20)) == ("model",)

    resumed = await _run(RESUME, services)
    assert _failure(resumed) is None
    assert _text(resumed) == "All done"
    assert sorted(RUNS) == ["cas-c0", "cas-c1"]  # the finished tools did not run again
    assert not [e for e in resumed if isinstance(e, ToolFinished)]
    history = model.inputs[-1]
    assert [m.content for m in history if isinstance(m, HumanMessage)] == ["Assess 1-1-1"]
    assert {m.tool_call_id for m in history if isinstance(m, ToolMessage)} == {"c0", "c1"}
    assert await pending_steps(THREAD, services, TurnSettings(recursion_limit=20)) == ()


async def test_a_resumed_segment_reports_its_own_model_calls() -> None:
    model = FlakyModel([_calls("c0"), reply("All done", 3, 1)], fail_at=1)
    saver, usages = InMemorySaver(), Usages()
    services = _services(model, saver, usages)
    await _run(FIRST, services)
    resumed = await _run(RESUME, services)
    usage = next(e for e in resumed if isinstance(e, TurnUsage))
    assert [c.input_tokens for c in usage.turn] == [3]
    assert len(usage.session) == len(usages.calls)


async def test_the_step_limit_interrupts_and_a_resume_gets_a_fresh_budget() -> None:
    script = [_calls("a"), _calls("b"), _calls("c"), reply("Finished", 1, 1)]
    model = ScriptedChatModel(script)
    services = _services(model, InMemorySaver(), Usages())

    first = await _run(FIRST, services, recursion_limit=3)
    failure = _failure(first)
    assert failure is not None and failure.reason == FailureReason.STEP_LIMIT
    assert await pending_steps(THREAD, services, TurnSettings(recursion_limit=3))

    second = await _run(RESUME, services, recursion_limit=6)
    assert _failure(second) is None and _text(second) == "Finished"
    assert RUNS == ["cas-a", "cas-b", "cas-c"]  # each tool ran exactly once across both runs


async def test_a_resumed_run_gets_the_users_values_again() -> None:
    model = FlakyModel([_calls("v0", name="read_values"), reply("ok", 1, 1)], fail_at=0)
    services = _services(model, InMemorySaver(), Usages())
    assert _failure(await _run(FIRST, services)) is not None
    await _run(RESUME, services)
    assert SEEN_VALUES == [{"supplied": {"rfc": 0.5}, "declined": []}]


async def test_a_new_message_closes_the_abandoned_turns_tool_calls_first() -> None:
    script = [_calls("x1", "x2"), reply("Fresh answer", 1, 1)]
    model = ScriptedChatModel(script)
    saver = InMemorySaver()
    services = _services(model, saver, Usages())
    # A step limit of 1 stops the run after the model asked for two tools, before they ran.
    failure = _failure(await _run(FIRST, services, recursion_limit=1))
    assert failure is not None and failure.reason == FailureReason.STEP_LIMIT
    assert RUNS == []

    follow_up = TurnRequest(thread_id=THREAD, question="Next", message="Next")
    events = await _run(follow_up, services)
    assert _failure(events) is None and _text(events) == "Fresh answer"
    history = model.inputs[-1]
    assert unanswered_calls(history) == []
    closed = [m for m in history if isinstance(m, ToolMessage)]
    assert [(m.tool_call_id, m.status, m.content) for m in closed] == [
        ("x1", "error", NOT_RUN),
        ("x2", "error", NOT_RUN),
    ]
    assert RUNS == []  # the abandoned calls were never run
    assert [m.content for m in history if isinstance(m, HumanMessage)] == ["Assess 1-1-1", "Next"]


async def test_a_history_with_every_call_answered_is_left_as_it_is() -> None:
    model = ScriptedChatModel([_calls("y1"), reply("one", 1, 1), reply("two", 1, 1)])
    services = _services(model, InMemorySaver(), Usages())
    await _run(FIRST, services)
    await _run(TurnRequest(thread_id=THREAD, question="Again", message="Again"), services)
    tool_results = [m for m in model.inputs[-1] if isinstance(m, ToolMessage)]
    assert [m.tool_call_id for m in tool_results] == ["y1"]


def test_unanswered_calls_reads_only_the_last_assistant_message() -> None:
    history: list[Any] = [
        HumanMessage("q"),
        _calls("old"),
        HumanMessage("q2"),
        _calls("n1", "n2"),
        ToolMessage("r", tool_call_id="n1"),
    ]
    assert unanswered_calls(history) == [("n2", "lookup")]
    assert unanswered_calls([HumanMessage("only")]) == []
