"""Chat contract: the turn request and the server-sent events of one turn."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, RootModel, StrictFloat, StrictInt, model_validator

from api.schemas.base import ContractModel
from api.schemas.workspace import WorkspaceState

THREAD_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
ThreadId = Annotated[str, Field(pattern=THREAD_ID_PATTERN)]


class EntryAnswer(ContractModel):
    """The user's answer to one missing value: a number in one of its units, or a decline."""

    entry_id: str = Field(min_length=1, max_length=200)
    decision: Literal["supply", "decline"]
    number: StrictFloat | StrictInt | None = None
    unit: str | None = Field(default=None, max_length=40)


class ConfirmationAnswers(ContractModel):
    """Answers to an open confirmation request: every entry, each answered once."""

    request_id: str = Field(min_length=1, max_length=64)
    entries: list[EntryAnswer] = Field(min_length=1, max_length=50)


class ChatRequest(ContractModel):
    """Body of ``POST /api/v1/chat/stream``: a message, or answers to an open request."""

    thread_id: ThreadId
    message: str = Field(default="", max_length=8000)
    answers: ConfirmationAnswers | None = None

    @model_validator(mode="after")
    def _message_or_answers(self) -> ChatRequest:
        if self.answers is None and not self.message.strip():
            raise ValueError("a message or answers to the open request are required")
        if self.answers is not None and self.message.strip():
            raise ValueError("a turn carries either a message or answers, not both")
        return self


class _Event(ContractModel):
    seq: int = Field(ge=0, description="Position of the event in its stream, from 0.")


class TurnStarted(_Event):
    type: Literal["turn_started"] = "turn_started"
    thread_id: str
    turn_id: str
    resumed: bool = False  # True when the turn continues from where it was interrupted


InterruptionReason = Literal[
    "out_of_credits",
    "rate_limited",
    "bad_key",
    "provider_down",
    "step_limit",
    "worker_lost",
]


class TurnInterruption(ContractModel):
    """Why a turn stopped before its answer, whether it can be resumed, and what to do."""

    reason: InterruptionReason
    resumable: bool
    message: str


class TurnInterrupted(_Event):
    """The turn stopped for a reason the user can fix; it may be resumed where it stopped."""

    type: Literal["turn_interrupted"] = "turn_interrupted"
    reason: InterruptionReason
    resumable: bool
    message: str


class ScopeDecision(_Event):
    type: Literal["scope"] = "scope"
    in_scope: bool


class GuardrailPivotResponse(_Event):
    """The in-character redirect sent instead of running the agent on an off-topic turn."""

    type: Literal["guardrail_pivot"] = "guardrail_pivot"
    text: str


class ToolStatus(_Event):
    """A tool step: ``started`` carries the label; ``finished`` adds the outcome."""

    type: Literal["tool_status"] = "tool_status"
    phase: Literal["started", "finished"]
    call_id: str
    tool_name: str
    label: str
    status: Literal["ok", "error"] | None = None


class WorkspaceUpdate(_Event):
    type: Literal["workspace_update"] = "workspace_update"
    state: WorkspaceState


class Token(_Event):
    type: Literal["token"] = "token"
    text: str


class AssistantMessage(_Event):
    type: Literal["assistant_message"] = "assistant_message"
    text: str


class UsageTotals(ContractModel):
    """Token counts and estimated cost (USD) of a turn or a session.

    ``cost_status`` is ``estimate`` when every call was priced, ``lower_bound`` when some call
    reported no usage, and ``unpriced`` (``cost_usd`` null) when the model has no price.
    """

    calls: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    cached_input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    complete: bool
    cost_usd: float | None
    cost_status: Literal["estimate", "lower_bound", "unpriced"]
    priced_on: str | None


class ThreadMessage(ContractModel):
    """One user or assistant message of a thread (text only, no tool calls or results)."""

    role: Literal["user", "assistant"]
    text: str


class ThreadSnapshot(ContractModel):
    """A held thread as of its last finished turn (``GET /api/v1/chat/threads/{id}``)."""

    thread_id: str
    messages: list[ThreadMessage]
    workspace: WorkspaceState
    usage: UsageTotals
    confirmation: ConfirmationPrompt | None = None  # the open request, if any
    interrupted: TurnInterruption | None = None  # the latest turn, when it was interrupted


class Usage(_Event):
    type: Literal["usage"] = "usage"
    turn: UsageTotals
    session: UsageTotals


class ErrorEvent(_Event):
    """A user-safe message and the id under which the details were logged."""

    type: Literal["error"] = "error"
    message: str
    correlation_id: str


class TurnFinished(_Event):
    type: Literal["turn_finished"] = "turn_finished"


class MissingValue(ContractModel):
    """One value the assessment needs and could not find, as the user is asked for it."""

    entry_id: str
    quantity: str
    subject: str
    accepted_units: list[str]  # the first is the target unit the analysis uses
    minimum: float  # plausible range in the target unit, inclusive
    maximum: float
    purpose: str


class ConfirmationPrompt(ContractModel):
    """An open request for missing values: what the user is asked, not yet answered."""

    request_id: str
    entries: list[MissingValue]


class ConfirmationRequested(_Event):
    """The turn stopped to ask the user for missing values; the request stays open."""

    type: Literal["confirmation_request"] = "confirmation_request"
    request_id: str
    entries: list[MissingValue]


StreamEvent = Annotated[
    TurnStarted
    | ScopeDecision
    | GuardrailPivotResponse
    | ToolStatus
    | WorkspaceUpdate
    | Token
    | AssistantMessage
    | TurnInterrupted
    | Usage
    | ErrorEvent
    | ConfirmationRequested
    | TurnFinished,
    Field(discriminator="type"),
]


class StreamEventSchema(RootModel[StreamEvent]):
    """Any one event of the stream (used to export the event union)."""
