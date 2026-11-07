"""Present one chat turn: run it through ``app.turns`` and translate its events into the contract.

This module never runs the graph itself. The runner reads the keys, builds the agent, meters
usage and classifies failures; here each ``TurnEvent`` becomes the wire events of
``api/schemas/chat.py`` (sequence numbers, step labels, the rebuilt workspace, the open
confirmation request, the usage summary and the fixed failure messages), and the thread's
bookkeeping in the ``ThreadStore`` is done.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator, Callable, Mapping, Sequence
from contextlib import aclosing
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, cast

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage
from pydantic import SecretStr

from agent.completion import CompletionGuard
from agent.guardrails import ScopeGuard
from agent.missing import ask_text
from api.schemas.chat import (
    AssistantMessage,
    ChatRequest,
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
    Usage,
    WorkspaceUpdate,
)
from api.services.confirmation import TurnPlan, request_event
from api.services.projectors.rules import WorkspaceRules
from api.services.provider_errors import NO_KEY_MESSAGE, interruption_message, message_for
from api.services.state_serializer import build_workspace
from api.services.threads import ThreadStore
from api.services.turn_lifecycle import can_resume
from api.services.usage_meter import summarize
from app.key_vault import ServiceKeys
from app.turns import (
    AgentStarted,
    AssistantText,
    ConfirmationNeeded,
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
    TurnRequest,
    TurnSegment,
    TurnServices,
    TurnSettings,
    TurnUsage,
    execute_turn,
    load_turn_keys,
    pending_steps,
    resumable,
)
from app.usage_meter import CallUsage
from config.telemetry import TelemetrySettings
from config.ui import ModelPrice
from storage.turn_model import Turn, TurnStatus, TurnTransitionError

__all__ = [
    "NO_KEY_MESSAGE",
    "AgentRuntime",
    "EventSequence",
    "ModelFactory",
    "resume_steps",
    "run_resume",
    "run_turn",
]

logger = logging.getLogger(__name__)

ModelFactory = Callable[[SecretStr], BaseChatModel]


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


class EventSequence:
    """Numbers the events of one stream from 0, in emission order."""

    def __init__(self) -> None:
        self._next = 0

    def next(self) -> int:
        """Return the next sequence number."""
        number = self._next
        self._next += 1
        return number


@dataclass
class _Outcome:
    """Whether the turn being presented stopped before its answer."""

    stopped: bool = False


@dataclass(frozen=True)
class _Turn:
    """One turn being presented: its record, where its bookkeeping goes and how it is shown."""

    record: Turn
    threads: ThreadStore
    runtime: AgentRuntime
    resumed: bool = False
    seq: EventSequence = field(default_factory=EventSequence)
    outcome: _Outcome = field(default_factory=_Outcome)

    @property
    def thread_id(self) -> str:
        """The turn's thread."""
        return self.record.thread_id


async def run_turn(
    request: ChatRequest,
    *,
    keys: ServiceKeys,
    threads: ThreadStore,
    runtime: AgentRuntime,
    turn: Turn,
    plan: TurnPlan | None = None,
) -> AsyncGenerator[StreamEvent]:
    """Run one turn (its record ``turn`` is running) and yield its events; always ends with
    ``usage`` and ``turn_finished``.

    Each tool call becomes a started and a finished ``tool_status`` event carrying the
    configured label (the tool name when none is configured), never the tool's payload.
    ``usage`` reports the tokens and estimated cost of every model call of the turn (its resumed
    segments included) and of the thread so far, even when the turn failed.

    A failure the user can fix (no credits, a refused key, a rate limit, the provider down, the
    step limit) interrupts the turn: one ``turn_interrupted`` event with its reason and fixed
    message, and the record becomes ``interrupted``. Any other failure becomes one ``error``
    event (a fixed message for a missing key or a refused account, otherwise a generic one with
    the id the details were logged under) and the record becomes ``failed``.
    """
    chosen = plan or TurnPlan(message=request.message, note="")
    turn_request = TurnRequest(
        request.thread_id,
        request.message,
        chosen.message,
        chosen.note,
        segment=TurnSegment(turn.id, turn.resume_count),
    )
    presented = _present_turn(turn_request, keys, _Turn(turn, threads, runtime))
    async with aclosing(
        presented,
    ) as events:  # closed here, in this context, when the client leaves
        async for event in events:
            yield event


