"""Run the agent for one chat turn and translate its stream into contract events.

The chat model is built per turn from the key read once from the vault; the key is never kept
past the turn. All scientific work stays in the agent and its tools.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncGenerator, Callable, Generator, Mapping
from contextlib import AbstractContextManager, ExitStack, contextmanager, nullcontext
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import cast

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from pydantic import SecretStr

from agent.completion import CompletionGuard
from agent.graph import build_agent
from agent.guardrails import REDIRECT_NAME, ScopeGuard
from agent.missing import ask_text
from agent.state import AgentState
from api.core.exceptions import GENERIC_ERROR, new_correlation_id
from api.core.logging_filter import protect_secrets
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
from api.services.provider_errors import explain
from api.services.state_serializer import build_workspace
from api.services.threads import ThreadStore
from api.services.usage_meter import summarize
from app.key_vault import KeychainUnavailableError, ServiceKeys, stored_key
from app.telemetry import SessionSpan, run_tracer, session_span
from app.usage_meter import UsageRecorder
from config.telemetry import TelemetrySettings
from config.ui import ModelPrice
from tools.credentials import HOLDERS
from tools.schemas import ConfirmationRequest

logger = logging.getLogger("api.agent_runner")
ModelFactory = Callable[[SecretStr], BaseChatModel]
NO_KEY_MESSAGE = "Add your OpenAI API key in Settings (the gear icon) to start."


Agent = CompiledStateGraph[AgentState, None, AgentState, AgentState]


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


class UserFacingError(Exception):
    """A failure whose message is safe and useful to show the user as is."""


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
class TurnKeys:
    """The keys read for one turn: the model key, and the service keys when stored."""

    openai: SecretStr
    census: SecretStr | None
    comptox: SecretStr | None

    def values(self) -> list[str]:
        """The raw values, for log protection (never stored anywhere)."""
        keys = (self.openai, self.census, self.comptox)
        return [key.get_secret_value() for key in keys if key is not None]


def _load_keys(keys: ServiceKeys) -> TurnKeys:
    """Read each stored key once. Only the model key is required."""
    try:
        openai = keys.vault("openai").load()
    except KeychainUnavailableError as error:
        raise UserFacingError(str(error)) from error
    if openai is None:
        raise UserFacingError(NO_KEY_MESSAGE)
    return TurnKeys(
        openai=openai,
        census=stored_key(keys.vault("census")),
        comptox=stored_key(keys.vault("comptox")),
    )


@contextmanager
def _provided(keys: TurnKeys) -> Generator[None]:
    """Give each key to the tools that need it, and keep them out of the logs, for the turn."""
    with ExitStack() as stack:
        stack.enter_context(protect_secrets(keys.values()))
        for name, key in (
            ("openai", keys.openai),
            ("census", keys.census),
            ("comptox", keys.comptox),
        ):
            if key is not None:
                stack.enter_context(HOLDERS[name].provide(key))
        yield


def _token_events(payload: object, seq: EventSequence) -> list[StreamEvent]:
    chunk, metadata = cast(tuple[object, Mapping[str, object]], payload)
    if not isinstance(chunk, AIMessageChunk) or metadata.get("langgraph_node") != "model":
        return []
    return [Token(seq=seq.next(), text=chunk.text)] if chunk.text else []


def _node_messages(update: Mapping[str, object], node: str) -> list[object]:
    node_update = update.get(node)
    if not isinstance(node_update, Mapping):
        return []
    return list(cast(Mapping[str, list[object]], node_update).get("messages", []))


def _label(labels: Mapping[str, str], tool_name: str) -> str:
    return labels.get(tool_name, tool_name)


def _tool_starts(
    message: AIMessage,
    seq: EventSequence,
    labels: Mapping[str, str],
) -> list[StreamEvent]:
    return [
        ToolStatus(
            seq=seq.next(),
            phase="started",
            call_id=str(call["id"]),
            tool_name=call["name"],
            label=_label(labels, call["name"]),
        )
        for call in message.tool_calls
    ]


def _tool_finish(message: ToolMessage, seq: EventSequence, labels: Mapping[str, str]) -> ToolStatus:
    name = message.name or ""
    return ToolStatus(
        seq=seq.next(),
        phase="finished",
        call_id=message.tool_call_id,
        tool_name=name,
        label=_label(labels, name),
        status="error" if message.status == "error" else "ok",
    )


def _scope_events(update: Mapping[str, object], seq: EventSequence) -> list[StreamEvent]:
    """The scope check's outcome: a pivot (the redirect text) or a pass to the agent."""
    if "scope" not in update:
        return []
    redirects = [
        m
        for m in _node_messages(update, "scope")
        if isinstance(m, AIMessage) and m.name == REDIRECT_NAME
    ]
    if not redirects:
        return [ScopeDecision(seq=seq.next(), in_scope=True)]
    return [
        ScopeDecision(seq=seq.next(), in_scope=False),
        *(GuardrailPivotResponse(seq=seq.next(), text=m.text) for m in redirects),
    ]


