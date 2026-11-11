"""Present one chat turn: read its events from the turn's stream and translate them into the
contract.

The API never runs the agent: a background worker runs the turn (``app.turns.job``), records
everything it changes and publishes its events. Here each relayed event becomes the wire events
of ``api/schemas/chat.py`` (sequence numbers, step labels, the live status line, the rebuilt
workspace, the open confirmation request, the usage summary and the fixed failure messages).
Presenting changes no turn state, so any number of readers (a reload, a second tab) see the same
events; the workspace rebuild is deterministic and idempotent.

The wire ``seq`` of an event is ``bus_seq * SLOTS + index``: strictly increasing, and a
``Last-Event-ID`` maps back to the record to resume from. A reader whose turn ended without its
last record (its worker was lost) ends the stream from the stored turn.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator, Callable, Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from types import MappingProxyType
from typing import Literal, cast

from langchain_core.language_models import BaseChatModel
from pydantic import SecretStr

from agent.completion import CompletionGuard
from agent.guardrails import ScopeGuard
from agent.missing import ask_text
from api.schemas.chat import (
    AssistantMessage,
    ErrorEvent,
    GuardrailPivotResponse,
    InterruptionReason,
    ScopeDecision,
    StreamEvent,
    Token,
    ToolStatus,
    TurnFinished,
    TurnInterrupted,
    TurnStarted,
    TurnStatus,
    Usage,
    WorkspaceUpdate,
)
from api.services.confirmation import request_event
from api.services.key_setup import KeyLoader
from api.services.projectors.rules import WorkspaceRules
from api.services.provider_errors import NO_KEY_MESSAGE, interruption_message, message_for
from api.services.threads import ThreadStore
from api.services.turn_lifecycle import interruption
from api.services.usage_meter import summarize
from api.services.workspace_sync import current_workspace
from app.turns import (
    AgentStarted,
    AssistantText,
    ConfirmationNeeded,
    FailureReason,
    ScopePassed,
    ScopeRedirect,
    TextDelta,
    ToolFinished,
    ToolResults,
    ToolStarted,
    TurnDone,
    TurnServices,
    TurnSettings,
    TurnUsage,
    new_correlation_id,
    pending_steps,
    resumable,
)
from app.turns.bus import TurnEventBus, turn_stream
from app.turns.codec import RelayedEvent, TurnQueued, TurnStopped, WorkerStarted, decode, is_last
from app.usage_meter import CallUsage
from config.telemetry import TelemetrySettings
from config.ui import ModelPrice
from storage.keys import ThreadKey
from storage.turn_model import OPEN_STATUSES, Turn
from storage.turn_model import TurnStatus as RecordStatus

__all__ = [
    "NO_KEY_MESSAGE",
    "SLOTS",
    "AgentRuntime",
    "ModelFactory",
    "RelayTiming",
    "relay_turn",
    "resume_steps",
]

logger = logging.getLogger(__name__)

ModelFactory = Callable[[SecretStr], BaseChatModel]
SLOTS = 64  # wire events one relayed record may become (more are dropped, logged)


@dataclass(frozen=True)
class AgentRuntime:
    """What a turn needs besides the request: how to build the model and how to report it.

    Attributes:
        build_model: Builds the chat model from the turn's key.
        recursion_limit: LangGraph step limit of the run.
        step_labels: Tool name -> label shown for its step.
        model_name: Configured model name (the key into ``pricing``).
        pricing: Model name -> token prices; a model without an entry is unpriced.
        scope_guard: Checks that each user turn is on topic before the agent runs, when given.
        completion_guard: Sends a reply that only announced its next steps back to work, when given.
        system_prompt: The agent's system prompt; None keeps the standard one.
        workspace_rules: Builds the workspace sent after each tool batch; None sends none.
        telemetry: Monitoring settings; each turn is then recorded as a trace. None records none.
        max_resumes_per_turn: How many times one interrupted turn may be resumed
            (``[agent].max_resumes_per_turn``; the default serves tests only).
    """

    build_model: ModelFactory
    recursion_limit: int
    step_labels: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    model_name: str = ""
    pricing: Mapping[str, ModelPrice] = field(default_factory=lambda: MappingProxyType({}))
    scope_guard: ScopeGuard | None = None
    completion_guard: CompletionGuard | None = None
    system_prompt: str | None = None
    workspace_rules: WorkspaceRules | None = None
    telemetry: TelemetrySettings | None = None
    max_resumes_per_turn: int = 3

    def turn_settings(self) -> TurnSettings:
        """The runner's view of these settings (everything but presentation)."""
        return TurnSettings(
            recursion_limit=self.recursion_limit,
            model_name=self.model_name,
            pricing=self.pricing,
            scope_guard=self.scope_guard,
            completion_guard=self.completion_guard,
            system_prompt=self.system_prompt,
            telemetry=self.telemetry,
        )


