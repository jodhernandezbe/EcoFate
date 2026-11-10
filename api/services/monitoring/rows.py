"""Parse the rows Logfire returns into typed records.

Rows are untrusted. A field of the wrong type, a non-finite or negative number or an
unparseable time becomes ``None`` (absent) with a warning that names the field and never shows
its value; nothing is coerced into a plausible number. A turn that lacks its identity (trace,
start time, session) is dropped.
"""

from __future__ import annotations

import json
import logging
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from api.schemas.monitoring import Outcome

logger = logging.getLogger("api.monitoring")
Row = Mapping[str, object]
COST_STATUSES = ("estimate", "lower_bound", "unpriced")


def _bad(key: str) -> None:
    logger.warning("monitoring row: field %r is not valid; treated as absent", key)


def text(row: Row, key: str) -> str | None:
    """A non-blank string field, or None."""
    value = row.get(key)
    if value is None:
        return None
    if isinstance(value, str) and value.strip():
        return value
    _bad(key)
    return None


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    return number if math.isfinite(number) and number >= 0 else None


def amount(row: Row, key: str) -> float | None:
    """A finite number >= 0 (a number or numeric text), or None."""
    if row.get(key) is None:
        return None
    number = _number(row[key])
    if number is None:
        _bad(key)
    return number


def count(row: Row, key: str) -> int | None:
    """A whole number >= 0 (an int or numeric text), or None."""
    number = amount(row, key)
    if number is None or number != int(number):
        if number is not None:
            _bad(key)
        return None
    return int(number)


def instant(row: Row, key: str) -> datetime | None:
    """An ISO 8601 time, taken as UTC when it has no offset, or None."""
    value = text(row, key)
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        _bad(key)
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def outcome(row: Row, key: str) -> Outcome:
    """``ok`` or ``error`` as recorded, otherwise ``unknown``."""
    value = row.get(key)
    return cast(Outcome, value) if value in ("ok", "error") else "unknown"


def token_usage(row: Row, key: str) -> tuple[int | None, int | None]:
    """Input and output tokens from a model call's usage JSON; (None, None) when absent."""
    raw = text(row, key)
    if raw is None:
        return None, None
    try:
        usage = json.loads(raw)
    except ValueError:
        _bad(key)
        return None, None
    table: Row = cast(Row, usage) if isinstance(usage, dict) else {}
    return count(table, "input_tokens"), count(table, "output_tokens")


def user_id(row: Row, key: str) -> str | None:
    """The opaque user id a span recorded, when it is a well-formed UUID (else absent)."""
    value = text(row, key)
    if value is None:
        return None
    try:
        return str(UUID(value))
    except ValueError:
        _bad(key)
        return None


@dataclass(frozen=True)
class RecordedUsage:
    """The usage and cost a turn's span recorded; a field it did not record is None."""

    input_tokens: int | None
    cached_input_tokens: int | None
    output_tokens: int | None
    cost_usd: float | None
    cost_status: str | None


def parse_usage(row: Row) -> RecordedUsage:
    """The recorded usage fields of a turn row."""
    status = text(row, "cost_status")
    return RecordedUsage(
        input_tokens=count(row, "input_tokens"),
        cached_input_tokens=count(row, "cached_input_tokens"),
        output_tokens=count(row, "output_tokens"),
        cost_usd=amount(row, "cost_usd"),
        cost_status=status if status in COST_STATUSES else None,
    )


@dataclass(frozen=True)
class TurnRecord:
    """One turn (web) or run (command line) as recorded on its span.

    ``model_calls`` and ``tool_calls`` are counted from the trace's spans.
    """

    trace_id: str
    started: datetime
    duration_s: float | None
    session_id: str
    question: str | None
    model: str | None
    outcome: Outcome
    usage: RecordedUsage
    model_calls: int | None
    tool_calls: int | None
    user_id: str | None = None


def parse_turn(row: Row) -> TurnRecord | None:
    """The turn a row describes, or None when it lacks its trace, start time or session."""
    trace_id, session_id = text(row, "trace_id"), text(row, "sid")
    started = instant(row, "start_timestamp")
    if trace_id is None or started is None or session_id is None:
        logger.warning("monitoring row: a turn without identity was skipped")
        return None
    return TurnRecord(
        trace_id=trace_id,
        started=started,
        duration_s=amount(row, "duration"),
        session_id=session_id,
        question=text(row, "question"),
        model=text(row, "model"),
        outcome=outcome(row, "outcome"),
        usage=parse_usage(row),
        model_calls=count(row, "model_calls"),
        tool_calls=count(row, "tool_calls"),
        user_id=user_id(row, "user_id"),
    )