def _update_events(
    payload: object,
    seq: EventSequence,
    labels: Mapping[str, str],
) -> list[StreamEvent]:
    update = cast(Mapping[str, object], payload)
    events: list[StreamEvent] = _scope_events(update, seq)
    for message in _node_messages(update, "model"):
        if not isinstance(message, AIMessage):
            continue
        events.extend(_tool_starts(message, seq, labels))
        # A model that streams has already sent this text as tokens; the final message is
        # for models that do not stream, and only the answer (no tool calls) counts.
        if message.text and not message.tool_calls:
            events.append(AssistantMessage(seq=seq.next(), text=message.text))
    for message in _node_messages(update, "tools"):
        if isinstance(message, ToolMessage):
            events.append(_tool_finish(message, seq, labels))
    return events


def _translate(
    mode: str,
    payload: object,
    seq: EventSequence,
    labels: Mapping[str, str],
) -> list[StreamEvent]:
    if mode == "messages":
        return _token_events(payload, seq)
    return _update_events(payload, seq, labels)


def _build(model: BaseChatModel, threads: ThreadStore, runtime: AgentRuntime) -> Agent:
    """The agent of one turn: the model, the thread history and the configured checks."""
    return build_agent(
        model,
        checkpointer=threads.checkpointer,
        scope_guard=runtime.scope_guard,
        completion_guard=runtime.completion_guard,
        system_prompt=runtime.system_prompt,
    )


def _callbacks(runtime: AgentRuntime, recorder: UsageRecorder) -> list[BaseCallbackHandler]:
    """What observes the run: the usage recorder and, when monitoring is on, the tracer."""
    tracer = run_tracer(runtime.telemetry) if runtime.telemetry is not None else None
    return [recorder, *([tracer] if tracer is not None else [])]


def _run_config(
    request: ChatRequest,
    threads: ThreadStore,
    runtime: AgentRuntime,
    recorder: UsageRecorder,
) -> RunnableConfig:
    """The run configuration: the thread, its answers for the tools, and the recorder."""
    supplied, declined = threads.answers(request.thread_id)
    return {
        "recursion_limit": runtime.recursion_limit,
        "configurable": {
            "thread_id": request.thread_id,
            "user_values": {"supplied": supplied, "declined": sorted(declined)},
        },
        "callbacks": _callbacks(runtime, recorder),
    }


def _confirmation_events(
    payload: object,
    request: ChatRequest,
    threads: ThreadStore,
    seq: EventSequence,
) -> list[StreamEvent]:
    """The question and the open request when the turn stopped to ask for missing values."""
    update = cast(Mapping[str, object], payload)
    ask = update.get("ask")
    if not isinstance(ask, dict):
        return []
    pending = cast(Mapping[str, object], ask).get("pending")
    if not isinstance(pending, dict):
        return []
    request_data = cast(ConfirmationRequest, pending)
    threads.set_pending(request.thread_id, request_data)
    question = ask_text(request_data)
    return [
        AssistantMessage(seq=seq.next(), text=question),
        request_event(seq.next(), request_data),
    ]


async def _agent_events(
    request: ChatRequest,
    model: BaseChatModel,
    threads: ThreadStore,
    runtime: AgentRuntime,
    seq: EventSequence,
    recorder: UsageRecorder,
    plan: TurnPlan,
) -> AsyncGenerator[StreamEvent]:
    agent = _build(model, threads, runtime)
    config = _run_config(request, threads, runtime, recorder)
    supplied, _ = threads.answers(request.thread_id)
    if supplied:  # the user's answers show on the card now, not only once a tool runs again
        for event in _rebuild(request, threads, runtime, seq):
            yield event
    inputs: AgentState = {
        "messages": [HumanMessage(content=plan.message)],
        "answers_note": plan.note,
    }
    async for mode, payload in agent.astream(inputs, config, stream_mode=["messages", "updates"]):
        for event in _translate(mode, payload, seq, runtime.step_labels):
            yield event
        if mode == "updates":
            for event in _workspace_events(payload, request, threads, runtime, seq):
                yield event
            for event in _confirmation_events(payload, request, threads, seq):
                yield event


