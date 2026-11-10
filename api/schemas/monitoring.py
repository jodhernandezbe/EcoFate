"""Wire models of the monitoring endpoints: sessions and their model and tool calls.

Every figure is read from what the telemetry recorded; one that the trace does not hold is
``None`` (or ``unknown``), never a zero or an estimate made up here.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from api.schemas.base import ContractModel

MonitoringState = Literal["ok", "not_configured", "unavailable", "unauthorized"]
CostStatus = Literal["estimate", "lower_bound", "unpriced", "unknown"]
Outcome = Literal["ok", "error", "unknown"]


class SessionStep(ContractModel):
    """One model call or tool call of a turn, in start order.

    Attributes:
        kind: ``model`` or ``tool``.
        name: The model name, or the tool's step label.
        offset_ms: Start, in milliseconds after the turn started.
        duration_ms: How long it took.
        outcome: ``error`` when the call raised.
        input_tokens: Input tokens (model calls that reported usage).
        output_tokens: Output tokens (model calls that reported usage).
    """

    kind: Literal["model", "tool"]
    name: str
    offset_ms: int = Field(ge=0)
    duration_ms: int | None = Field(ge=0)
    outcome: Outcome
    input_tokens: int | None = Field(ge=0)
    output_tokens: int | None = Field(ge=0)


class SessionTurn(ContractModel):
    """One turn (web) or run (command line) of a session, with its steps.

    ``trace_url`` opens the trace in Logfire; None when the project is unknown.
    """

    trace_id: str
    started_at: str
    question: str | None
    duration_ms: int | None = Field(ge=0)
    outcome: Outcome
    steps: list[SessionStep]
    trace_url: str | None


class SessionSummary(ContractModel):
    """A session as listed: a web thread or one command-line run.

    Counts come from the trace's spans; tokens and cost are the sums of the turns' recorded
    usage and are None when any turn did not record them. ``cost_status`` is the weakest status
    of its turns (``unknown`` when one is missing). ``account`` is the email of the user who ran
    it, looked up in the application database from the opaque user id on the spans; None when the
    spans carry none (a command-line run) or the account no longer exists.
    """

    session_id: str
    started_at: str
    question: str | None
    model: str | None
    turns: int = Field(ge=1)
    model_calls: int | None = Field(ge=0)
    tool_calls: int | None = Field(ge=0)
    input_tokens: int | None = Field(ge=0)
    cached_input_tokens: int | None = Field(ge=0)
    output_tokens: int | None = Field(ge=0)
    cost_usd: float | None = Field(ge=0)
    cost_status: CostStatus
    duration_ms: int | None = Field(ge=0)
    outcome: Outcome
    account: str | None


class SessionsResponse(ContractModel):
    """``GET /api/v1/monitoring/sessions``: recent sessions, newest first, or why there are none.

    ``message`` is a user-safe reason when ``state`` is not ``ok``.
    """

    state: MonitoringState
    message: str | None
    sessions: list[SessionSummary]


class SessionDetailResponse(ContractModel):
    """``GET /api/v1/monitoring/sessions/{session_id}``: one session and its turns."""

    state: MonitoringState
    message: str | None
    session: SessionSummary | None
    turns: list[SessionTurn]
