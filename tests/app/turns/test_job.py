"""A background turn, run in-process: its stream, its records, its stops and its keys."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Generator, Iterator
from contextlib import contextmanager
from dataclasses import replace
from typing import Any
from uuid import UUID

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolCall
from langchain_core.tools import StructuredTool
from pydantic import SecretStr

from app.task_queue import TurnJob
from app.turns.bus import MemoryBus, turn_stream
from app.turns.codec import RelayedEvent, TurnStopped, decode
from app.turns.events import TurnUsage
from app.turns.failures import FailureReason
from app.turns.job import run_background_turn
from app.turns.keys import load_turn_keys
from app.turns.recording import BackgroundServices, BackgroundSettings
from app.turns.runner import TurnSettings
from commons.scoped_secret import ScopedSecret
from storage.keys import ThreadKey
from storage.turn_model import PlannedInput, Turn, TurnStatus
from tests.fakes import OWNER_ID, InMemoryThreadStore, KeyBench, ScriptedChatModel, reply
from tools.credentials import HOLDERS

pytestmark = pytest.mark.anyio
KEY_VALUE = "sk-proj-" + "j0B1q2U3e4" * 3  # pragma: allowlist secret
THREAD = ThreadKey(OWNER_ID, "bg-thread")
TIMING = BackgroundSettings(
    heartbeat_seconds=0.02,
    soft_limit_seconds=30.0,
    hard_limit_seconds=60.0,
    event_ttl_seconds=60,
    max_resumes=3,
)


class Bench:
    """A store, a stream, a key vault and the services of one in-process worker."""

    def __init__(self, model: BaseChatModel, timing: BackgroundSettings = TIMING) -> None:
        self.store = InMemoryThreadStore()
        self.bus = MemoryBus()
        self.keys = KeyBench()
        self.models_built = 0
        self.refunds: list[str] = []
        self.model = model
        self.services = BackgroundServices(
            threads=self.store,
            bus=self.bus,
            load_keys=lambda user: load_turn_keys(self.keys.vault, self.keys.operator, user),
            build_model=self._build,
            refund=self._refund,
            turn_settings=TurnSettings(recursion_limit=10, model_name="m"),
            settings=timing,
        )

    def _build(self, key: SecretStr) -> BaseChatModel:
        assert key.get_secret_value() == KEY_VALUE
        self.models_built += 1
        return self.model

    async def _refund(self, user_id: UUID, turn_id: str) -> bool:
        self.refunds.append(turn_id)
        return True

    async def queue(self, *, counted: bool = False) -> Turn:
        assert await self.store.claim(THREAD)
        turn = await self.store.turns.begin(THREAD, PlannedInput("Assess", "Assess", "", counted))
        assert turn is not None
        return turn

    async def run(self, turn: Turn) -> list[RelayedEvent]:
        await run_background_turn(TurnJob(turn.id, turn.owner_id), self.services)
        stream = turn_stream(turn.id, turn.resume_count)
        events = [decode(record) for _, record in await self.bus.read(stream, None, 0.01)]
        assert None not in events
        return [event for event in events if event is not None]

    async def turn(self, turn_id: str) -> Turn:
        found = await self.store.turns.get(OWNER_ID, turn_id)
        assert found is not None
        return found


def _kinds(events: list[RelayedEvent]) -> list[str]:
    return [type(event).__name__ for event in events]


def _stopped(events: list[RelayedEvent]) -> TurnStopped:
    found = [event for event in events if isinstance(event, TurnStopped)]
    assert len(found) == 1, _kinds(events)
    return found[0]


def _call() -> AIMessage:
    return AIMessage("", tool_calls=[ToolCall(name="slow_lookup", args={"cas": "1-1-1"}, id="c0")])


@pytest.fixture
def tool_body(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[Callable[[], Any]]]:
    """The body of the one synthetic tool (a test sets what it does); returns a result."""
    actions: list[Callable[[], Any]] = []

    async def slow_lookup(cas: str) -> str:
        for action in actions:
            result = action()
            if asyncio.iscoroutine(result):
                await result
        return '{"found": true}'

    tool = StructuredTool.from_function(coroutine=slow_lookup, name="slow_lookup", description="x")
    monkeypatch.setattr("agent.graph.get_all_tools", lambda: [tool])
    yield actions


@pytest.fixture
def holders(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, int]]:
    """How many times each key holder is currently providing a key (0 when released)."""
    active = dict.fromkeys(HOLDERS, 0)
    for name, holder in HOLDERS.items():
        original = holder.provide

        @contextmanager
        def counted(secret: SecretStr, *, _n: str = name, _o: Any = original) -> Generator[None]:
            active[_n] += 1
            try:
                with _o(secret):
                    yield
            finally:
                active[_n] -= 1

        monkeypatch.setattr(holder, "provide", counted)
    yield active


async def test_a_turn_streams_its_events_completes_and_frees_the_thread(
    holders: dict[str, int],
) -> None:
    bench = Bench(ScriptedChatModel([reply("All done.", 5, 3)]))
    bench.keys.give(KEY_VALUE)
    turn = await bench.queue()
    events = await bench.run(turn)
    assert _kinds(events)[:3] == ["WorkerStarted", "TurnBegan", "AgentStarted"]
    assert _kinds(events)[-2:] == ["TurnUsage", "TurnDone"]
    assert "TextDelta" in _kinds(events)
    finished = await bench.turn(turn.id)
    assert (finished.status, finished.reason) == (TurnStatus.COMPLETED, None)
    assert not await bench.store.running(THREAD)
    assert holders == dict.fromkeys(HOLDERS, 0)


async def test_records_are_numbered_after_the_queued_record() -> None:
    bench = Bench(ScriptedChatModel([reply("ok", 1, 1)]))
    bench.keys.give(KEY_VALUE)
    turn = await bench.queue()
    await bench.run(turn)
    seqs = [seq for seq, _ in await bench.bus.read(turn_stream(turn.id, 0), None, 0.01)]
    assert seqs == list(range(1, len(seqs) + 1))


async def test_tool_calls_and_results_are_stored_for_the_workspace(
    tool_body: list[Callable[[], Any]],
) -> None:
    bench = Bench(ScriptedChatModel([_call(), reply("Found it.", 2, 2)]))
    bench.keys.give(KEY_VALUE)
    turn = await bench.queue()
    events = await bench.run(turn)
    for kind in ("ToolStarted", "ToolCalls", "ToolFinished", "ToolResults"):
        assert kind in _kinds(events)
    stored = await bench.store.tool_messages(THREAD)
    assert [m.type for m in stored] == ["ai", "tool"]


async def test_a_turn_that_is_no_longer_queued_is_left_alone() -> None:
    bench = Bench(ScriptedChatModel([reply("ok", 1, 1)]))
    bench.keys.give(KEY_VALUE)
    turn = await bench.queue()
    await bench.run(turn)
    again = await bench.run(turn)  # a second delivery of the same task
    assert _kinds(again) == _kinds(await bench.run(turn))
    assert bench.models_built == 1


async def test_a_missing_key_fails_the_turn_without_building_a_model(
    holders: dict[str, int],
) -> None:
    bench = Bench(ScriptedChatModel([reply("never", 1, 1)]))
    turn = await bench.queue(counted=True)
    events = await bench.run(turn)
    stopped = _stopped(events)
    assert (stopped.reason, stopped.resumable) == (FailureReason.NO_KEY, False)
    assert _kinds(events)[-2:] == ["TurnUsage", "TurnDone"]
    assert bench.models_built == 0
    assert (await bench.turn(turn.id)).status is TurnStatus.FAILED
    assert bench.refunds == [turn.id]  # counted, stopped before the model, not resumable
    assert holders == dict.fromkeys(HOLDERS, 0)


async def test_an_uncounted_turn_is_not_refunded() -> None:
    bench = Bench(ScriptedChatModel([]))
    await bench.run(await bench.queue(counted=False))
    assert bench.refunds == []


async def test_an_unexpected_failure_fails_the_turn_and_logs_no_key(
    holders: dict[str, int],
    caplog: pytest.LogCaptureFixture,
) -> None:
    bench = Bench(ScriptedChatModel([]))  # the first model call runs out of script
    bench.keys.give(KEY_VALUE)
    turn = await bench.queue(counted=True)
    with caplog.at_level(logging.DEBUG):
        events = await bench.run(turn)
    stopped = _stopped(events)
    assert (stopped.reason, stopped.resumable) == (FailureReason.UNEXPECTED, False)
    assert (await bench.turn(turn.id)).status is TurnStatus.FAILED
    assert holders == dict.fromkeys(HOLDERS, 0)
    assert KEY_VALUE not in caplog.text
    assert bench.refunds == [turn.id]  # the model was called but recorded no usage


async def test_cancel_during_a_tool_keeps_its_result_and_makes_no_further_model_call(
    tool_body: list[Callable[[], Any]],
    holders: dict[str, int],
) -> None:
    model = ScriptedChatModel([_call(), reply("never sent", 1, 1)])
    bench = Bench(model)
    bench.keys.give(KEY_VALUE)
    turn = await bench.queue()
    tool_body.append(lambda: bench.store.turns.request_cancel(OWNER_ID, turn.id))
    events = await bench.run(turn)
    stopped = _stopped(events)
    assert (stopped.reason, stopped.resumable) == (FailureReason.CANCELLED, True)
    assert model.calls == 1
    assert [m.type for m in await bench.store.tool_messages(THREAD)] == ["ai", "tool"]
    assert _kinds(events)[-3:] == ["TurnStopped", "TurnUsage", "TurnDone"]
    finished = await bench.turn(turn.id)
    assert (finished.status, finished.reason) == (TurnStatus.INTERRUPTED, "cancelled")
    assert holders == dict.fromkeys(HOLDERS, 0)


async def test_a_turn_cancelled_while_queued_never_starts() -> None:
    bench = Bench(ScriptedChatModel([reply("never", 1, 1)]))
    bench.keys.give(KEY_VALUE)
    turn = await bench.queue()
    assert await bench.store.turns.request_cancel(OWNER_ID, turn.id)
    events = await bench.run(turn)
    assert _stopped(events).reason is FailureReason.CANCELLED
    assert _kinds(events)[-2:] == ["TurnUsage", "TurnDone"]
    assert bench.models_built == 0
    assert (await bench.turn(turn.id)).reason == "cancelled"


async def test_the_soft_time_limit_stops_the_turn_after_its_step(
    tool_body: list[Callable[[], Any]],
) -> None:
    timing = replace(TIMING, soft_limit_seconds=0.05, hard_limit_seconds=30.0)
    model = ScriptedChatModel([_call(), reply("never sent", 1, 1)])
    bench = Bench(model, timing)
    bench.keys.give(KEY_VALUE)
    tool_body.append(lambda: asyncio.sleep(0.2))
    turn = await bench.queue()
    events = await bench.run(turn)
    assert _stopped(events).reason is FailureReason.TIME_LIMIT
    assert _kinds(events)[-3:] == ["TurnStopped", "TurnUsage", "TurnDone"]
    assert model.calls == 1
    finished = await bench.turn(turn.id)
    assert (finished.status, finished.reason) == (TurnStatus.INTERRUPTED, "time_limit")


async def test_a_step_that_does_not_return_is_abandoned_before_the_hard_limit(
    tool_body: list[Callable[[], Any]],
    holders: dict[str, int],
) -> None:
    timing = replace(TIMING, soft_limit_seconds=0.05, hard_limit_seconds=0.25)
    bench = Bench(ScriptedChatModel([_call(), reply("never", 1, 1)]), timing)
    bench.keys.give(KEY_VALUE)
    tool_body.append(lambda: asyncio.sleep(5))
    turn = await bench.queue()
    events = await asyncio.wait_for(bench.run(turn), 3)
    assert _stopped(events).reason is FailureReason.TIME_LIMIT
    assert _kinds(events)[-2:] == ["TurnUsage", "TurnDone"]
    assert (await bench.turn(turn.id)).reason == "time_limit"
    assert not await bench.store.running(THREAD)
    assert holders == dict.fromkeys(HOLDERS, 0)


async def test_the_heartbeat_and_the_lease_are_renewed_while_a_step_runs(
    tool_body: list[Callable[[], Any]],
) -> None:
    bench = Bench(ScriptedChatModel([_call(), reply("done", 1, 1)]))
    bench.keys.give(KEY_VALUE)
    turn = await bench.queue()
    beats: list[object] = []

    async def watch() -> None:
        await asyncio.sleep(0.1)
        current = await bench.store.turns.get(OWNER_ID, turn.id)
        beats.append(current.heartbeat_at if current else None)

    tool_body.append(watch)
    await bench.run(turn)
    started = (await bench.turn(turn.id)).started_at
    assert beats and beats[0] is not None and started is not None
    assert beats[0] > started  # pyright: ignore[reportOperatorIssue]


async def test_a_resumed_turn_continues_from_its_checkpoint_on_its_own_stream(
    tool_body: list[Callable[[], Any]],
) -> None:
    model = ScriptedChatModel([_call(), reply("Resumed.", 1, 1)])
    bench = Bench(model)
    bench.keys.give(KEY_VALUE)
    turn = await bench.queue()
    tool_body.append(lambda: bench.store.turns.request_cancel(OWNER_ID, turn.id))
    first = await bench.run(turn)
    tool_body.clear()
    assert await bench.store.claim(THREAD)
    resumed = await bench.store.turns.resume(OWNER_ID, turn.id, 3)
    assert resumed is not None and resumed.resume_count == 1
    events = await bench.run(resumed)
    assert "TextDelta" in _kinds(events) and "ToolStarted" not in _kinds(events)
    assert model.calls == 2  # the tool did not run again
    assert (await bench.turn(turn.id)).status is TurnStatus.COMPLETED
    assert len(await bench.bus.read(turn_stream(turn.id, 0), None, 0.01)) == len(first)


async def test_usage_reports_the_turns_calls() -> None:
    bench = Bench(ScriptedChatModel([reply("ok", 7, 3)]))
    bench.keys.give(KEY_VALUE)
    turn = await bench.queue()
    events = await bench.run(turn)
    usage = next(event for event in events if isinstance(event, TurnUsage))
    assert [(c.input_tokens, c.output_tokens) for c in usage.turn] == [(7, 3)]
    assert await bench.store.turn_calls(THREAD, turn.id) == list(usage.turn)


def test_scoped_secret_is_what_the_holders_are() -> None:
    assert all(isinstance(holder, ScopedSecret) for holder in HOLDERS.values())
