"""Typed loader for the ``[telemetry]`` settings: Logfire monitoring of agent runs."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from config.parsing import (
    read_toml,
    require_bool,
    require_int,
    require_number,
    require_str,
    section,
    subtable,
)

_NAME = "telemetry"
_REQUIRED_URL_FIELD = "{trace_id}"


@dataclass(frozen=True)
class SpanNames:
    """Names of the spans that open a trace.

    Attributes:
        cli_session: One command-line run.
        web_turn: One chat turn of the web program.
    """

    cli_session: str
    web_turn: str


@dataclass(frozen=True)
class AttributeNames:
    """Names of the attributes written on the session and turn spans.

    Attributes:
        session_id: The session (a command-line run, or the web thread) the span belongs to.
        question: The user's question.
        model: The configured chat model name.
        outcome: ``ok`` or ``error``.
        usage_prefix: Prefix of the usage fields of the run (``calls``, ``input_tokens``, ...).
        session_usage_prefix: The same fields for the thread so far (web turns only).
        turn_id: The web turn the span belongs to (a resumed turn keeps its id).
        resume_index: 0 for a turn's first run, then 1, 2, ... for each resume (web turns only).
        user_id: The signed-in user's opaque id (web turns only; never an email).
    """

    session_id: str
    question: str
    model: str
    outcome: str
    usage_prefix: str
    session_usage_prefix: str
    turn_id: str
    resume_index: str
    user_id: str


@dataclass(frozen=True)
class BridgeNames:
    """Attributes the LangChain-to-OpenTelemetry bridge writes on its spans.

    Attributes:
        operation: Attribute telling what a span is.
        model_operation: Its value on a chat model call.
        tool_operation: Its value on a tool call.
        tool_name: Attribute holding a tool call's tool name.
        usage_metadata: Attribute holding a model call's usage, as JSON.
    """

    operation: str
    model_operation: str
    tool_operation: str
    tool_name: str
    usage_metadata: str


@dataclass(frozen=True)
class TelemetrySettings:
    """Monitoring settings. The tokens themselves are never stored, only a variable name.

    Attributes:
        enabled: False records nothing and adds no callback to a run.
        service_name: Logfire service name.
        environment: Deployment environment tag.
        console: Also print spans to the terminal.
        write_token_env_var: Environment variable holding the Logfire write token (read by
            Logfire itself; named here so its value stays out of the logs).
        read_token_env_var: Environment variable holding the Logfire read token.
        query_timeout_seconds: Time limit of one Logfire query, in seconds.
        session_window_hours: How far back the Monitoring view looks, in hours.
        max_sessions: Most sessions the Monitoring view lists.
        max_rows: Most rows one Logfire query may return.
        trace_url_template: Link to a trace; ``{trace_id}`` is required.
        spans: Names of the spans that open a trace.
        attributes: Names of the attributes written on them.
        bridge: Names the LangChain bridge writes on model and tool call spans.
    """

    enabled: bool
    service_name: str
    environment: str
    console: bool
    write_token_env_var: str
    read_token_env_var: str
    query_timeout_seconds: float
    session_window_hours: int
    max_sessions: int
    max_rows: int
    trace_url_template: str
    spans: SpanNames
    attributes: AttributeNames
    bridge: BridgeNames


def _url_template(table: dict[str, object]) -> str:
    value = require_str(table, "trace_url_template", _NAME).strip()
    if _REQUIRED_URL_FIELD not in value or not value.startswith("https://"):
        raise ValueError(f"{_NAME}.trace_url_template must be an https URL containing {{trace_id}}")
    return value


def _token_var(table: dict[str, object], key: str) -> str:
    return require_str(table, key, _NAME).strip()


def _timeout(table: dict[str, object]) -> float:
    return require_number(table, "query_timeout_seconds", minimum=0.001, name=_NAME)


def _spans(table: dict[str, object]) -> SpanNames:
    name = f"{_NAME}.spans"
    spans = subtable(table, "spans", _NAME)
    values = SpanNames(
        cli_session=require_str(spans, "cli_session", name).strip(),
        web_turn=require_str(spans, "web_turn", name).strip(),
    )
    if values.cli_session == values.web_turn:
        raise ValueError(f"{name} must give each span its own name")
    return values


def _attributes(table: dict[str, object]) -> AttributeNames:
    name = f"{_NAME}.attributes"
    attrs = subtable(table, "attributes", _NAME)
    values = AttributeNames(
        session_id=require_str(attrs, "session_id", name).strip(),
        question=require_str(attrs, "question", name).strip(),
        model=require_str(attrs, "model", name).strip(),
        outcome=require_str(attrs, "outcome", name).strip(),
        usage_prefix=require_str(attrs, "usage_prefix", name).strip(),
        session_usage_prefix=require_str(attrs, "session_usage_prefix", name).strip(),
        turn_id=require_str(attrs, "turn_id", name).strip(),
        resume_index=require_str(attrs, "resume_index", name).strip(),
        user_id=require_str(attrs, "user_id", name).strip(),
    )
    if values.usage_prefix == values.session_usage_prefix:
        raise ValueError(f"{name} must give the turn and the session usage their own prefix")
    return values


def _bridge(table: dict[str, object]) -> BridgeNames:
    name = f"{_NAME}.bridge"
    bridge = subtable(table, "bridge", _NAME)
    return BridgeNames(
        operation=require_str(bridge, "operation", name).strip(),
        model_operation=require_str(bridge, "model_operation", name).strip(),
        tool_operation=require_str(bridge, "tool_operation", name).strip(),
        tool_name=require_str(bridge, "tool_name", name).strip(),
        usage_metadata=require_str(bridge, "usage_metadata", name).strip(),
    )


def load_telemetry_settings(path: Path | None = None) -> TelemetrySettings:
    """Load and validate the monitoring settings.

    Args:
        path: Settings file; defaults to the ``settings.toml`` shipped in ``config/``.

    Returns:
        The validated settings (timeout in seconds, window in hours).

    Raises:
        FileNotFoundError: If the settings file does not exist.
        ValueError: If a key is missing or invalid; the message names the key.
    """
    table = section(read_toml(path), _NAME)
    return TelemetrySettings(
        enabled=require_bool(table, "enabled", _NAME),
        service_name=require_str(table, "service_name", _NAME).strip(),
        environment=require_str(table, "environment", _NAME).strip(),
        console=require_bool(table, "console", _NAME),
        write_token_env_var=_token_var(table, "write_token_env_var"),
        read_token_env_var=_token_var(table, "read_token_env_var"),
        query_timeout_seconds=_timeout(table),
        session_window_hours=require_int(table, "session_window_hours", minimum=1, name=_NAME),
        max_sessions=require_int(table, "max_sessions", minimum=1, name=_NAME),
        max_rows=require_int(table, "max_rows", minimum=1, name=_NAME),
        trace_url_template=_url_template(table),
        spans=_spans(table),
        attributes=_attributes(table),
        bridge=_bridge(table),
    )


@lru_cache(maxsize=1)
def get_telemetry_settings() -> TelemetrySettings:
    """Return the cached monitoring settings from the default file."""
    return load_telemetry_settings()
