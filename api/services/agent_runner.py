"""Present one chat turn: run it through ``app.turns`` and translate its events into the contract.

This module never runs the graph itself. The runner reads the keys, builds the agent, meters
usage and classifies failures; here each ``TurnEvent`` becomes the wire events of
``api/schemas/chat.py`` (sequence numbers, step labels, the rebuilt workspace, the open
confirmation request, the usage summary and the fixed failure messages), and the thread's
bookkeeping in the ``ThreadStore`` is done.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator, Callable, Mapping, Sequence
from contextlib import aclosing
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from pydantic import SecretStr

from agent.completion import CompletionGuard
from agent.guardrails import ScopeGuard
from agent.missing import ask_text
from api.schemas.chat import (
    AssistantMessage,
    ChatRequest,
    ErrorEvent,
    GuardrailPivotResponse,
    ScopeDecision,
    StreamEvent,
    Token,
    ToolStatus,
    TurnFinished,
    TurnStarted,
    Usage,
    WorkspaceUpdate,
)
from api.services.confirmation import TurnPlan, request_event
from api.services.projectors.rules import WorkspaceRules
from api.services.provider_errors import NO_KEY_MESSAGE, message_for
from api.services.state_serializer import build_workspace
from api.services.threads import ThreadStore
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
    TurnServices,
    TurnSettings,
    TurnUsage,
    execute_turn,
    load_turn_keys,
)
from app.usage_meter import CallUsage
from config.telemetry import TelemetrySettings
from config.ui import ModelPrice

__all__ = ["NO_KEY_MESSAGE", "AgentRuntime", "EventSequence", "ModelFactory", "run_turn"]

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


@dataclass(frozen=True)
class _Turn:
    """One turn being presented: its thread, where its bookkeeping goes and how it is shown."""

    thread_id: str
    threads: ThreadStore
    runtime: AgentRuntime
    seq: EventSequence = field(default_factory=EventSequence)


async def run_turn(
    request: ChatRequest,
    *,
    keys: ServiceKeys,
    threads: ThreadStore,
    runtime: AgentRuntime,
    plan: TurnPlan | None = None,
) -> AsyncGenerator[StreamEvent]:
    """Run one turn and yield its events; always ends with ``usage`` and ``turn_finished``.

    Each tool call becomes a started and a finished ``tool_status`` event carrying the
    configured label (the tool name when none is configured), never the tool's payload.
    ``usage`` reports the tokens and estimated cost of every model call of the turn and of
    the thread so far, even when the turn failed.

    Failures become one ``error`` event: a user-facing message for a missing key or keychain or
    a known provider failure (no credits, a refused key, a rate limit, no connection), otherwise
    a generic message (the details are logged, redacted, under the same id).
    """
    turn = _Turn(request.thread_id, threads, runtime)
    chosen = plan or TurnPlan(message=request.message, note="")
    events = execute_turn(
        TurnRequest(request.thread_id, request.message, chosen.message, chosen.note),
        _services(keys, threads, runtime, request.thread_id),
        runtime.turn_settings(),
    )
    async with aclosing(_relay(events, turn)) as relayed:  # closed here when the client leaves
        async for event in relayed:
            yield event


def _services(
    keys: ServiceKeys,
    threads: ThreadStore,
    runtime: AgentRuntime,
    thread_id: str,
) -> TurnServices:
    """The runner's collaborators: this turn's keys, model factory and the thread's store."""

    async def record_usage(calls: Sequence[CallUsage]) -> Sequence[CallUsage]:
        await threads.add_usage(thread_id, calls)
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
        case _:
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
    """The start, the usage, a failure and the end of the turn."""
    seq = turn.seq
    match event:
        case TurnBegan():
            turn_id = uuid.uuid4().hex[:12]
            return [TurnStarted(seq=seq.next(), thread_id=turn.thread_id, turn_id=turn_id)]
        case TurnUsage():
            return [_usage(event, turn)]
        case TurnFailed(reason=reason, correlation_id=correlation_id):
            message = message_for(reason)
            return [ErrorEvent(seq=seq.next(), message=message, correlation_id=correlation_id)]
        case TurnDone():
            return [TurnFinished(seq=seq.next())]
        case _:
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


def _usage(event: TurnUsage, turn: _Turn) -> Usage:
    pricing = turn.runtime.pricing
    return Usage(
        seq=turn.seq.next(),
        turn=summarize(event.turn, pricing),
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
