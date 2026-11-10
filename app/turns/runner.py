"""Run one agent turn and yield transport-neutral ``TurnEvent``s.

The runner owns everything that *runs* a turn: reading the turn's keys and giving them to the
tools for the turn only, building the agent, the run configuration and its callbacks, the
session span, usage recording and failure classification. How the events are shown (sequence
numbers, labels, messages, workspace) is the caller's job.

A failure in the caller's handling of an event can be thrown back into the generator
(``athrow``); it is classified and reported like any failure of the turn itself.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator, Awaitable, Callable, Generator, Mapping, Sequence
from contextlib import AbstractContextManager, aclosing, contextmanager, nullcontext
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import cast

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph
from pydantic import SecretStr

from agent.completion import CompletionGuard
from agent.graph import build_agent
from agent.guardrails import REDIRECT_NAME, ScopeGuard
from agent.state import AgentState
from app.telemetry import SessionSpan, TurnSegment, run_tracer, session_span
from app.turns.events import (
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
    TurnUsage,
)
from app.turns.failures import SETUP_REASONS, FailureReason, classify, new_correlation_id
from app.turns.history import not_run_results
from app.turns.keys import TurnKeys, provided
from app.usage_meter import CallUsage, UsageRecorder
from config.telemetry import TelemetrySettings
from config.ui import ModelPrice
from tools.schemas import ConfirmationRequest

logger = logging.getLogger("app.turns")
Agent = CompiledStateGraph[AgentState, None, AgentState, AgentState]
UserValues = tuple[Mapping[str, float], frozenset[str]]


@dataclass(frozen=True)
class TurnRequest:
    """One turn's input.

    Attributes:
        thread_id: The conversation (the checkpointer's thread and the span's session id).
        question: What the user typed, as recorded on the span.
        message: The message the agent receives (the question, or the answers to a request).
        note: The note on the user's answers for the agent; empty when there is none.
        resume: Continue the thread's interrupted run from its last checkpoint instead of
            sending ``message`` (the message and note are then not used).
        segment: The turn and resume index the span records; None records neither.
        user_id: The signed-in user's opaque id, recorded on the span; None (the command line)
            records none. Never an email.
        checkpoint_id: The checkpointer's key for the thread when it is not ``thread_id`` (the
            web program scopes it to the owner); None uses ``thread_id``.
    """

    thread_id: str
    question: str
    message: str
    note: str = ""
    resume: bool = False
    segment: TurnSegment | None = None
    user_id: str | None = None
    checkpoint_id: str | None = None

    @property
    def checkpoint(self) -> str:
        """The key the thread's history is stored under."""
        return self.checkpoint_id or self.thread_id


@dataclass(frozen=True)
class TurnSettings:
    """What does not change between turns.

    Attributes:
        recursion_limit: LangGraph step limit of the run.
        model_name: Configured model name (the key into ``pricing``).
        pricing: Model name -> token prices; a model without an entry is unpriced.
        scope_guard: Checks that each user turn is on topic before the agent runs, when given.
        completion_guard: Sends a reply that only announced its next steps back to work.
        system_prompt: The agent's system prompt; None keeps the standard one.
        telemetry: Monitoring settings; each turn is then recorded as a span. None records none.
    """

    recursion_limit: int
    model_name: str = ""
    pricing: Mapping[str, ModelPrice] = field(default_factory=lambda: MappingProxyType({}))
    scope_guard: ScopeGuard | None = None
    completion_guard: CompletionGuard | None = None
    system_prompt: str | None = None
    telemetry: TelemetrySettings | None = None


@dataclass(frozen=True)
class TurnServices:
    """The collaborators of one turn, injected by the front end.

    Attributes:
        load_keys: Reads the turn's keys (raises ``KeysUnavailableError`` when it cannot).
        build_model: Builds the chat model from the turn's model key.
        checkpointer: Keeps the thread's history.
        user_values: Returns the values the user supplied and the entries they declined.
        record_usage: Stores the turn's model calls and returns every call of the thread so far.
    """

    load_keys: Callable[[], TurnKeys]
    build_model: Callable[[SecretStr], BaseChatModel]
    checkpointer: BaseCheckpointSaver[str]
    user_values: Callable[[], Awaitable[UserValues]]
    record_usage: Callable[[Sequence[CallUsage]], Awaitable[Sequence[CallUsage]]]