@dataclass(frozen=True)
class RelayTiming:
    """How a reader waits (seconds).

    Attributes:
        block_seconds: One blocking read of the stream before the turn's record is checked.
        grace_seconds: A last read after the record says the turn ended (its end record is
            published right after its status is stored).
        stale_after: A running turn with an older heartbeat lost its worker.
    """

    block_seconds: float
    grace_seconds: float
    stale_after: timedelta


async def resume_steps(
    key: ThreadKey,
    *,
    keys: KeyLoader,
    threads: ThreadStore,
    runtime: AgentRuntime,
) -> tuple[str, ...]:
    """What the thread's last checkpoint would run next (no model call, no tool); raises
    ``KeysUnavailableError``."""

    async def no_usage(calls: object) -> list[CallUsage]:
        return []

    services = TurnServices(
        load_keys=keys,
        build_model=runtime.build_model,
        checkpointer=threads.checkpointer,
        user_values=lambda: threads.answers(key),
        record_usage=no_usage,
    )
    return await pending_steps(key.checkpoint_id, services, runtime.turn_settings())


# --- the relay ----------------------------------------------------------------------------------


@dataclass
class _Relay:
    """One reader of one turn segment."""

    turn: Turn
    threads: ThreadStore
    runtime: AgentRuntime
    after: int | None
    last_record: int = -1

    @property
    def key(self) -> ThreadKey:
        return self.turn.key

    @property
    def stream(self) -> str:
        return turn_stream(self.turn.id, self.turn.resume_count)

    def start(self) -> int | None:
        """The record to read after: the one before the record ``after`` belongs to (its
        events already delivered are skipped), None to read from the first."""
        if self.after is None or self.after < SLOTS:
            return None
        return self.after // SLOTS - 1

    def fresh(self, event: StreamEvent) -> bool:
        """Whether the reader has not received ``event`` yet."""
        return self.after is None or event.seq > self.after


class _Numbers:
    """The wire ``seq`` of the events of one record."""

    def __init__(self, record: int) -> None:
        self._base, self._index = record * SLOTS, 0

    def next(self) -> int:
        number = self._base + min(self._index, SLOTS - 1)
        self._index += 1
        return number

    @property
    def overflowed(self) -> bool:
        return self._index > SLOTS


async def relay_turn(
    turn: Turn,
    *,
    bus: TurnEventBus,
    threads: ThreadStore,
    runtime: AgentRuntime,
    timing: RelayTiming,
    after_seq: int | None = None,
) -> AsyncGenerator[StreamEvent]:
    """The wire events of one turn segment from its stream, after the wire ``seq``
    ``after_seq`` (from the first when None); always ends with ``turn_finished``."""
    relay = _Relay(turn, threads, runtime, after_seq)
    async for record, event in _records(bus, relay, timing):
        for shown in await _shown(event, record, relay):
            if relay.fresh(shown):
                yield shown
        if is_last(event):
            return
    for shown in await _ended_without_record(relay):
        if relay.fresh(shown):
            yield shown


