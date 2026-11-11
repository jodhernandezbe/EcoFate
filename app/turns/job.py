"""Run one queued turn in the background: the body of the worker's task (and of in-process runs).

``run_background_turn`` takes the turn (``queued -> running``; a turn that is no longer queued is
left alone, so a second delivery does nothing), publishes every event on the turn's stream,
records what each changes, and always ends the stream with ``usage`` and the end, then moves the
turn to its final status and releases the thread. While it runs, a supervisor renews the
heartbeat and the thread's lease, and enforces the soft time limit: the turn stops after its
current step (``time_limit``), and a step that has not returned halfway to the hard limit is
abandoned. A cancel request is checked after each graph step and stops the turn the same way
(``cancelled``); the step's results are kept and the turn can be resumed.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncGenerator, Sequence
from contextlib import aclosing
from dataclasses import dataclass

from app.task_queue import TurnJob
from app.telemetry import TurnSegment
from app.turns.codec import WorkerStarted
from app.turns.events import (
    AgentStarted,
    AssistantText,
    ScopePassed,
    ToolCalls,
    ToolResults,
    TurnDone,
    TurnEvent,
)
from app.turns.failures import FailureReason, StopRequestedError, new_correlation_id
from app.turns.recording import (
    BackgroundServices,
    BackgroundSettings,
    TurnRun,
    close_without_running,
    final_status,
    record,
)
from app.turns.runner import TurnRequest, TurnServices, execute_turn
from app.usage_meter import CallUsage
from storage.errors import DATABASE_ERRORS
from storage.turn_model import Turn, TurnTransitionError

logger = logging.getLogger("app.turns.background")
# The last event of a graph step: the agent's start, the scope check, a model step that asked for
# tools (its tools have not run yet), a whole batch of tool results, a final answer.
_STEP_ENDS = (AgentStarted, ScopePassed, ToolCalls, ToolResults, AssistantText)


async def run_background_turn(job: TurnJob, services: BackgroundServices) -> None:
    """Run the queued turn ``job`` names to its end; never raises for a failure of the turn."""
    turns = services.threads.turns
    queued = await turns.get(job.owner_id, job.turn_id)
    turn = await turns.start(job.owner_id, job.turn_id)
    if turn is None:
        logger.info("Turn %s is not queued; nothing to run", job.turn_id)
        return
    run = TurnRun(turn, services, queue_wait_seconds=_waited(queued, turn))
    try:
        await run.publish(WorkerStarted())
        await _run_supervised(run)
    except Exception:
        await _fail(run)
    finally:
        await _finish(run)


def _waited(queued: Turn | None, started: Turn) -> float | None:
    """Seconds the turn waited for a worker (from being queued to its first heartbeat)."""
    if queued is None or started.heartbeat_at is None:
        return None
    return max((started.heartbeat_at - queued.updated_at).total_seconds(), 0.0)


async def _run_supervised(run: TurnRun) -> None:
    """Run the turn while the supervisor watches it; a cancelled or abandoned turn still ends."""
    if run.turn.cancel_requested:  # cancelled while it waited: it does not start
        await close_without_running(run, FailureReason.CANCELLED)
        return
    pump = asyncio.create_task(_pump(run))
    supervisor = asyncio.create_task(_supervise(run, pump))
    try:
        await pump
    except asyncio.CancelledError:
        if not run.forced:
            raise
        await close_without_running(run, FailureReason.TIME_LIMIT)
    finally:
        supervisor.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await supervisor


async def _pump(run: TurnRun) -> None:
    """Consume the runner's events: record and publish each, stop it when asked."""
    request = await _turn_request(run)
    events = execute_turn(request, _turn_services(run), run.services.turn_settings)
    async with aclosing(events):
        event = await anext(events, None)
        while event is not None:
            event = await _step(events, event, run)


async def _step(
    events: AsyncGenerator[TurnEvent],
    event: TurnEvent,
    run: TurnRun,
) -> TurnEvent | None:
    """Record ``event``; a failure while the agent runs, or a stop request after a graph step,
    is thrown back into the runner, which reports it as the turn's failure (then usage)."""
    try:
        await record(event, run)
    except Exception as error:
        if not run.agent_running:
            raise
        return await _throw(events, error)
    stop = await _stop_wanted(event, run)
    if stop is not None:
        return await _throw(events, StopRequestedError(stop))
    return await anext(events, None)


async def _throw(events: AsyncGenerator[TurnEvent], error: Exception) -> TurnEvent | None:
    try:
        return await events.athrow(error)
    except StopAsyncIteration:
        return None


async def _stop_wanted(event: TurnEvent, run: TurnRun) -> FailureReason | None:
    """Why the turn should stop now: the soft time limit, or the user's cancel request (checked
    when a graph step has ended while the agent runs: never mid-batch or after a token, so the
    step's results are always recorded first)."""
    if not run.agent_running or not isinstance(event, _STEP_ENDS):
        return None
    if run.stop_reason is not None:
        return run.stop_reason
    turn = run.turn
    if await run.services.threads.turns.cancel_requested(turn.owner_id, turn.id):
        return FailureReason.CANCELLED
    return None