async def execute_turn(
    request: TurnRequest,
    services: TurnServices,
    settings: TurnSettings,
) -> AsyncGenerator[TurnEvent]:
    """Run one turn and yield its events: ``TurnBegan`` first, ``TurnUsage`` and ``TurnDone`` last.

    A failure becomes one ``TurnFailed`` with a reason code and a correlation id (the details
    are logged, redacted, under that id), followed by the usage of the calls made so far. The
    keys are provided only while the agent runs and released on every exit path.
    """
    recorder, outcome = UsageRecorder(settings.model_name), _Outcome()
    with _turn_span(request, settings) as span:
        yield TurnBegan()
        # The failure capture wraps this generator's own yields, so that a failure the caller
        # throws in (``athrow``) lands inside it. The inner capture sits inside ``provided``:
        # a failure is logged while the turn's keys are still redacted from the logs.
        # ``aclosing`` closes each stage at once, in this context, when the caller stops early.
        with _captured(outcome):
            keys = services.load_keys()
            with provided(keys), _captured(outcome):  # the tools see the keys, the logs never do
                model = services.build_model(keys.openai)
                agent_run = _agent_events(request, model, services, settings, recorder)
                async with aclosing(agent_run) as events:
                    async for event in events:
                        yield event
        if outcome.failure is not None:
            span.fail()
            yield outcome.failure
        async with aclosing(_closing_events(services, settings, recorder, span)) as closing:
            async for event in closing:
                yield event


def _turn_span(request: TurnRequest, settings: TurnSettings) -> AbstractContextManager[SessionSpan]:
    """The trace of one turn (session id = the thread); records nothing without monitoring."""
    telemetry = settings.telemetry
    if telemetry is None:
        return nullcontext(SessionSpan.inactive())
    return session_span(
        telemetry,
        telemetry.spans.web_turn,
        request.thread_id,
        request.question,
        settings.model_name,
        request.segment,
        request.user_id,
    )


async def _closing_events(
    services: TurnServices,
    settings: TurnSettings,
    recorder: UsageRecorder,
    span: SessionSpan,
) -> AsyncGenerator[TurnEvent]:
    """``TurnUsage`` then ``TurnDone``; a store failure here becomes ``TurnFailed`` instead."""
    try:
        session = tuple(await services.record_usage(recorder.calls))
    except Exception as error:
        span.fail()
        yield failed(error)
    else:
        span.record_usage(recorder.calls, settings.pricing)
        span.record_usage(session, settings.pricing, session=True)
        yield TurnUsage(turn=tuple(recorder.calls), session=session)
    yield TurnDone()


@dataclass
class _Outcome:
    """The failure of a turn's run, once one was captured (logged where it happened)."""

    failure: TurnFailed | None = None


@contextmanager
def _captured(outcome: _Outcome) -> Generator[None]:
    """Turn any failure inside the block into ``outcome.failure``, logged there and then."""
    try:
        yield
    except Exception as error:
        outcome.failure = failed(error)


def failed(error: Exception) -> TurnFailed:
    """The failure event of ``error``: a reason and an id; details only in the (redacted) log."""
    event = TurnFailed(reason=classify(error), correlation_id=new_correlation_id())
    if event.reason == FailureReason.UNEXPECTED:
        logger.exception("turn failed (%s)", event.correlation_id)
    elif event.reason not in SETUP_REASONS:  # a known provider failure: no traceback needed
        logger.warning("turn failed (%s): %s", event.correlation_id, type(error).__name__)
    return event


async def _agent_events(
    request: TurnRequest,
    model: BaseChatModel,
    services: TurnServices,
    settings: TurnSettings,
    recorder: UsageRecorder,
) -> AsyncGenerator[TurnEvent]:
    agent = _build(model, services, settings)
    config = await _run_config(request, services, settings, recorder)
    yield AgentStarted()
    # A resume sends no input: the run continues from the last checkpoint with a fresh step
    # budget (the recursion limit applies to each run), so nothing finished runs again.
    inputs = None if request.resume else await _new_message(agent, config, request)
    async for mode, payload in agent.astream(inputs, config, stream_mode=["messages", "updates"]):
        for event in translate(mode, payload):
            yield event


async def _new_message(agent: Agent, config: RunnableConfig, request: TurnRequest) -> AgentState:
    """The input of a new message; first, tool calls an abandoned turn left without a result
    get a "not run" result, so the history the model receives is valid."""
    state = await agent.aget_state(config)
    closing = not_run_results(cast(AgentState, state.values).get("messages", []))
    if closing:
        await agent.aupdate_state(config, {"messages": closing}, as_node="tools")
    return {"messages": [HumanMessage(content=request.message)], "answers_note": request.note}