async def _records(
    bus: TurnEventBus,
    relay: _Relay,
    timing: RelayTiming,
) -> AsyncGenerator[tuple[int, RelayedEvent]]:
    """The turn's records in order until its last one, or until the turn ended without it."""
    position = relay.start()
    while True:
        entries = await bus.read(relay.stream, position, timing.block_seconds)
        if not entries and await _gone(relay, timing):
            entries = await bus.read(relay.stream, position, timing.grace_seconds)
            if not entries:
                return
        for record, raw in entries:
            position = relay.last_record = record
            event = decode(raw)
            if event is not None:
                yield record, event


async def _gone(relay: _Relay, timing: RelayTiming) -> bool:
    """Whether the turn is no longer open (a running turn with a stale heartbeat is first
    interrupted as ``worker_lost`` and its thread released)."""
    turns = relay.threads.turns
    stale = await turns.interrupt_stale(timing.stale_after, FailureReason.WORKER_LOST, relay.key)
    if stale:
        await relay.threads.release(relay.key)
    current = await turns.get(relay.key.owner_id, relay.turn.id)
    return current is None or current.status not in OPEN_STATUSES


async def _shown(event: RelayedEvent, record: int, relay: _Relay) -> list[StreamEvent]:
    numbers = _Numbers(record)
    shown = await _stateful(event, numbers, relay)
    if shown is None:
        shown = _plain(event, numbers, relay) or _lifecycle(event, numbers, relay)
    if numbers.overflowed:
        logger.warning("Record %d of turn %s had too many events", record, relay.turn.id)
        shown = shown[:SLOTS]
    return shown


async def _stateful(event: RelayedEvent, n: _Numbers, relay: _Relay) -> list[StreamEvent] | None:
    """Events whose presentation reads the thread's stored state; None for any other."""
    match event:
        case AgentStarted():  # the user's answers show on the card now, not only once a tool runs
            supplied, _ = await relay.threads.answers(relay.key)
            workspace = await _workspace(n, relay) if supplied else []
            return [*workspace, _status(n, "thinking")]
        case ToolResults():
            return [*await _workspace(n, relay), _status(n, "thinking")]
        case TurnUsage(session=session):
            return [await _usage(n, relay, session)]
        case _:
            return None


def _plain(event: RelayedEvent, n: _Numbers, relay: _Relay) -> list[StreamEvent]:
    """Events shown as they are, numbered and labelled."""
    match event:
        case TextDelta(text=text):
            return [Token(seq=n.next(), text=text)]
        case AssistantText(text=text):
            return [AssistantMessage(seq=n.next(), text=text)]
        case ToolStarted():
            label = _label(event.tool_name, relay)
            return [_tool_status(event, n, relay), _status(n, "running_tool", label=label)]
        case ToolFinished():
            return [_tool_status(event, n, relay)]
        case ScopePassed() | ScopeRedirect():
            return _scope(event, n)
        case ConfirmationNeeded(request=pending):
            question = AssistantMessage(seq=n.next(), text=ask_text(pending))
            return [question, request_event(n.next(), pending)]
        case _:
            return []


def _lifecycle(event: RelayedEvent, n: _Numbers, relay: _Relay) -> list[StreamEvent]:
    """The start (queued, then running), the stop and the end of the turn."""
    match event:
        case TurnQueued(position=position):
            started = TurnStarted(
                seq=n.next(),
                thread_id=relay.key.thread_id,
                turn_id=relay.turn.id,
                resumed=relay.turn.resume_count > 0,
            )
            return [started, _status(n, "queued", position=position)]
        case WorkerStarted():
            return [_status(n, "running")]
        case TurnStopped():
            return [_stopped(event, n)]
        case TurnDone():
            return [TurnFinished(seq=n.next())]
        case _:
            return []


Phase = Literal["queued", "running", "thinking", "running_tool"]


def _status(
    n: _Numbers,
    phase: Phase,
    *,
    label: str | None = None,
    position: int | None = None,
) -> TurnStatus:
    return TurnStatus(seq=n.next(), phase=phase, label=label, position=position)


