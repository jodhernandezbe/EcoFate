"""The durable side of a background turn: what each event changes in storage, then its record.

The worker that runs a turn is the only writer of its state: tool calls and results kept for the
workspace, the pending confirmation, the stop (with whether it can be resumed), the quota refund,
and the final status. Every event is then published on the turn's stream, numbered from 1 (the
API wrote ``seq`` 0, the queued record, before it enqueued the turn). The end is published last,
after the turn's final status is stored and its thread released, so a reader that sees the end
can start the next turn at once.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from pydantic import SecretStr

from app.turns.bus import TurnEventBus, turn_stream
from app.turns.codec import RelayedEvent, TurnStopped, encode, is_last
from app.turns.events import (
    AgentStarted,
    ConfirmationNeeded,
    ToolCalls,
    ToolResults,
    TurnDone,
    TurnEvent,
    TurnFailed,
    TurnUsage,
)
from app.turns.failures import FailureReason, new_correlation_id, resumable
from app.turns.keys import TurnKeys
from app.turns.runner import TurnSettings
from app.usage_meter import CallUsage
from config.worker import WorkerSettings
from storage.errors import DATABASE_ERRORS
from storage.keys import ThreadKey
from storage.turn_model import Turn, TurnStatus
from tools.schemas import ConfirmationRequest

logger = logging.getLogger("app.turns.background")
QUEUED_SEQ = 0  # the API's queued record; the worker's records follow it


class BackgroundTurns(Protocol):
    """The turn records a worker reads and moves (``storage.turns.TurnRepository``)."""

    async def get(self, owner_id: UUID, turn_id: str) -> Turn | None: ...

    async def start(self, owner_id: UUID, turn_id: str) -> Turn | None: ...

    async def heartbeat(self, owner_id: UUID, turn_id: str) -> bool: ...

    async def cancel_requested(self, owner_id: UUID, turn_id: str) -> bool: ...

    async def move(
        self,
        owner_id: UUID,
        turn_id: str,
        target: TurnStatus,
        reason: str | None = None,
    ) -> Turn: ...


class BackgroundThreads(Protocol):
    """The thread state a worker reads and writes (``storage.threads.PostgresThreadStore``)."""

    @property
    def checkpointer(self) -> BaseCheckpointSaver[str]: ...

    @property
    def turns(self) -> BackgroundTurns: ...

    async def extend(self, key: ThreadKey) -> None: ...

    async def release(self, key: ThreadKey) -> None: ...

    async def messages(self, key: ThreadKey) -> list[BaseMessage]: ...

    async def add_usage(
        self,
        key: ThreadKey,
        calls: Sequence[CallUsage],
        turn_id: str | None = None,
    ) -> None: ...

    async def session_calls(self, key: ThreadKey) -> list[CallUsage]: ...

    async def turn_calls(self, key: ThreadKey, turn_id: str) -> list[CallUsage]: ...

    async def add_tool_messages(self, key: ThreadKey, messages: Sequence[BaseMessage]) -> None: ...

    async def set_pending(self, key: ThreadKey, request: ConfirmationRequest | None) -> None: ...

    async def answers(self, key: ThreadKey) -> tuple[dict[str, float], frozenset[str]]: ...


@dataclass(frozen=True)
class BackgroundSettings:
    """Timing of a background turn (seconds).

    Attributes:
        heartbeat_seconds: How often the turn's heartbeat and the thread's lease are renewed.
        soft_limit_seconds: After this the turn stops after its current step (``time_limit``).
        hard_limit_seconds: The task queue kills the process after this; halfway between the
            soft and the hard limit a step that has not returned is abandoned.
        event_ttl_seconds: How long a finished turn's stream stays readable.
        max_resumes: How often one interrupted turn may be resumed.
    """

    heartbeat_seconds: float
    soft_limit_seconds: float
    hard_limit_seconds: float
    event_ttl_seconds: int
    max_resumes: int

    @classmethod
    def from_config(cls, worker: WorkerSettings, max_resumes: int) -> BackgroundSettings:
        """The timing ``[worker]`` configures, with ``[agent].max_resumes_per_turn``."""
        return cls(
            heartbeat_seconds=worker.heartbeat_seconds,
            soft_limit_seconds=worker.soft_time_limit_seconds,
            hard_limit_seconds=worker.time_limit_seconds,
            event_ttl_seconds=worker.event_ttl_seconds,
            max_resumes=max_resumes,
        )

    @property
    def running_ttl_seconds(self) -> int:
        """How long a stream is kept while its turn runs (it outlives the hard limit)."""
        return round(self.hard_limit_seconds) + self.event_ttl_seconds


@dataclass(frozen=True)
class BackgroundServices:
    """The collaborators of a worker, built once per process.

    Attributes:
        threads: The thread and turn store.
        bus: Where the turn's events are published.
        load_keys: Decrypts the owner's model key and adds the operator's (raises
            ``KeysUnavailableError``).
        build_model: Builds the chat model from the turn's model key.
        refund: Gives a counted turn back (user id, turn id); None when nothing is counted.
        turn_settings: What does not change between turns.
        settings: Timing.
    """

    threads: BackgroundThreads
    bus: TurnEventBus
    load_keys: Callable[[UUID], Awaitable[TurnKeys]]
    build_model: Callable[[SecretStr], BaseChatModel]
    refund: Callable[[UUID, str], Awaitable[bool]] | None
    turn_settings: TurnSettings
    settings: BackgroundSettings


@dataclass
class TurnRun:
    """One background turn segment while it runs: its record, its stream position and outcome."""

    turn: Turn
    services: BackgroundServices
    seq: int = QUEUED_SEQ + 1
    agent_running: bool = False
    stopped: TurnStopped | None = None
    ended: bool = False
    done: bool = False
    stop_reason: FailureReason | None = None
    forced: bool = False
    queue_wait_seconds: float | None = None

    @property
    def key(self) -> ThreadKey:
        """The turn's thread and owner."""
        return self.turn.key

    @property
    def stream(self) -> str:
        """The stream of this segment."""
        return turn_stream(self.turn.id, self.turn.resume_count)

    async def publish(self, event: RelayedEvent) -> None:
        """Append ``event`` to the stream; the last one sets the finished stream's lifetime."""
        timing = self.services.settings
        ttl = timing.event_ttl_seconds if is_last(event) else timing.running_ttl_seconds
        await self.services.bus.publish(self.stream, self.seq, encode(event), ttl)
        self.seq += 1
        self.done = self.done or is_last(event)

    def stop(self, reason: FailureReason, correlation_id: str) -> TurnStopped:
        """Record why the turn stopped; resumable while the reason allows and the cap is not
        reached."""
        again = resumable(reason) and self.turn.resume_count < self.services.settings.max_resumes
        self.stopped = TurnStopped(reason, correlation_id, again)
        self.agent_running = False
        return self.stopped