async def _turn_request(run: TurnRun) -> TurnRequest:
    """The runner's request: a resume continues the checkpoint, a new turn sends its input.

    Raises:
        ValueError: A new turn has no recorded input (the turn then fails).
    """
    turn = run.turn
    segment = TurnSegment(turn.id, turn.resume_count, run.queue_wait_seconds)
    common = _RequestScope(segment, str(turn.owner_id), turn.key.checkpoint_id)
    if turn.resume_count > 0:
        return common.request(turn.thread_id, await _last_question(run), "", resume=True)
    if turn.planned is None:
        raise ValueError("a new turn has no recorded input")
    planned = turn.planned
    return common.request(turn.thread_id, planned.question, planned.message, note=planned.note)


@dataclass(frozen=True)
class _RequestScope:
    """What every request of one turn segment shares: its span segment, owner and checkpoint."""

    segment: TurnSegment
    user_id: str
    checkpoint_id: str

    def request(
        self,
        thread_id: str,
        question: str,
        message: str,
        *,
        note: str = "",
        resume: bool = False,
    ) -> TurnRequest:
        return TurnRequest(
            thread_id,
            question,
            message,
            note,
            resume=resume,
            segment=self.segment,
            user_id=self.user_id,
            checkpoint_id=self.checkpoint_id,
        )


async def _last_question(run: TurnRun) -> str:
    """The thread's last user message, recorded on the span of a resume."""
    messages = await run.services.threads.messages(run.key)
    return next((m.text for m in reversed(messages) if m.type == "human"), "")


def _turn_services(run: TurnRun) -> TurnServices:
    """The runner's collaborators for this turn: the owner's keys and the thread's store."""
    services, key, turn = run.services, run.key, run.turn
    threads = services.threads

    async def record_usage(calls: Sequence[CallUsage]) -> Sequence[CallUsage]:
        await threads.add_usage(key, calls, turn.id)
        return await threads.session_calls(key)

    return TurnServices(
        load_keys=lambda: services.load_keys(turn.owner_id),
        build_model=services.build_model,
        checkpointer=threads.checkpointer,
        user_values=lambda: threads.answers(key),
        record_usage=record_usage,
    )


# --- supervision --------------------------------------------------------------------------------


async def _supervise(run: TurnRun, pump: asyncio.Task[None]) -> None:
    """Renew the heartbeat and the lease; ask the turn to stop at the soft limit and abandon a
    step that has not returned halfway to the hard limit."""
    timing, loop = run.services.settings, asyncio.get_running_loop()
    started = loop.time()
    while not pump.done():
        await asyncio.sleep(_tick(timing, loop.time() - started))
        await _beat(run)
        elapsed = loop.time() - started
        if elapsed >= timing.soft_limit_seconds:
            run.stop_reason = FailureReason.TIME_LIMIT
        if elapsed >= _abandon_after(timing):
            run.forced = True
            pump.cancel()
            return


def _abandon_after(timing: BackgroundSettings) -> float:
    return (timing.soft_limit_seconds + timing.hard_limit_seconds) / 2


def _tick(timing: BackgroundSettings, elapsed: float) -> float:
    """Seconds until the next heartbeat or limit, whichever comes first."""
    deadlines = (timing.soft_limit_seconds, _abandon_after(timing))
    ahead = [deadline - elapsed for deadline in deadlines if deadline > elapsed]
    return max(min([timing.heartbeat_seconds, *ahead]), 0.0)


async def _beat(run: TurnRun) -> None:
    """Record the heartbeat and renew the thread's lease; a database hiccup is only logged."""
    turn, threads = run.turn, run.services.threads
    try:
        await threads.turns.heartbeat(turn.owner_id, turn.id)
        await threads.extend(run.key)
    except DATABASE_ERRORS as error:
        logger.warning("Heartbeat of turn %s failed: %s", turn.id, type(error).__name__)


# --- the end ------------------------------------------------------------------------------------


async def _fail(run: TurnRun) -> None:
    """A failure outside the runner (storage, the stream): logged under an id, and reported on
    the stream when it can be (the end follows in ``_finish``)."""
    correlation_id = new_correlation_id()
    logger.exception("Background turn %s failed (%s)", run.turn.id, correlation_id)
    if run.stopped is not None:
        return
    try:
        await run.publish(run.stop(FailureReason.UNEXPECTED, correlation_id))
    except Exception as error:
        logger.warning(
            "Could not report the failure of turn %s: %s",
            run.turn.id,
            type(error).__name__,
        )


async def _finish(run: TurnRun) -> None:
    """Store the final status, release the thread, then end the stream (each step only logged
    when it cannot be done: a recovery sweep may have moved the turn already)."""
    turn, threads = run.turn, run.services.threads
    target, reason = final_status(run)
    try:
        await threads.turns.move(turn.owner_id, turn.id, target, reason)
    except (TurnTransitionError, *DATABASE_ERRORS) as error:
        logger.warning("Turn %s could not move to %s: %s", turn.id, target, type(error).__name__)
    try:
        await threads.release(run.key)
    except DATABASE_ERRORS as error:
        logger.warning("Thread of turn %s not released: %s", turn.id, type(error).__name__)
    try:
        await run.publish(TurnDone())
    except Exception as error:
        logger.warning("Could not end the stream of turn %s: %s", turn.id, type(error).__name__)
