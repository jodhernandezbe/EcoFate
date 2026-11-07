"""Rows to and from the program's types. Stored rows are untrusted on read.

Every ``*_from_*`` function checks shape and type (finite numbers, never a ``bool`` as a number,
known message types, a valid workspace) and returns ``None`` for a row that fails, after logging
the thread id and what failed (never the row's content). Nothing is coerced or guessed.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from typing import cast

from langchain_core.messages import BaseMessage, message_to_dict, messages_from_dict
from pydantic import BaseModel, ValidationError

from app.usage_meter import CallUsage
from tools.schemas import ConfirmationRequest, MissingEntry

logger = logging.getLogger(__name__)

_ENTRY_TEXT_KEYS = ("entry_id", "quantity", "subject", "purpose")


def _warn(thread_id: str, what: str) -> None:
    logger.warning("Ignoring a stored %s that does not decode (thread %s)", what, thread_id)


def _number(value: object) -> float | None:
    """The value as a float when it is a finite int or float (never a bool), else None."""
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return None
    return float(value)


def _count(value: object, *, nullable: bool) -> tuple[bool, int | None]:
    """(valid, value) for a stored token count: a non-negative int, or None when nullable."""
    if value is None:
        return nullable, None
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return True, value
    return False, None


def message_to_json(message: BaseMessage) -> dict[str, object]:
    """One LangChain message as JSON-ready data."""
    return cast(dict[str, object], message_to_dict(message))


def message_from_json(raw: object, thread_id: str) -> BaseMessage | None:
    """A stored message, or None (with a warning) when it is not a known message type."""
    try:
        if not isinstance(raw, dict):
            raise ValueError("not an object")
        return messages_from_dict([cast(dict[str, object], raw)])[0]
    except (ValueError, KeyError, TypeError, ValidationError):
        _warn(thread_id, "message")
        return None


def workspace_to_json(state: BaseModel) -> dict[str, object]:
    """A workspace as JSON-ready data."""
    return state.model_dump(mode="json")


def workspace_from_json[ModelT: BaseModel](
    model: type[ModelT],
    raw: object,
    thread_id: str,
) -> ModelT | None:
    """A stored workspace validated against ``model``, or None (with a warning)."""
    try:
        return model.model_validate(raw)
    except ValidationError:
        _warn(thread_id, "workspace")
        return None


def _texts(entry: Mapping[str, object]) -> dict[str, str] | None:
    found = {key: entry.get(key) for key in _ENTRY_TEXT_KEYS}
    if not all(isinstance(text, str) and text for text in found.values()):
        return None
    return cast(dict[str, str], found)


def _units(value: object) -> list[str] | None:
    items = cast(list[object], value) if isinstance(value, list) else []
    if not items or not all(isinstance(unit, str) for unit in items):
        return None
    return cast(list[str], list(items))


def _entry_from_json(raw: object) -> MissingEntry | None:
    if not isinstance(raw, dict):
        return None
    entry = cast(dict[str, object], raw)
    texts, units = _texts(entry), _units(entry.get("accepted_units"))
    low, high = _number(entry.get("minimum")), _number(entry.get("maximum"))
    if texts is None or units is None or low is None or high is None:
        return None
    return cast(MissingEntry, {**texts, "accepted_units": units, "minimum": low, "maximum": high})


def pending_to_json(request: ConfirmationRequest) -> dict[str, object]:
    """A confirmation request as JSON-ready data (a copy)."""
    return cast(dict[str, object], {**request, "entries": [dict(e) for e in request["entries"]]})


def pending_from_json(raw: object, thread_id: str) -> ConfirmationRequest | None:
    """A stored confirmation request, or None (with a warning) when its shape is wrong."""
    data: dict[str, object] = cast(dict[str, object], raw) if isinstance(raw, dict) else {}
    request_id, entries = data.get("request_id"), data.get("entries")
    items = cast(list[object], entries) if isinstance(entries, list) else []
    decoded = [_entry_from_json(item) for item in items]
    if not isinstance(request_id, str) or not request_id or not decoded or None in decoded:
        _warn(thread_id, "confirmation request")
        return None
    return ConfirmationRequest(request_id=request_id, entries=cast(list[MissingEntry], decoded))


def usage_from_row(
    thread_id: str,
    model: object,
    input_tokens: object,
    cached_input_tokens: object,
    output_tokens: object,
) -> CallUsage | None:
    """A stored model call's usage, or None (with a warning) when a field is invalid."""
    in_ok, tokens_in = _count(input_tokens, nullable=True)
    cached_ok, cached = _count(cached_input_tokens, nullable=False)
    out_ok, tokens_out = _count(output_tokens, nullable=True)
    if not (in_ok and cached_ok and out_ok) or not isinstance(model, str) or not model:
        _warn(thread_id, "usage record")
        return None
    return CallUsage(model, tokens_in, cached or 0, tokens_out)


def answer_from_row(
    thread_id: str,
    key: object,
    value: object,
    declined: object,
) -> tuple[str, float | None] | None:
    """A stored answer as ``(key, value)``; value is None for a declined entry. None if invalid."""
    number = _number(value)
    is_declined = declined is True
    if not isinstance(key, str) or not key or (is_declined == (number is not None)):
        _warn(thread_id, "answer")
        return None
    return key, number
