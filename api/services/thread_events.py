"""The thread-level event stream as server-sent events: job and turn lifecycle of one thread.

Reads the thread's stream (``app.turns.thread_bus``) from after the client's ``Last-Event-ID``
(from the first entry when absent) and presents each entry as one SSE frame whose id is the
entry's id, so a reconnecting page misses nothing and sees nothing twice. It never changes a job
or a turn. Records are untrusted: one that does not fit the contract is skipped (its id still
advances the position).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from pydantic import ValidationError

from api.schemas.chat import ThreadEvent
from app.turns.thread_bus import Record, ThreadEventBus, thread_stream
from storage.keys import ThreadKey


def encode_thread_event(entry_id: str, event: ThreadEvent) -> str:
    """One SSE frame: the entry id (the client's ``Last-Event-ID``) and the event as JSON."""
    return f"id: {entry_id}\ndata: {event.model_dump_json(exclude_none=True)}\n\n"


def decode(record: Record) -> ThreadEvent | None:
    """The event of a stored record; None when it does not fit the contract."""
    try:
        return ThreadEvent.model_validate(record)
    except ValidationError:
        return None


async def thread_frames(
    bus: ThreadEventBus,
    key: ThreadKey,
    after: str | None,
    block_seconds: float,
) -> AsyncGenerator[str]:
    """The thread's events as SSE frames, for as long as the reader stays."""
    stream = thread_stream(key)
    while True:
        for entry_id, record in await bus.read(stream, after, block_seconds):
            after = entry_id
            event = decode(record)
            if event is not None:
                yield encode_thread_event(entry_id, event)
