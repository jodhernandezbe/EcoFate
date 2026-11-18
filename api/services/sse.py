"""Server-sent-event encoding of stream events, and the keepalive of a quiet stream."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

from pydantic import BaseModel

# An SSE comment: EventSource ignores it; it only keeps proxies from closing a quiet stream.
KEEPALIVE = ": keepalive\n\n"


def encode_event(event: BaseModel) -> str:
    """One SSE frame: the event's ``seq`` (when it has one) as the event id, so a client can
    reattach with ``Last-Event-ID``, and the event as a single-line JSON ``data`` field."""
    seq = getattr(event, "seq", None)
    event_id = f"id: {seq}\n" if isinstance(seq, int) and not isinstance(seq, bool) else ""
    return f"{event_id}data: {event.model_dump_json()}\n\n"


async def _next_or_keepalive(task: asyncio.Future[str], interval_seconds: float) -> str | None:
    """The next frame, or None when ``interval_seconds`` pass first (the task keeps running)."""
    done, _ = await asyncio.wait({task}, timeout=interval_seconds)
    return task.result() if done else None


async def with_heartbeat(
    frames: AsyncGenerator[str],
    interval_seconds: float,
) -> AsyncGenerator[str]:
    """``frames`` unchanged, plus a ``KEEPALIVE`` comment whenever none arrives for
    ``interval_seconds``. The wait for the next frame is never cancelled by a keepalive, so no
    frame is lost; leaving early cancels the pending read and closes ``frames``."""
    pending: asyncio.Future[str] | None = None
    try:
        while True:
            pending = pending or asyncio.ensure_future(anext(frames))
            try:
                frame = await _next_or_keepalive(pending, interval_seconds)
            except StopAsyncIteration:
                return
            if frame is None:
                yield KEEPALIVE
                continue
            pending = None
            yield frame
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        await frames.aclose()