async def pending_steps(
    thread_id: str,
    services: TurnServices,
    settings: TurnSettings,
) -> tuple[str, ...]:
    """The graph nodes the thread's last checkpoint would run next (empty when it finished).

    Builds the agent with the stored model key but calls no model and runs no tool.

    Raises:
        KeysUnavailableError: The keychain cannot be used, or no model key is stored.
    """
    keys = services.load_keys()
    agent = _build(services.build_model(keys.openai), services, settings)
    snapshot = await agent.aget_state({"configurable": {"thread_id": thread_id}})
    return tuple(snapshot.next)


def _build(model: BaseChatModel, services: TurnServices, settings: TurnSettings) -> Agent:
    """The agent of one turn: the model, the thread history and the configured checks."""
    return build_agent(
        model,
        checkpointer=services.checkpointer,
        scope_guard=settings.scope_guard,
        completion_guard=settings.completion_guard,
        system_prompt=settings.system_prompt,
    )


def _callbacks(settings: TurnSettings, recorder: UsageRecorder) -> list[BaseCallbackHandler]:
    """What observes the run: the usage recorder and, when monitoring is on, the tracer."""
    tracer = run_tracer(settings.telemetry) if settings.telemetry is not None else None
    return [recorder, *([tracer] if tracer is not None else [])]


async def _run_config(
    request: TurnRequest,
    services: TurnServices,
    settings: TurnSettings,
    recorder: UsageRecorder,
) -> RunnableConfig:
    """The run configuration: the thread, the user's values for the tools, and the observers."""
    supplied, declined = await services.user_values()
    return {
        "recursion_limit": settings.recursion_limit,
        "configurable": {
            "thread_id": request.checkpoint,
            "user_values": {"supplied": dict(supplied), "declined": sorted(declined)},
        },
        "callbacks": _callbacks(settings, recorder),
    }


# --- the graph's stream as turn events ----------------------------------------------------------


def translate(mode: str, payload: object) -> list[TurnEvent]:
    """The turn events of one item of ``astream(..., stream_mode=["messages", "updates"])``."""
    if mode == "messages":
        return _text_events(payload)
    update = cast(Mapping[str, object], payload)
    return [
        *_scope_events(update),
        *_model_events(update),
        *_tool_events(update),
        *_confirmation_events(update),
    ]


def _text_events(payload: object) -> list[TurnEvent]:
    chunk, metadata = cast(tuple[object, Mapping[str, object]], payload)
    if not isinstance(chunk, AIMessageChunk) or metadata.get("langgraph_node") != "model":
        return []
    return [TextDelta(chunk.text)] if chunk.text else []


def _node_messages(update: Mapping[str, object], node: str) -> list[object]:
    node_update = update.get(node)
    if not isinstance(node_update, Mapping):
        return []
    return list(cast(Mapping[str, list[object]], node_update).get("messages", []))


def _scope_events(update: Mapping[str, object]) -> list[TurnEvent]:
    """The scope check's outcome: a redirect (its reply texts) or a pass to the agent."""
    if "scope" not in update:
        return []
    texts = tuple(
        m.text
        for m in _node_messages(update, "scope")
        if isinstance(m, AIMessage) and m.name == REDIRECT_NAME
    )
    return [ScopeRedirect(texts)] if texts else [ScopePassed()]


def _model_events(update: Mapping[str, object]) -> list[TurnEvent]:
    events: list[TurnEvent] = []
    for message in _node_messages(update, "model"):
        if not isinstance(message, AIMessage):
            continue
        events.extend(ToolStarted(str(call["id"]), call["name"]) for call in message.tool_calls)
        if message.tool_calls:
            events.append(ToolCalls(message))
        # A model that streams has already sent this text as deltas; the final message is
        # for models that do not stream, and only the answer (no tool calls) counts.
        elif message.text:
            events.append(AssistantText(message.text))
    return events


def _tool_events(update: Mapping[str, object]) -> list[TurnEvent]:
    results = tuple(m for m in _node_messages(update, "tools") if isinstance(m, ToolMessage))
    finished: list[TurnEvent] = [
        ToolFinished(m.tool_call_id, m.name or "", m.status == "error", m) for m in results
    ]
    return [*finished, ToolResults(results)] if results else []


def _confirmation_events(update: Mapping[str, object]) -> list[TurnEvent]:
    """The open request when the turn stopped to ask for missing values."""
    ask = update.get("ask")
    if not isinstance(ask, dict):
        return []
    pending = cast(Mapping[str, object], ask).get("pending")
    if not isinstance(pending, dict):
        return []
    return [ConfirmationNeeded(cast(ConfirmationRequest, pending))]
