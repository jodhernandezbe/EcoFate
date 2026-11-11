"""The one turn runner: runs an agent turn and yields transport-neutral events.

Every front end (the web API now, a background worker later) runs turns only through
``execute_turn`` and presents its ``TurnEvent``s in its own way. Nothing here knows about HTTP,
SSE, wire schemas, step labels or user-facing text.
"""

from __future__ import annotations

from app.telemetry import TurnSegment
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
from app.turns.failures import (
    FailureReason,
    KeysUnavailableError,
    StopRequestedError,
    classify,
    new_correlation_id,
    resumable,
)
from app.turns.keys import TurnKeys, load_turn_keys
from app.turns.runner import TurnRequest, TurnServices, TurnSettings, execute_turn, pending_steps

__all__ = [
    "AgentStarted",
    "AssistantText",
    "ConfirmationNeeded",
    "FailureReason",
    "KeysUnavailableError",
    "ScopePassed",
    "StopRequestedError",
    "ScopeRedirect",
    "TextDelta",
    "ToolCalls",
    "ToolFinished",
    "ToolResults",
    "ToolStarted",
    "TurnBegan",
    "TurnDone",
    "TurnEvent",
    "TurnFailed",
    "TurnKeys",
    "TurnRequest",
    "TurnSegment",
    "TurnServices",
    "TurnSettings",
    "TurnUsage",
    "classify",
    "execute_turn",
    "load_turn_keys",
    "new_correlation_id",
    "pending_steps",
    "resumable",
]
