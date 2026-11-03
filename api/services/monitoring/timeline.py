"""A session's turns with their model calls and tool calls in start order.

Built from the rows of the detail query: the turn spans, and the model and tool call spans of
their traces. A call's figures come from its span; a tool shows under its configured step label.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime
from urllib.parse import quote

from api.schemas.monitoring import Outcome, SessionStep, SessionTurn
from api.services.monitoring.client import Project
from api.services.monitoring.rows import (
    Row,
    TurnRecord,
    amount,
    instant,
    parse_turn,
    text,
    token_usage,
)
from api.services.monitoring.sessions import iso
from config.telemetry import TelemetrySettings

_PLACEHOLDERS = ("organization", "project", "trace_id")


def trace_url(template: str, project: Project | None, trace_id: str) -> str | None:
    """The link that opens a trace in Logfire; None when the project is not known."""
    if project is None or not project.organization or not project.name:
        return None
    values = {"organization": project.organization, "project": project.name, "trace_id": trace_id}
    url = template
    for name in _PLACEHOLDERS:
        url = url.replace("{" + name + "}", quote(values[name], safe=""))
    return url


def _failed(row: Row) -> Outcome:
    status = text(row, "status")
    if status is None:
        return "unknown"
    raised = row.get("is_exception") in (True, "true", "True")
    return "error" if status == "ERROR" or raised else "ok"


def _milliseconds(seconds: float | None) -> int | None:
    return round(seconds * 1000) if seconds is not None else None


def _step(
    row: Row,
    turn_start: datetime,
    settings: TelemetrySettings,
    labels: Mapping[str, str],
) -> tuple[datetime, SessionStep] | None:
    started = instant(row, "start_timestamp")
    if started is None:
        return None
    is_model = row.get("op") == settings.bridge.model_operation
    tool = text(row, "tool") or text(row, "span_name") or "tool"
    tokens_in, tokens_out = token_usage(row, "usage") if is_model else (None, None)
    return started, SessionStep(
        kind="model" if is_model else "tool",
        name=(text(row, "model") or "model") if is_model else labels.get(tool, tool),
        offset_ms=max(0, round((started - turn_start).total_seconds() * 1000)),
        duration_ms=_milliseconds(amount(row, "duration")),
        outcome=_failed(row),
        input_tokens=tokens_in,
        output_tokens=tokens_out,
    )


def _steps(
    rows: Sequence[Row],
    turn_start: datetime,
    settings: TelemetrySettings,
    labels: Mapping[str, str],
) -> list[SessionStep]:
    found = [_step(row, turn_start, settings, labels) for row in rows]
    ordered = sorted((pair for pair in found if pair is not None), key=lambda pair: pair[0])
    return [step for _, step in ordered]


def _is_turn(row: Row, settings: TelemetrySettings) -> bool:
    return row.get("span_name") in (settings.spans.cli_session, settings.spans.web_turn)


def _calls_by_trace(rows: Sequence[Row], settings: TelemetrySettings) -> dict[str, list[Row]]:
    calls: defaultdict[str, list[Row]] = defaultdict(list)
    for row in rows:
        trace = text(row, "trace_id")
        if trace is not None and not _is_turn(row, settings):
            calls[trace].append(row)
    return calls


def build_turns(
    rows: Sequence[Row],
    settings: TelemetrySettings,
    labels: Mapping[str, str],
    project: Project | None,
) -> tuple[list[TurnRecord], list[SessionTurn]]:
    """The recorded turns (with their call counts) and their timelines, oldest first."""
    calls = _calls_by_trace(rows, settings)
    parsed = [parse_turn(row) for row in rows if _is_turn(row, settings)]
    records: list[TurnRecord] = []
    turns: list[SessionTurn] = []
    for record in sorted((t for t in parsed if t is not None), key=lambda t: t.started):
        steps = _steps(calls[record.trace_id], record.started, settings, labels)
        kinds = [step.kind for step in steps]
        counted = replace(record, model_calls=kinds.count("model"), tool_calls=kinds.count("tool"))
        records.append(counted)
        turns.append(_turn(counted, steps, settings, project))
    return records, turns


def _turn(
    record: TurnRecord,
    steps: list[SessionStep],
    settings: TelemetrySettings,
    project: Project | None,
) -> SessionTurn:
    return SessionTurn(
        trace_id=record.trace_id,
        started_at=iso(record.started),
        question=record.question,
        duration_ms=_milliseconds(record.duration_s),
        outcome=record.outcome,
        steps=steps,
        trace_url=trace_url(settings.trace_url_template, project, record.trace_id),
    )
