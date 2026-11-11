"""Monitoring of agent runs with Logfire: set-up, the LangChain bridge and the session span.

Set it up once at the program edge (``configure_telemetry``), open a ``session_span`` around a
run and add ``run_tracer`` to the run's callbacks: the model calls and tool calls of the run
become spans inside the session span. Nothing here is imported by ``agent/`` or ``tools/``.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Generator, Iterable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal

import logfire
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.tracers import LangChainTracer
from langsmith import Client

from app.usage_meter import CallUsage, summarize_calls
from commons.key_patterns import KEY_PATTERNS
from config.telemetry import TelemetrySettings
from config.ui import ModelPrice

Outcome = Literal["ok", "error"]
SCRUBBED = "***REDACTED***"
# Logfire joins its extra patterns into one case-insensitive regex, so inline flags must go.
_KEY_PATTERN_SOURCES = tuple(pattern.pattern.removeprefix("(?i)") for pattern in KEY_PATTERNS)


def _shows_secret(text: str, protected: frozenset[str]) -> bool:
    """Whether ``text`` has a key-shaped part or contains a protected value (any letter case)."""
    lowered = text.lower()
    return any(p.search(text) for p in KEY_PATTERNS) or any(v in lowered for v in protected)


def _hide_keys(
    own: Callable[[str], bool],
    protected: frozenset[str],
) -> Callable[[logfire.ScrubMatch], object | None]:
    """The scrubbing callback: what looks like a key, or is a protected value, is replaced with a
    fixed marker, and the attributes this module writes itself (those ``own`` accepts) are kept as
    they are.

    Logfire's own marker quotes the matched text, which for the key patterns and the protected
    values is the secret itself. Its built-in patterns would otherwise hide the session id (they
    match "session"). Every other match keeps Logfire's default handling (None).
    """

    def decide(match: logfire.ScrubMatch) -> object | None:
        if _shows_secret(match.pattern_match.group(0), protected):
            return SCRUBBED
        if match.path and own(str(match.path[-1])):
            text = match.value if isinstance(match.value, str) else ""
            return SCRUBBED if _shows_secret(text, protected) else match.value
        return None

    return decide


def scrubbing_options(
    settings: TelemetrySettings,
    protected: Iterable[str] = (),
) -> logfire.ScrubbingOptions:
    """Logfire scrubbing that also hides everything the log redaction hides.

    Args:
        settings: The monitoring settings (the attributes this module writes itself).
        protected: Exact secret values with no recognisable shape (the key-encryption keys, the
            session secret, the SMTP password, the operator's service keys, the monitoring
            tokens); each is hidden wherever it appears in a span. Logfire compiles its patterns
            once at configuration, so these must be known then.
    """
    names = settings.attributes
    exact = {names.session_id, names.question, names.model, names.outcome, names.user_id}
    prefixes = (names.usage_prefix, names.session_usage_prefix)
    literals = frozenset(value.lower() for value in protected if value)

    def own(key: str) -> bool:
        return key in exact or key.startswith(prefixes)

    return logfire.ScrubbingOptions(
        extra_patterns=[*_KEY_PATTERN_SOURCES, *(re.escape(value) for value in sorted(literals))],
        callback=_hide_keys(own, literals),
    )


def configure_telemetry(settings: TelemetrySettings, protected: Iterable[str] = ()) -> None:
    """Configure Logfire once, at start-up; does nothing when monitoring is disabled.

    ``protected`` are secret values to hide in every span (see ``scrubbing_options``).

    Spans are exported only when a write token is present (``LOGFIRE_TOKEN`` or the project
    credentials of ``logfire projects use``). Call it before the first ``run_tracer``.
    """
    if not settings.enabled:
        return
    logfire.configure(
        service_name=settings.service_name,
        environment=settings.environment,
        send_to_logfire="if-token-present",
        console=logfire.ConsoleOptions() if settings.console else False,
        scrubbing=scrubbing_options(settings, protected),
    )


@contextmanager
def enqueue_span(
    settings: TelemetrySettings | None,
    session_id: str,
    turn: TurnSegment,
    user_id: str,
) -> Generator[None]:
    """The span of handing a web turn to the worker: the trace context the task carries in its
    headers is this span's, so the worker's turn span is its child. Records nothing without
    monitoring."""
    if settings is None or not settings.enabled:
        yield
        return
    names = settings.attributes
    attributes: dict[str, Any] = {
        names.session_id: session_id,
        names.turn_id: turn.turn_id,
        names.resume_index: turn.resume_index,
        names.user_id: user_id,
    }
    with logfire.span(settings.spans.web_enqueue, **attributes):
        yield


def instrument_task_queue(settings: TelemetrySettings) -> None:
    """Propagate the trace through the task queue: the web program's turn span travels in each
    task's headers (never its arguments) and the worker's spans join that trace. Call after
    ``configure_telemetry`` in both processes; does nothing when monitoring is disabled."""
    if settings.enabled:
        logfire.instrument_celery()


@lru_cache(maxsize=1)
def _otel_client() -> Client:
    """The LangSmith client in OpenTelemetry mode: it writes to Logfire's tracer provider and
    sends nothing to LangSmith. Built on first use, after ``configure_telemetry``, because it
    binds to the provider that exists then."""
    return Client(tracing_mode="otel")


def flush_telemetry(settings: TelemetrySettings) -> None:
    """Send the spans still queued: the LangChain bridge sends from a background thread, so a
    short command-line run must call this before the process exits. Blocking; in async code run
    it in a thread. Does nothing when monitoring is disabled."""
    if not settings.enabled:
        return
    if _otel_client.cache_info().currsize:
        _otel_client().flush()
    logfire.force_flush()


def run_tracer(
    settings: TelemetrySettings,
    client: Client | None = None,
) -> BaseCallbackHandler | None:
    """The callback that records a run's chains, model calls and tool calls as spans, nested in
    the span that is current when the run starts; None when monitoring is disabled.

    Args:
        settings: The monitoring settings.
        client: LangSmith client in OpenTelemetry mode; defaults to the shared one.
    """
    if not settings.enabled:
        return None
    return LangChainTracer(client=client if client is not None else _otel_client())


class SessionSpan:
    """The span of one session or turn, as seen by its caller; every method is a no-op when
    monitoring is disabled."""

    def __init__(
        self,
        span: logfire.LogfireSpan | None,
        settings: TelemetrySettings | None,
    ) -> None:
        self._span = span
        self._settings = settings
        self.outcome: Outcome = "ok"

    @classmethod
    def inactive(cls) -> SessionSpan:
        """A span that records nothing (monitoring is off or not given)."""
        return cls(None, None)

    def fail(self) -> None:
        """Mark the run as failed (also done when the run raises)."""
        self.outcome = "error"

    def record_usage(
        self,
        calls: Sequence[CallUsage],
        pricing: Mapping[str, ModelPrice],
        *,
        session: bool = False,
    ) -> None:
        """Set the usage of ``calls`` on the span: the turn's or, with ``session``, the thread's."""
        if self._span is None or self._settings is None:
            return
        attributes = self._settings.attributes
        prefix = attributes.session_usage_prefix if session else attributes.usage_prefix
        for name, value in usage_fields(calls, pricing).items():
            self._span.set_attribute(f"{prefix}{name}", value)


def usage_fields(
    calls: Sequence[CallUsage],
    pricing: Mapping[str, ModelPrice],
) -> dict[str, int | float | bool | str]:
    """The usage attributes of ``calls``; an unpriced cost is left out, never recorded as 0."""
    total = summarize_calls(calls, pricing)
    fields: dict[str, int | float | bool | str] = {
        "calls": total.calls,
        "input_tokens": total.input_tokens,
        "cached_input_tokens": total.cached_input_tokens,
        "output_tokens": total.output_tokens,
        "complete": total.complete,
        "cost_status": total.cost.status,
    }
    if total.cost.usd is not None:
        fields["cost_usd"] = total.cost.usd
    return fields


@dataclass(frozen=True)
class TurnSegment:
    """Which web turn a span records, which of its runs (0 first, then each resume) and, when a
    background worker ran it, how many seconds it waited in the queue."""

    turn_id: str
    resume_index: int
    queue_wait_seconds: float | None = None


def _span_attributes(
    settings: TelemetrySettings,
    session_id: str,
    question: str,
    model: str,
    segment: TurnSegment | None,
    user_id: str | None,
) -> dict[str, Any]:
    # Any: logfire.span takes attributes as free keywords, which a str-valued dict would also
    # match against its typed options (tags, level, links).
    names = settings.attributes
    attributes: dict[str, Any] = {
        names.session_id: session_id,
        names.question: question,
        names.model: model,
    }
    if segment is not None:
        attributes |= {names.turn_id: segment.turn_id, names.resume_index: segment.resume_index}
        if segment.queue_wait_seconds is not None:
            attributes[names.queue_wait_seconds] = segment.queue_wait_seconds
    if user_id is not None:
        attributes[names.user_id] = user_id
    return attributes


@contextmanager
def session_span(
    settings: TelemetrySettings,
    name: str,
    session_id: str,
    question: str,
    model: str,
    segment: TurnSegment | None = None,
    user_id: str | None = None,
) -> Generator[SessionSpan]:
    """Open the span of a command-line run or a web turn (one span per resume of a turn).

    The span carries the session id, the question and the model (and, for a web turn, its turn
    id and resume index, and the signed-in user's opaque id), and ends with the outcome:
    ``error`` when the run raised or the caller called ``fail``, otherwise ``ok``.
    """
    if not settings.enabled:
        yield SessionSpan(None, settings)
        return
    names = settings.attributes
    attributes = _span_attributes(settings, session_id, question, model, segment, user_id)
    with logfire.span(name, **attributes) as span:
        handle = SessionSpan(span, settings)
        try:
            yield handle
        except BaseException:
            handle.fail()
            raise
        finally:
            span.set_attribute(names.outcome, handle.outcome)