async def run_resume(
    *,
    keys: ServiceKeys,
    threads: ThreadStore,
    runtime: AgentRuntime,
    turn: Turn,
) -> AsyncGenerator[StreamEvent]:
    """Continue the interrupted ``turn`` (now running again) from its last checkpoint; the
    events are those of ``run_turn``, starting with ``turn_started`` marked as resumed."""
    messages = await threads.messages(turn.thread_id)
    question = next((m.text for m in reversed(messages) if isinstance(m, HumanMessage)), "")
    turn_request = TurnRequest(
        turn.thread_id,
        question,
        "",
        resume=True,
        segment=TurnSegment(turn.id, turn.resume_count),
    )
    presented = _present_turn(turn_request, keys, _Turn(turn, threads, runtime, resumed=True))
    async with aclosing(
        presented,
    ) as events:  # closed here, in this context, when the client leaves
        async for event in events:
            yield event


async def resume_steps(
    thread_id: str,
    *,
    keys: ServiceKeys,
    threads: ThreadStore,
    runtime: AgentRuntime,
) -> tuple[str, ...]:
    """What the thread's last checkpoint would run next; raises ``KeysUnavailableError``."""
    services = _services(keys, threads, runtime, thread_id, turn_id=None)
    return await pending_steps(thread_id, services, runtime.turn_settings())


async def _present_turn(
    request: TurnRequest,
    keys: ServiceKeys,
    turn: _Turn,
) -> AsyncGenerator[StreamEvent]:
    services = _services(keys, turn.threads, turn.runtime, turn.thread_id, turn.record.id)
    events = execute_turn(request, services, turn.runtime.turn_settings())
    async with aclosing(_relay(events, turn)) as relayed:  # closed here when the client leaves
        async for event in relayed:
            yield event


def _services(
    keys: ServiceKeys,
    threads: ThreadStore,
    runtime: AgentRuntime,
    thread_id: str,
    turn_id: str | None,
) -> TurnServices:
    """The runner's collaborators: this turn's keys, model factory and the thread's store."""

    async def record_usage(calls: Sequence[CallUsage]) -> Sequence[CallUsage]:
        await threads.add_usage(thread_id, calls, turn_id)
        return await threads.session_calls(thread_id)

    return TurnServices(
        load_keys=lambda: load_turn_keys(keys),
        build_model=runtime.build_model,
        checkpointer=threads.checkpointer,
        user_values=lambda: threads.answers(thread_id),
        record_usage=record_usage,
    )


async def _relay(events: AsyncGenerator[TurnEvent], turn: _Turn) -> AsyncGenerator[StreamEvent]:
    """Present each turn event; a failure while presenting one is thrown back into the runner,
    which reports it as the turn's failure (then usage and the end, as for any failure)."""
    try:
        event = await anext(events)
        while True:
            try:
                shown = await _present(event, turn)
            except Exception as error:
                event = await events.athrow(error)
                continue
            for item in shown:
                yield item
            event = await anext(events)
    except StopAsyncIteration:
        return
    finally:
        await events.aclose()


async def _present(event: TurnEvent, turn: _Turn) -> list[StreamEvent]:
    """The wire events of one turn event (the thread's bookkeeping is done on the way)."""
    stateful = await _bookkeeping(event, turn)
    if stateful is not None:
        return stateful
    return _shown(event, turn)


async def _bookkeeping(event: TurnEvent, turn: _Turn) -> list[StreamEvent] | None:
    """Events that change the thread's stored state; None for any other event."""
    match event:
        case AgentStarted():  # the user's answers show on the card now, not only once a tool runs
            supplied, _ = await turn.threads.answers(turn.thread_id)
            return await _rebuild(turn) if supplied else []
        case ToolCalls(message=message):
            await _keep_tool_messages(turn, [message])
            return []
        case ToolResults(messages=messages):
            return await _keep_tool_messages(turn, list(messages))
        case ConfirmationNeeded(request=pending):
            await turn.threads.set_pending(turn.thread_id, pending)
            question = AssistantMessage(seq=turn.seq.next(), text=ask_text(pending))
            return [question, request_event(turn.seq.next(), pending)]
        case TurnFailed() | TurnUsage() | TurnDone():
            return await _closing(event, turn)
        case _:
            return None


async def _closing(event: TurnFailed | TurnUsage | TurnDone, turn: _Turn) -> list[StreamEvent]:
    """A failure, the usage and the end: the turn's record is updated on the way."""
    match event:
        case TurnFailed():
            return [await _stopped(event, turn)]
        case TurnUsage():
            return [await _usage(event, turn)]
        case TurnDone():
            if not turn.outcome.stopped:
                await _move(turn, TurnStatus.COMPLETED)
            return [TurnFinished(seq=turn.seq.next())]


