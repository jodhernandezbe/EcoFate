"""The events of one agent turn, independent of any transport.

Frozen dataclasses with no sequence numbers, labels or user-facing text: numbering, labelling
and wording are the presenter's job. A turn always ends with ``TurnUsage`` (or a ``TurnFailed``
when the usage could not be recorded) and then ``TurnDone``; it always starts with ``TurnBegan``.
"""

from __future__ import annotations

from dataclasses import dataclass

from langchain_core.messages import AIMessage, ToolMessage

from app.turns.failures import FailureReason
from app.usage_meter import CallUsage
from tools.schemas import ConfirmationRequest


@dataclass(frozen=True)
class TurnBegan:
    """The first event of every turn: its span is open, nothing has run yet."""


@dataclass(frozen=True)
class AgentStarted:
    """The keys are provided and the agent is built; the graph is about to run."""


@dataclass(frozen=True)
class TextDelta:
    """A piece of the answer, streamed by the agent's model."""

    text: str


@dataclass(frozen=True)
class AssistantText:
    """The agent's final answer as one message (for models that do not stream)."""

    text: str


@dataclass(frozen=True)
class ToolStarted:
    """The model asked for a tool call."""

    call_id: str
    tool_name: str


@dataclass(frozen=True)
class ToolCalls:
    """The model message that asked for tool calls (for the caller's tool-message history)."""

    message: AIMessage


@dataclass(frozen=True)
class ToolFinished:
    """One tool call returned; ``failed`` when the tool reported an error."""

    call_id: str
    tool_name: str
    failed: bool
    message: ToolMessage


@dataclass(frozen=True)
class ToolResults:
    """A batch of tool results is complete: every ``ToolFinished`` of one graph step was sent."""

    messages: tuple[ToolMessage, ...]


@dataclass(frozen=True)
class ScopePassed:
    """The scope check let the turn through to the agent."""


@dataclass(frozen=True)
class ScopeRedirect:
    """The scope check stopped the turn; ``texts`` are its redirect replies."""

    texts: tuple[str, ...]


@dataclass(frozen=True)
class ConfirmationNeeded:
    """The turn stopped to ask the user for missing values."""

    request: ConfirmationRequest


@dataclass(frozen=True)
class TurnUsage:
    """Every model call of the turn, and of the thread so far (including this turn)."""

    turn: tuple[CallUsage, ...]
    session: tuple[CallUsage, ...]


@dataclass(frozen=True)
class TurnFailed:
    """The turn failed; the details are only in the log, under ``correlation_id``."""

    reason: FailureReason
    correlation_id: str


@dataclass(frozen=True)
class TurnDone:
    """The last event of every turn."""


TurnEvent = (
    TurnBegan
    | AgentStarted
    | TextDelta
    | AssistantText
    | ToolStarted
    | ToolCalls
    | ToolFinished
    | ToolResults
    | ScopePassed
    | ScopeRedirect
    | ConfirmationNeeded
    | TurnUsage
    | TurnFailed
    | TurnDone
)
