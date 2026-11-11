"""The events a background turn passes from its worker to its readers, as JSON-ready records.

A record is a flat mapping with a ``kind``. Messages travel as LangChain's message dicts, usage
as plain numbers, a confirmation request as its JSON shape. ``TurnFailed`` never travels: the
worker records the failure and sends ``TurnStopped`` (the reason, its correlation id and whether
the turn can be resumed). Records hold no key, token or exception text; a record read back is
untrusted and decodes to None when it does not fit.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import cast

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    ToolMessage,
    message_to_dict,
    messages_from_dict,
)

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
    TurnUsage,
)
from app.turns.failures import FailureReason
from app.usage_meter import CallUsage
from tools.schemas import ConfirmationRequest

logger = logging.getLogger(__name__)
Record = dict[str, object]


@dataclass(frozen=True)
class TurnQueued:
    """The turn waits for a worker; ``position`` turns were queued before it (approximate)."""

    position: int


@dataclass(frozen=True)
class WorkerStarted:
    """A worker took the turn and is about to run it."""


@dataclass(frozen=True)
class TurnStopped:
    """The turn stopped before its answer: interrupted (``resumable``) or failed."""

    reason: FailureReason
    correlation_id: str
    resumable: bool


RelayedEvent = (
    TurnQueued
    | WorkerStarted
    | TurnBegan
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
    | TurnStopped
    | TurnUsage
    | TurnDone
)

_BARE: Mapping[str, RelayedEvent] = {
    "began": TurnBegan(),
    "agent_started": AgentStarted(),
    "running": WorkerStarted(),
    "scope_passed": ScopePassed(),
    "done": TurnDone(),
}
_BARE_KINDS: Mapping[type, str] = {type(event): kind for kind, event in _BARE.items()}


def is_last(event: RelayedEvent) -> bool:
    """Whether ``event`` ends a turn's stream."""
    return isinstance(event, TurnDone)


def _message(message: BaseMessage) -> Record:
    return cast(Record, message_to_dict(message))


def _usage(calls: tuple[CallUsage, ...]) -> list[Record]:
    return [
        {
            "model": c.model,
            "input_tokens": c.input_tokens,
            "cached_input_tokens": c.cached_input_tokens,
            "output_tokens": c.output_tokens,
        }
        for c in calls
    ]


def encode(event: RelayedEvent) -> Record:
    """The record of ``event`` (JSON-ready)."""
    bare = _BARE_KINDS.get(type(event))
    if bare is not None:
        return {"kind": bare}
    return _encode_text(event) or _encode_tool(event) or _encode_other(event)


def _encode_text(event: RelayedEvent) -> Record | None:
    match event:
        case TextDelta(text=text):
            return {"kind": "text", "text": text}
        case AssistantText(text=text):
            return {"kind": "assistant_text", "text": text}
        case ScopeRedirect(texts=texts):
            return {"kind": "scope_redirect", "texts": list(texts)}
        case _:
            return None


def _encode_tool(event: RelayedEvent) -> Record | None:
    match event:
        case ToolStarted(call_id=call_id, tool_name=name):
            return {"kind": "tool_started", "call_id": call_id, "tool_name": name}
        case ToolCalls(message=message):
            return {"kind": "tool_calls", "message": _message(message)}
        case ToolFinished(call_id=call_id, tool_name=name, failed=failed, message=message):
            record: Record = {"kind": "tool_finished", "call_id": call_id, "tool_name": name}
            return record | {"failed": failed, "message": _message(message)}
        case ToolResults(messages=messages):
            return {"kind": "tool_results", "messages": [_message(m) for m in messages]}
        case _:
            return None


def _encode_other(event: RelayedEvent) -> Record:
    match event:
        case TurnQueued(position=position):
            return {"kind": "queued", "position": position}
        case ConfirmationNeeded(request=request):
            return {"kind": "confirmation", "request": dict(request)}
        case TurnStopped(reason=reason, correlation_id=correlation_id, resumable=again):
            record: Record = {"kind": "stopped", "reason": reason.value}
            return record | {"correlation_id": correlation_id, "resumable": again}
        case TurnUsage(turn=turn, session=session):
            return {"kind": "usage", "turn": _usage(turn), "session": _usage(session)}
        case _:
            raise TypeError(f"no record for {type(event).__name__}")


class _Unfit(ValueError):
    """A record field does not have the expected shape."""


def _text(record: Mapping[str, object], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str):
        raise _Unfit(key)
    return value