async def _stopped(event: TurnFailed, turn: _Turn) -> StreamEvent:
    """Interrupt the turn for a reason the user can fix; fail it for any other."""
    turn.outcome.stopped = True
    seq, reason = turn.seq, event.reason
    if not resumable(reason):
        await _move(turn, TurnStatus.FAILED, reason)
        message = message_for(reason)
        return ErrorEvent(seq=seq.next(), message=message, correlation_id=event.correlation_id)
    interrupted = await _move(turn, TurnStatus.INTERRUPTED, reason)
    again = interrupted is not None and can_resume(interrupted, turn.runtime.max_resumes_per_turn)
    return TurnInterrupted(
        seq=seq.next(),
        reason=cast(InterruptionReason, reason.value),
        resumable=again,
        message=interruption_message(reason, resumable=again),
    )


async def _move(turn: _Turn, target: TurnStatus, reason: str | None = None) -> Turn | None:
    """Record the turn's new status; a move another process made impossible is only logged."""
    try:
        return await turn.threads.turns.move(turn.record.id, target, reason)
    except TurnTransitionError:
        logger.warning("turn %s could not move to %s", turn.record.id, target)
        return None


def _shown(event: TurnEvent, turn: _Turn) -> list[StreamEvent]:
    """Events shown as they are, numbered and labelled."""
    match event:
        case TextDelta(text=text):
            return [Token(seq=turn.seq.next(), text=text)]
        case AssistantText(text=text):
            return [AssistantMessage(seq=turn.seq.next(), text=text)]
        case ToolStarted() | ToolFinished():
            return [_tool_status(event, turn)]
        case ScopePassed() | ScopeRedirect():
            return _scope(event, turn)
        case _:
            return _lifecycle(event, turn)


def _lifecycle(event: TurnEvent, turn: _Turn) -> list[StreamEvent]:
    """The start of the turn (marked as resumed when it continues an interrupted one)."""
    if isinstance(event, TurnBegan):
        started = TurnStarted(
            seq=turn.seq.next(),
            thread_id=turn.thread_id,
            turn_id=turn.record.id,
            resumed=turn.resumed,
        )
        return [started]
    return []


def _tool_status(event: ToolStarted | ToolFinished, turn: _Turn) -> ToolStatus:
    label = turn.runtime.step_labels.get(event.tool_name, event.tool_name)
    status: Literal["ok", "error"] | None = None
    if isinstance(event, ToolFinished):
        status = "error" if event.failed else "ok"
    return ToolStatus(
        seq=turn.seq.next(),
        phase="started" if isinstance(event, ToolStarted) else "finished",
        call_id=event.call_id,
        tool_name=event.tool_name,
        label=label,
        status=status,
    )


def _scope(event: ScopePassed | ScopeRedirect, turn: _Turn) -> list[StreamEvent]:
    """The scope check's outcome: a pivot (the redirect texts) or a pass to the agent."""
    if isinstance(event, ScopePassed):
        return [ScopeDecision(seq=turn.seq.next(), in_scope=True)]
    return [
        ScopeDecision(seq=turn.seq.next(), in_scope=False),
        *(GuardrailPivotResponse(seq=turn.seq.next(), text=text) for text in event.texts),
    ]


async def _usage(event: TurnUsage, turn: _Turn) -> Usage:
    """The turn's calls (every segment of a resumed turn) and the thread's so far."""
    pricing = turn.runtime.pricing
    calls = await turn.threads.turn_calls(turn.thread_id, turn.record.id)
    return Usage(
        seq=turn.seq.next(),
        turn=summarize(calls, pricing),
        session=summarize(event.session, pricing),
    )


async def _keep_tool_messages(turn: _Turn, messages: list[BaseMessage]) -> list[StreamEvent]:
    """Store the tool calls or results for the workspace; rebuild it after a batch of results."""
    if turn.runtime.workspace_rules is None or not messages:
        return []
    await turn.threads.add_tool_messages(turn.thread_id, messages)
    calls_only = not any(m.type == "tool" for m in messages)
    return [] if calls_only else await _rebuild(turn)


async def _rebuild(turn: _Turn) -> list[StreamEvent]:
    """Rebuild the workspace from the tool messages and the user's answers, if it changed."""
    rules = turn.runtime.workspace_rules
    if rules is None:
        return []
    threads, thread_id = turn.threads, turn.thread_id
    previous = await threads.workspace(thread_id)
    supplied, _ = await threads.answers(thread_id)
    state = build_workspace(await threads.tool_messages(thread_id), rules, previous, supplied)
    if state == previous:
        return []
    await threads.set_workspace(thread_id, state)
    return [WorkspaceUpdate(seq=turn.seq.next(), state=state)]
