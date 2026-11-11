"""Server-sent-event encoding of stream events."""

from __future__ import annotations

from pydantic import BaseModel


def encode_event(event: BaseModel) -> str:
    """One SSE frame: the event's ``seq`` (when it has one) as the event id, so a client can
    reattach with ``Last-Event-ID``, and the event as a single-line JSON ``data`` field."""
    seq = getattr(event, "seq", None)
    event_id = f"id: {seq}\n" if isinstance(seq, int) and not isinstance(seq, bool) else ""
    return f"{event_id}data: {event.model_dump_json()}\n\n"