async def record(event: TurnEvent, run: TurnRun) -> None:
    """Store what ``event`` changes, then publish it (a failure becomes ``TurnStopped``; the
    end is published by the job once the final status is stored)."""
    match event:
        case TurnFailed(reason=reason, correlation_id=correlation_id):
            await run.publish(run.stop(reason, correlation_id))
        case TurnDone():
            run.ended = True
        case _:
            await _store(event, run)
            await run.publish(event)


async def _store(event: TurnEvent, run: TurnRun) -> None:
    """What ``event`` changes in the thread's stored state (and the run's own)."""
    threads, key = run.services.threads, run.key
    match event:
        case AgentStarted():
            run.agent_running = True
        case ToolCalls(message=message):
            await threads.add_tool_messages(key, [message])
        case ToolResults(messages=messages):
            await threads.add_tool_messages(key, list(messages))
        case ConfirmationNeeded(request=request):
            await threads.set_pending(key, request)
        case TurnUsage():
            run.agent_running = False
            await refund_if_unused(run)
        case _:
            pass


async def close_without_running(run: TurnRun, reason: FailureReason) -> None:
    """Close a turn that stops without running (or whose step was abandoned): its stop (unless
    one was sent) and the usage recorded so far; the job then publishes the end."""
    if run.stopped is None:
        await run.publish(run.stop(reason, new_correlation_id()))
    session = tuple(await run.services.threads.session_calls(run.key))
    turn = tuple(await run.services.threads.turn_calls(run.key, run.turn.id))
    await refund_if_unused(run)
    await run.publish(TurnUsage(turn=turn, session=session))
    run.ended = True


async def refund_if_unused(run: TurnRun) -> bool:
    """Give back a counted turn that stopped before it reached the model.

    Only a turn that stopped for a reason it cannot resume from, with no model call recorded,
    is given back: a resumable stop continues for free, so refunding it too would let one count
    pay for any number of turns. A database failure is logged (class only), never fatal.
    """
    refund, planned, stopped = run.services.refund, run.turn.planned, run.stopped
    if refund is None or planned is None or not planned.counted or stopped is None:
        return False
    if resumable(stopped.reason):
        return False
    try:
        if await run.services.threads.turn_calls(run.key, run.turn.id):
            return False
        return await refund(run.turn.owner_id, run.turn.id)
    except DATABASE_ERRORS as error:
        logger.warning("Quota refund failed: %s", type(error).__name__)
        return False


def final_status(run: TurnRun) -> tuple[TurnStatus, str | None]:
    """The status the turn ends in: completed, interrupted (resumable reason) or failed."""
    if run.stopped is None and run.ended:
        return TurnStatus.COMPLETED, None
    reason = run.stopped.reason if run.stopped is not None else FailureReason.WORKER_LOST
    target = TurnStatus.INTERRUPTED if resumable(reason) else TurnStatus.FAILED
    return target, reason.value
