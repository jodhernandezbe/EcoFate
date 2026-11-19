"""The per-thread event stream: job and turn lifecycle for a page that has the thread open.

Unlike a turn's stream (one writer, numbered by it), a thread's stream has several writers in
several processes (the chat worker, the tools worker, the API), so the stream itself numbers the
entries: an entry's id is its position (Redis' own ``{ms}-{n}`` id, or a counter in memory), and
a reader that reconnects with the last id it saw misses none and sees none twice. The stream is
named by the owner and the thread (two users may pick the same thread id), capped in length and
expiring after a time. Records carry ids and statuses only, never a result, a message or a key.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal, Protocol, cast

from redis.asyncio import Redis

from app.turns.bus import entries_text
from storage.job_model import Job
from storage.keys import ThreadKey
from storage.turn_model import Turn

logger = logging.getLogger("app.turns.thread_bus")
Record = dict[str, object]
ThreadEntry = tuple[str, Record]
# An entry id as Redis writes it (and as the memory bus does): two numbers joined by a dash.
ENTRY_ID_PATTERN = r"^\d{1,20}-\d{1,20}$"
_ENTRY_ID = re.compile(ENTRY_ID_PATTERN)
EventKind = Literal["job.queued", "job.running", "job.ended", "turn.started", "turn.ended"]


def thread_stream(key: ThreadKey) -> str:
    """The stream name of one user's thread."""
    return f"thread:{key.owner_id}:{key.thread_id}:events"


def is_entry_id(value: str) -> bool:
    """Whether ``value`` has the shape of an entry id (a ``Last-Event-ID`` is untrusted)."""
    return _ENTRY_ID.fullmatch(value) is not None


def job_record(kind: EventKind, job: Job) -> Record:
    """The record of a job event: ids and the status, no input and no result."""
    return {"kind": kind, "job_id": job.id, "tool": job.tool, "status": job.status.value}


def turn_record(kind: EventKind, turn: Turn, status: str) -> Record:
    """The record of a turn event: its id, whether the system started it, and its status."""
    return {"kind": kind, "turn_id": turn.id, "automatic": turn.automatic, "status": status}


class ThreadEventBus(Protocol):
    """Where a thread's events are appended (by any process) and read back from any entry."""

    async def publish(self, stream: str, record: Record, ttl_seconds: int) -> None:
        """Append ``record`` and keep the stream for ``ttl_seconds`` from now."""
        ...

    async def read(self, stream: str, after: str | None, block_seconds: float) -> list[ThreadEntry]:
        """The entries after entry id ``after`` (from the first when None), in order; waits up to
        ``block_seconds`` for one when there is none yet (then returns an empty list)."""
        ...


async def publish_quietly(
    bus: ThreadEventBus | None,
    key: ThreadKey,
    record: Record,
    ttl_seconds: int,
) -> None:
    """Publish a thread event; a stream that cannot be written never changes the job or turn
    (the page catches up from its snapshot): logged by class only."""
    if bus is None:
        return
    try:
        await bus.publish(thread_stream(key), record, ttl_seconds)
    except Exception as error:
        logger.warning("Thread event not published: %s", type(error).__name__)


@dataclass
class _Stream:
    entries: list[ThreadEntry] = field(default_factory=list[ThreadEntry])
    last: int = 0
    expires_at: float = 0.0


def _number(entry_id: str | None) -> int:
    return 0 if entry_id is None else int(entry_id.split("-", 1)[0])


class MemoryThreadBus:
    """``ThreadEventBus`` in process memory (tests, in-process runs); same reading semantics.

    Args:
        clock: Monotonic seconds (a test moves time to check expiry).
        max_length: Entries kept per stream (the oldest go first).
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic, max_length: int = 1000) -> None:
        self._clock = clock
        self._max = max_length
        self._streams: dict[str, _Stream] = {}
        self._changed = asyncio.Condition()

    def _live(self, stream: str) -> _Stream | None:
        found = self._streams.get(stream)
        if found is not None and found.expires_at <= self._clock():
            del self._streams[stream]
            return None
        return found

    async def publish(self, stream: str, record: Record, ttl_seconds: int) -> None:
        """Append a copy of ``record`` as the next entry and wake every waiting reader."""
        target = self._live(stream) or self._streams.setdefault(stream, _Stream())
        target.last += 1
        copy = cast(Record, json.loads(json.dumps(record, default=str)))
        target.entries = [*target.entries, (f"{target.last}-0", copy)][-self._max :]
        target.expires_at = self._clock() + ttl_seconds
        async with self._changed:
            self._changed.notify_all()

    def _after(self, stream: str, after: str | None) -> list[ThreadEntry]:
        found = self._live(stream)
        entries = found.entries if found is not None else []
        return [(i, dict(r)) for i, r in entries if _number(i) > _number(after)]

    async def read(self, stream: str, after: str | None, block_seconds: float) -> list[ThreadEntry]:
        """The entries after ``after``; waits for the next publish when there are none."""
        async with self._changed:
            ready = self._after(stream, after)
            if ready:
                return ready
            try:
                await asyncio.wait_for(self._changed.wait(), timeout=block_seconds)
            except TimeoutError:
                return []
        return self._after(stream, after)


_FIELD = "data"
_MS_PER_SECOND = 1000


class RedisThreadBus:
    """``ThreadEventBus`` over a Redis Stream (``XADD`` with ``MAXLEN ~`` and an automatic id,
    ``XREAD BLOCK``).

    Args:
        client: A ``redis.asyncio`` client created with ``decode_responses=True``.
        max_length: Approximate number of entries kept per stream.
    """

    def __init__(self, client: Redis, max_length: int) -> None:
        self._client = client
        self._max_length = max_length

    async def publish(self, stream: str, record: Record, ttl_seconds: int) -> None:
        """``XADD`` the record (Redis numbers it) and renew the stream's expiry."""
        data = json.dumps(record, default=str)
        async with self._client.pipeline(transaction=True) as pipe:
            pipe.xadd(stream, {_FIELD: data}, maxlen=self._max_length)
            pipe.expire(stream, ttl_seconds)
            await pipe.execute()

    async def read(self, stream: str, after: str | None, block_seconds: float) -> list[ThreadEntry]:
        """``XREAD BLOCK`` after entry id ``after`` (``0-0`` from the start)."""
        block = max(1, round(block_seconds * _MS_PER_SECOND))
        reply = await self._client.xread({stream: after or "0-0"}, block=block)
        streams = cast(list[tuple[str, list[object]]], reply or [])
        return [entry for _, items in streams for entry in entries_text(items)]