def _tool_messages(update: Mapping[str, object]) -> list[BaseMessage]:
    """The tool calls and tool results of one graph update."""
    calls = [
        m for m in _node_messages(update, "model") if isinstance(m, AIMessage) and m.tool_calls
    ]
    results = [m for m in _node_messages(update, "tools") if isinstance(m, ToolMessage)]
    return [*calls, *results]


def _workspace_events(
    payload: object,
    request: ChatRequest,
    threads: ThreadStore,
    runtime: AgentRuntime,
    seq: EventSequence,
) -> list[StreamEvent]:
    """The workspace rebuilt from the thread's tool messages after a batch of tool results."""
    messages = _tool_messages(cast(Mapping[str, object], payload))
    if runtime.workspace_rules is None or not messages:
        return []
    threads.add_tool_messages(request.thread_id, messages)
    if not any(isinstance(m, ToolMessage) for m in messages):
        return []
    return _rebuild(request, threads, runtime, seq)


def _rebuild(
    request: ChatRequest,
    threads: ThreadStore,
    runtime: AgentRuntime,
    seq: EventSequence,
) -> list[StreamEvent]:
    """Rebuild the workspace from the tool messages and the user's answers, if it changed."""
    if runtime.workspace_rules is None:
        return []
    previous = threads.workspace(request.thread_id)
    supplied, _ = threads.answers(request.thread_id)
    state = build_workspace(
        threads.tool_messages(request.thread_id),
        runtime.workspace_rules,
        previous,
        supplied,
    )
    if state == previous:
        return []
    threads.set_workspace(request.thread_id, state)
    return [WorkspaceUpdate(seq=seq.next(), state=state)]


def _error(seq: EventSequence, message: str) -> ErrorEvent:
    return ErrorEvent(seq=seq.next(), message=message, correlation_id=new_correlation_id())


def _usage_event(
    seq: EventSequence,
    request: ChatRequest,
    threads: ThreadStore,
    runtime: AgentRuntime,
    recorder: UsageRecorder,
    span: SessionSpan,
) -> Usage:
    threads.add_usage(request.thread_id, recorder.calls)
    session_calls = threads.session_calls(request.thread_id)
    span.record_usage(recorder.calls, runtime.pricing)
    span.record_usage(session_calls, runtime.pricing, session=True)
    return Usage(
        seq=seq.next(),
        turn=summarize(recorder.calls, runtime.pricing),
        session=summarize(session_calls, runtime.pricing),
    )


def _failure(seq: EventSequence, error: Exception) -> ErrorEvent:
    """The error event of an unexpected failure: a fixed message, details only in the log."""
    explained = explain(error)
    failure = _error(seq, explained or GENERIC_ERROR)
    if explained is None:
        logger.exception("turn failed (%s)", failure.correlation_id)
    else:  # a known provider failure: its class and status are enough, no traceback
        logger.warning("turn failed (%s): %s", failure.correlation_id, type(error).__name__)
    return failure


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
    with _turn_span(request, runtime) as span:
        async for event in _turn_events(request, keys, threads, runtime, plan, span):
            yield event


def _turn_span(request: ChatRequest, runtime: AgentRuntime) -> AbstractContextManager[SessionSpan]:
    """The trace of one turn (session id = the thread); records nothing without monitoring."""
    settings = runtime.telemetry
    if settings is None:
        return nullcontext(SessionSpan.inactive())
    name = settings.spans.web_turn
    return session_span(settings, name, request.thread_id, request.message, runtime.model_name)


async def _turn_events(
    request: ChatRequest,
    keys: ServiceKeys,
    threads: ThreadStore,
    runtime: AgentRuntime,
    plan: TurnPlan | None,
    span: SessionSpan,
) -> AsyncGenerator[StreamEvent]:
    seq = EventSequence()
    recorder = UsageRecorder(runtime.model_name)
    yield TurnStarted(seq=seq.next(), thread_id=request.thread_id, turn_id=uuid.uuid4().hex[:12])
    try:
        turn_keys = _load_keys(keys)
        model = runtime.build_model(turn_keys.openai)
        with _provided(turn_keys):  # the tools see this turn's keys, and the logs never do
            turn = plan or TurnPlan(message=request.message, note="")
            async for event in _agent_events(request, model, threads, runtime, seq, recorder, turn):
                yield event
    except UserFacingError as error:
        span.fail()
        yield _error(seq, str(error))
    except Exception as error:
        span.fail()
        yield _failure(seq, error)
    yield _usage_event(seq, request, threads, runtime, recorder, span)
    yield TurnFinished(seq=seq.next())