def _label(tool_name: str, relay: _Relay) -> str:
    return relay.runtime.step_labels.get(tool_name, tool_name)


def _tool_status(event: ToolStarted | ToolFinished, n: _Numbers, relay: _Relay) -> ToolStatus:
    status: Literal["ok", "error"] | None = None
    if isinstance(event, ToolFinished):
        status = "error" if event.failed else "ok"
    return ToolStatus(
        seq=n.next(),
        phase="started" if isinstance(event, ToolStarted) else "finished",
        call_id=event.call_id,
        tool_name=event.tool_name,
        label=_label(event.tool_name, relay),
        status=status,
    )


def _scope(event: ScopePassed | ScopeRedirect, n: _Numbers) -> list[StreamEvent]:
    """The scope check's outcome: a pivot (the redirect texts) or a pass to the agent."""
    if isinstance(event, ScopePassed):
        return [ScopeDecision(seq=n.next(), in_scope=True)]
    return [
        ScopeDecision(seq=n.next(), in_scope=False),
        *(GuardrailPivotResponse(seq=n.next(), text=text) for text in event.texts),
    ]


def _stopped(event: TurnStopped, n: _Numbers) -> StreamEvent:
    """A reason the user can fix interrupts the turn; any other fails it (a fixed message)."""
    reason = event.reason
    if not resumable(reason):
        message = message_for(reason)
        return ErrorEvent(seq=n.next(), message=message, correlation_id=event.correlation_id)
    return TurnInterrupted(
        seq=n.next(),
        reason=cast(InterruptionReason, reason.value),
        resumable=event.resumable,
        message=interruption_message(reason, resumable=event.resumable),
    )


async def _usage(n: _Numbers, relay: _Relay, session: tuple[CallUsage, ...]) -> Usage:
    """The turn's calls (every segment of a resumed turn) and the thread's so far."""
    pricing = relay.runtime.pricing
    calls = await relay.threads.turn_calls(relay.key, relay.turn.id)
    return Usage(seq=n.next(), turn=summarize(calls, pricing), session=summarize(session, pricing))


async def _workspace(n: _Numbers, relay: _Relay) -> list[StreamEvent]:
    """The workspace rebuilt from the stored tool results (always sent, so every reader of
    the turn sees the same events)."""
    rules = relay.runtime.workspace_rules
    if rules is None:
        return []
    state = await current_workspace(relay.threads, relay.key, rules)
    return [WorkspaceUpdate(seq=n.next(), state=state)]


async def _ended_without_record(relay: _Relay) -> list[StreamEvent]:
    """The end of a turn whose worker stopped before its last record: its stored stop, the
    usage recorded so far and the end."""
    n = _Numbers(relay.last_record + 1)
    turn = await relay.threads.turns.get(relay.key.owner_id, relay.turn.id)
    stop = _stored_stop(turn, n, relay.runtime.max_resumes_per_turn)
    session = tuple(await relay.threads.session_calls(relay.key))
    usage = await _usage(n, relay, session)
    return [*stop, usage, TurnFinished(seq=n.next())]


def _stored_stop(turn: Turn | None, n: _Numbers, max_resumes: int) -> list[StreamEvent]:
    if turn is None or turn.status is RecordStatus.COMPLETED:
        return []
    stopped = interruption(turn, max_resumes)
    if stopped is not None:
        return [TurnInterrupted(seq=n.next(), **stopped.model_dump())]
    reason = _reason(turn.reason)
    message = message_for(reason)
    return [ErrorEvent(seq=n.next(), message=message, correlation_id=new_correlation_id())]


def _reason(stored: str | None) -> FailureReason:
    """A stored reason (untrusted); an unknown one reads as unexpected."""
    try:
        return FailureReason(stored) if stored is not None else FailureReason.UNEXPECTED
    except ValueError:
        return FailureReason.UNEXPECTED
