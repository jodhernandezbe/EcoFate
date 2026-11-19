"""Tests for scripts/load/run.py: server time, timers, shared budget and session events."""

from __future__ import annotations

import asyncio
import time

import pytest

from scripts.load.report import Measurements
from scripts.load.run import Session, Shared, TurnTimer, parse, server_seconds


def _shared(budget: float | None = None, deadline_in: float = 100.0) -> Shared:
    return Shared(Measurements(), time.monotonic() + deadline_in, budget)


def _session(shared: Shared) -> Session:
    return Session(object(), shared)  # pyright: ignore[reportArgumentType]  # unused here


def test_server_seconds_reads_stream_id() -> None:
    assert server_seconds("1700000000123-0") == pytest.approx(1700000000.123)


@pytest.mark.parametrize("event_id", [None, "", "garbage", "-1"])
def test_server_seconds_falls_back_to_clock(event_id: str | None) -> None:
    before = time.time()
    assert server_seconds(event_id) >= before


def test_turn_timer_chat_queue_wait_once() -> None:
    measured = Measurements()
    timer = TurnTimer("assess", sent=time.monotonic() - 2)
    timer.see({"type": "turn_status", "phase": "queued"}, measured)
    assert measured.durations == {}
    timer.see({"type": "turn_status", "phase": "running"}, measured)
    timer.see({"type": "turn_status", "phase": "running"}, measured)
    assert len(measured.durations["chat_queue_wait"]) == 1
    assert measured.durations["chat_queue_wait"][0] >= 2


def test_turn_timer_first_answer_once_per_kind() -> None:
    measured = Measurements()
    timer = TurnTimer("question")
    timer.see({"type": "token"}, measured)
    timer.see({"type": "assistant_message"}, measured)
    assert len(measured.durations["first_answer_question"]) == 1


def test_turn_timer_sets_interrupted() -> None:
    timer = TurnTimer("assess")
    timer.see({"type": "turn_interrupted"}, Measurements())
    assert timer.interrupted


def test_may_start_false_after_deadline() -> None:
    assert not _shared(deadline_in=-1).may_start()
    assert _shared().may_start()


def test_may_start_false_when_budget_spent() -> None:
    shared = _shared(budget=1.0)
    assert shared.may_start()
    shared.costs["t"] = 1.0
    assert not shared.may_start()
    assert shared.measured.budget_reached


def test_record_usage_keeps_max_per_thread() -> None:
    shared = _shared()
    shared.record_usage("t", {"session": {"cost_usd": 0.5}})
    shared.record_usage("t", {"session": {"cost_usd": 0.2}})
    shared.record_usage("u", {"session": {"cost_usd": 0.1}})
    assert shared.costs == {"t": 0.5, "u": 0.1}


def test_record_usage_ignores_bool_and_missing() -> None:
    shared = _shared()
    shared.record_usage("t", {"session": {"cost_usd": True}})
    shared.record_usage("t", {"session": {}})
    shared.record_usage("t", {})
    assert shared.costs == {}


def test_job_events_time_queue_wait_and_duration() -> None:
    session = _session(_shared())
    session.on_thread_event({"kind": "job.queued", "job_id": "j"}, "1700000000000-0")
    session.on_thread_event({"kind": "job.running", "job_id": "j"}, "1700000002500-0")
    session.on_thread_event(
        {"kind": "job.ended", "job_id": "j", "status": "done"},
        "1700000012500-0",
    )
    measured = session.shared.measured
    assert measured.jobs_queued == 1
    assert measured.durations["tools_queue_wait"] == [pytest.approx(2.5)]
    assert measured.durations["job_duration"] == [pytest.approx(10.0)]
    assert measured.jobs_ended == {"done": 1}
    assert not session.done.is_set()


def test_job_running_without_queued_is_ignored() -> None:
    session = _session(_shared())
    session.on_thread_event({"kind": "job.running", "job_id": "j"}, "1700000000000-0")
    assert session.shared.measured.durations == {}


def test_cancelled_job_sets_done() -> None:
    session = _session(_shared())
    session.on_thread_event({"kind": "job.ended", "job_id": "j", "status": "cancelled"}, "5-0")
    assert session.done.is_set()


def test_manual_turn_events_are_ignored() -> None:
    session = _session(_shared())
    session.on_thread_event({"kind": "turn.started", "turn_id": "x"}, "5-0")
    session.on_thread_event({"kind": "turn.ended"}, "6-0")
    assert not session.done.is_set()
    assert session.shared.measured.follow_ups_started == 0


@pytest.mark.anyio
async def test_follow_up_events_record_wait_and_duration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_usage(self: Session, turn_id: str) -> None:
        return None

    monkeypatch.setattr(Session, "_follow_up_usage", no_usage)
    session = _session(_shared())
    session.on_thread_event({"kind": "job.ended", "job_id": "j", "status": "done"}, "1000-0")
    session.on_thread_event({"kind": "turn.started", "automatic": True, "turn_id": "t"}, "3000-0")
    session.on_thread_event({"kind": "turn.ended", "automatic": True}, "8000-0")
    await asyncio.sleep(0)
    measured = session.shared.measured
    assert measured.follow_ups_started == 1
    assert measured.durations["follow_up_wait"] == [pytest.approx(2.0)]
    assert measured.durations["follow_up_duration"] == [pytest.approx(5.0)]
    assert session.done.is_set()


@pytest.mark.parametrize("users", ["0", "201", "-3"])
def test_parse_users_out_of_range(users: str) -> None:
    with pytest.raises(SystemExit):
        parse(["--users", users])


def test_parse_users_in_range() -> None:
    assert parse(["--users", "10"]).users == 10


def test_a_real_key_goes_only_to_loopback_or_https() -> None:
    from scripts.load.run import safe_for_key

    assert safe_for_key("http://127.0.0.1:8000")
    assert safe_for_key("https://staging.example.com")
    assert not safe_for_key("http://203.0.113.9:8000")
