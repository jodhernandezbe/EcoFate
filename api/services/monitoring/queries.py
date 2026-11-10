"""The SQL the Monitoring view sends to Logfire, built from the ``[telemetry]`` settings.

Logfire's query API has no bind parameters, so a value only ever enters a statement as a quoted
literal: a name from configuration, or a session id that matched ``THREAD_ID_PATTERN`` (the
rule every thread id already follows). That is why bandit's B608 is silenced on the statements
below: nothing else is ever interpolated into them. The result columns the parsers read are the
aliases used here: ``trace_id``, ``start_timestamp``, ``duration`` (seconds), ``sid``, ``question``,
``model``, ``outcome``, ``input_tokens``, ``cached_input_tokens``, ``output_tokens``,
``cost_usd``, ``cost_status``, ``user_id``, ``model_calls``, ``tool_calls`` for the sessions
listing, and
``span_name``, ``op``, ``tool``, ``usage``, ``status``, ``is_exception`` for the detail.
"""

from __future__ import annotations

import re

from api.schemas.chat import THREAD_ID_PATTERN
from config.telemetry import TelemetrySettings

_SESSION_ID = re.compile(THREAD_ID_PATTERN)
_USAGE_FIELDS = ("input_tokens", "cached_input_tokens", "output_tokens", "cost_usd", "cost_status")


def is_session_id(value: str) -> bool:
    """True when ``value`` has the shape of a session id, which makes it safe in a statement."""
    return _SESSION_ID.fullmatch(value) is not None


def _literal(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _attribute(name: str) -> str:
    return f"attributes->>{_literal(name)}"


def _roots(settings: TelemetrySettings) -> str:
    spans = settings.spans
    return f"{_literal(spans.cli_session)}, {_literal(spans.web_turn)}"


def _calls_of(settings: TelemetrySettings) -> str:
    bridge = settings.bridge
    return f"{_literal(bridge.model_operation)}, {_literal(bridge.tool_operation)}"


def _count(settings: TelemetrySettings, operation: str, alias: str) -> str:
    column = _attribute(settings.bridge.operation)
    return f"sum(case when {column} = {_literal(operation)} then 1 else 0 end) as {alias}"


def _turn_columns(settings: TelemetrySettings) -> str:
    """The columns of a turn span: session, question, model, outcome and recorded usage."""
    names = settings.attributes
    usage = ", ".join(f"{_attribute(names.usage_prefix + f)} as {f}" for f in _USAGE_FIELDS)
    return (
        f"{_attribute(names.session_id)} as sid, {_attribute(names.question)} as question, "
        f"{_attribute(names.model)} as model, {_attribute(names.outcome)} as outcome, "
        f"{_attribute(names.user_id)} as user_id, {usage}"
    )


def _turns(settings: TelemetrySettings) -> str:
    return (
        "turns as (select trace_id, start_timestamp, duration, "  # nosec B608
        f"{_turn_columns(settings)} from records where span_name in ({_roots(settings)}) "
        f"and {_attribute(settings.attributes.session_id)} is not null)"
    )


def _calls(settings: TelemetrySettings) -> str:
    bridge = settings.bridge
    return (
        f"calls as (select trace_id, {_count(settings, bridge.model_operation, 'model_calls')}, "  # nosec B608
        f"{_count(settings, bridge.tool_operation, 'tool_calls')} from records "
        f"where {_attribute(bridge.operation)} in ({_calls_of(settings)}) group by trace_id)"
    )


def sessions_sql(settings: TelemetrySettings) -> str:
    """One statement: every turn of the most recent sessions, with its call counts."""
    recent = (
        "recent as (select sid, min(start_timestamp) as first_start from turns "  # nosec B608
        f"group by sid order by first_start desc limit {settings.max_sessions})"
    )
    return (
        f"with {_turns(settings)}, {recent}, {_calls(settings)} "  # nosec B608
        "select t.*, coalesce(c.model_calls, 0) as model_calls, "
        "coalesce(c.tool_calls, 0) as tool_calls from turns t join recent r on r.sid = t.sid "
        "left join calls c on c.trace_id = t.trace_id order by t.start_timestamp"
    )


def detail_sql(settings: TelemetrySettings, session_id: str) -> str:
    """One statement: the turn spans of a session and the model and tool calls in them.

    Raises:
        ValueError: If ``session_id`` is not shaped like a session id.
    """
    if not is_session_id(session_id):
        raise ValueError("not a session id")
    names, bridge = settings.attributes, settings.bridge
    inner = (
        f"select trace_id from records where span_name in ({_roots(settings)}) "  # nosec B608
        f"and {_attribute(names.session_id)} = {_literal(session_id)}"
    )
    columns = (
        "trace_id, start_timestamp, duration, span_name, otel_status_code as status, "
        f"is_exception, {_attribute(bridge.operation)} as op, "
        f"{_attribute(bridge.tool_name)} as tool, {_attribute(bridge.usage_metadata)} as usage, "
        f"{_turn_columns(settings)}"
    )
    return (
        f"select {columns} from records where trace_id in ({inner}) and (span_name in "  # nosec B608
        f"({_roots(settings)}) or {_attribute(bridge.operation)} in ({_calls_of(settings)})) "
        "order by start_timestamp"
    )