def _flag(record: Mapping[str, object], key: str) -> bool:
    value = record.get(key)
    if not isinstance(value, bool):
        raise _Unfit(key)
    return value


def _count(value: object, *, nullable: bool = False) -> int | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _Unfit("count")
    return value


def _items(record: Mapping[str, object], key: str) -> list[object]:
    value = record.get(key)
    if not isinstance(value, list):
        raise _Unfit(key)
    return cast(list[object], value)


def _decoded_message[M: BaseMessage](raw: object, kind: type[M]) -> M:
    if not isinstance(raw, dict):
        raise _Unfit("message")
    try:
        message = messages_from_dict([cast(dict[str, object], raw)])[0]
    except (KeyError, TypeError, ValueError) as error:
        raise _Unfit("message") from error
    if not isinstance(message, kind):
        raise _Unfit("message")
    return message


def _call(raw: object) -> CallUsage:
    if not isinstance(raw, dict):
        raise _Unfit("usage")
    data = cast(Mapping[str, object], raw)
    cached = _count(data.get("cached_input_tokens"))
    return CallUsage(
        model=_text(data, "model"),
        input_tokens=_count(data.get("input_tokens"), nullable=True),
        cached_input_tokens=cached if cached is not None else 0,
        output_tokens=_count(data.get("output_tokens"), nullable=True),
    )


def _calls(record: Mapping[str, object], key: str) -> tuple[CallUsage, ...]:
    return tuple(_call(item) for item in _items(record, key))


def _texts(record: Mapping[str, object], key: str) -> tuple[str, ...]:
    items = _items(record, key)
    if not all(isinstance(item, str) for item in items):
        raise _Unfit(key)
    return tuple(cast(list[str], items))


def _request(record: Mapping[str, object]) -> ConfirmationRequest:
    raw = record.get("request")
    if not isinstance(raw, dict):
        raise _Unfit("request")
    data = cast(Mapping[str, object], raw)
    _text(data, "request_id")
    _items(data, "entries")
    return cast(ConfirmationRequest, dict(data))


def _stopped(record: Mapping[str, object]) -> TurnStopped:
    try:
        reason = FailureReason(_text(record, "reason"))
    except ValueError as error:
        raise _Unfit("reason") from error
    return TurnStopped(reason, _text(record, "correlation_id"), _flag(record, "resumable"))


def _tool_finished(record: Mapping[str, object]) -> ToolFinished:
    message = _decoded_message(record.get("message"), ToolMessage)
    return ToolFinished(
        _text(record, "call_id"),
        _text(record, "tool_name"),
        _flag(record, "failed"),
        message,
    )


def _tool_results(record: Mapping[str, object]) -> ToolResults:
    items = _items(record, "messages")
    return ToolResults(tuple(_decoded_message(item, ToolMessage) for item in items))


_DECODERS: Mapping[str, Callable[[Mapping[str, object]], RelayedEvent]] = {
    "queued": lambda r: TurnQueued(_count(r.get("position")) or 0),
    "text": lambda r: TextDelta(_text(r, "text")),
    "assistant_text": lambda r: AssistantText(_text(r, "text")),
    "scope_redirect": lambda r: ScopeRedirect(_texts(r, "texts")),
    "tool_started": lambda r: ToolStarted(_text(r, "call_id"), _text(r, "tool_name")),
    "tool_calls": lambda r: ToolCalls(_decoded_message(r.get("message"), AIMessage)),
    "tool_finished": _tool_finished,
    "tool_results": _tool_results,
    "confirmation": lambda r: ConfirmationNeeded(_request(r)),
    "stopped": _stopped,
    "usage": lambda r: TurnUsage(_calls(r, "turn"), _calls(r, "session")),
}


def decode(record: object) -> RelayedEvent | None:
    """The event of a record read back; None (logged by kind only) when it does not fit."""
    if not isinstance(record, dict):
        logger.warning("Ignoring a turn event record that is not a mapping")
        return None
    data = cast(Mapping[str, object], record)
    kind = data.get("kind")
    if isinstance(kind, str) and kind in _BARE:
        return _BARE[kind]
    decoder = _DECODERS.get(kind) if isinstance(kind, str) else None
    try:
        if decoder is None:
            raise _Unfit("kind")
        return decoder(data)
    except _Unfit as error:
        logger.warning("Ignoring a turn event record that does not fit (%s: %s)", kind, error)
        return None
