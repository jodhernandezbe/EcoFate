"""The per-turn event stream between the worker that runs a turn and the readers that show it.

Each turn segment (a new turn, or one resume of it) has its own stream. Its writers number the
records from 0 (``seq``); a reader asks for the records after a ``seq`` and blocks until one
arrives, so a reader that reconnects with the last ``seq`` it received misses none and sees none
twice. ``RedisStreamBus`` keeps the records in a Redis Stream (entry id ``{seq}-1``, capped at
an approximate length, expiring after a time); ``MemoryBus`` has the same reading semantics in
process memory for tests and in-process runs. Records are JSON-ready mappings without secrets
(``app.turns.codec``).
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol, cast

from redis.asyncio import Redis

Record = dict[str, object]
Entry = tuple[int, Record]


def turn_stream(turn_id: str, segment: int) -> str:
    """The stream name of one segment of a turn (``segment`` = how often it was resumed)."""
    return f"turn:{turn_id}:{segment}:events"


class TurnEventBus(Protocol):
    """Where a turn's events are written in order and read back from any ``seq``."""

    async def publish(
        self,
        stream: str,
        seq: int,
        record: Record,
        ttl_seconds: int,
    ) -> None:
        """Append ``record`` as ``seq`` (one more than the last) and keep the stream for
        ``ttl_seconds`` from now."""
        ...

    async def read(
        self,
        stream: str,
        after: int | None,
        block_seconds: float,
    ) -> list[Entry]:
        """The records after ``seq`` ``after`` (from the first when None), in order; waits up to
        ``block_seconds`` for one when there is none yet (then returns an empty list)."""
        ...

    async def exists(
        self,
        stream: str,
    ) -> bool:
        """Whether the stream still exists (it expires after its last ``ttl_seconds``)."""
        ...


@dataclass
class _Stream:
    entries: list[Entry] = field(default_factory=list[Entry])
    expires_at: float = 0.0


class MemoryBus:
    """``TurnEventBus`` in process memory (tests and in-process runs); same semantics as Redis.

    Args:
        clock: Monotonic seconds (a test moves time to check expiry).
    """

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._clock = clock
        self._streams: dict[str, _Stream] = {}
        self._changed = asyncio.Condition()

    def _live(self, stream: str) -> _Stream | None:
        found = self._streams.get(stream)
        if found is not None and found.expires_at <= self._clock():
            del self._streams[stream]
            return None
        return found

    async def publish(
        self,
        stream: str,
        seq: int,
        record: Record,
        ttl_seconds: int,
    ) -> None:
        """Append a copy of ``record`` and wake every waiting reader."""
        target = self._live(stream) or self._streams.setdefault(stream, _Stream())
        target.entries.append((seq, json.loads(json.dumps(record, default=str))))
        target.expires_at = self._clock() + ttl_seconds
        async with self._changed:
            self._changed.notify_all()

    def _after(
        self,
        stream: str,
        after: int | None,
    ) -> list[Entry]:
        found = self._live(stream)
        entries = found.entries if found is not None else []
        return [(seq, dict(record)) for seq, record in entries if after is None or seq > after]

    async def read(
        self,
        stream: str,
        after: int | None,
        block_seconds: float,
    ) -> list[Entry]:
        """The records after ``after``; waits for the next publish when there are none."""
        async with self._changed:  # checked under the lock, so no publish is missed
            ready = self._after(stream, after)
            if ready:
                return ready
            try:
                await asyncio.wait_for(self._changed.wait(), timeout=block_seconds)
            except TimeoutError:
                return []
        return self._after(stream, after)

    async def exists(self, stream: str) -> bool:
        """Whether the stream exists and has not expired."""
        return self._live(stream) is not None


_FIELD = "data"
_MS_PER_SECOND = 1000


class RedisStreamBus:
    """``TurnEventBus`` over Redis Streams (``XADD`` with ``MAXLEN ~``, ``XREAD BLOCK``).

    Args:
        client: A ``redis.asyncio`` client created with ``decode_responses=True`` (one per
            process, never shared across a fork).
        max_length: Approximate number of records kept per stream.
    """

    def __init__(self, client: Redis, max_length: int) -> None:
        self._client = client
        self._max_length = max_length

    async def publish(
        self,
        stream: str,
        seq: int,
        record: Record,
        ttl_seconds: int,
    ) -> None:
        """``XADD`` the record as entry ``{seq}-1`` and renew the stream's expiry."""
        data = json.dumps(record, default=str)
        async with self._client.pipeline(transaction=True) as pipe:
            pipe.xadd(stream, {_FIELD: data}, id=f"{seq}-1", maxlen=self._max_length)
            pipe.expire(stream, ttl_seconds)
            await pipe.execute()

    async def read(
        self,
        stream: str,
        after: int | None,
        block_seconds: float,
    ) -> list[Entry]:
        """``XREAD BLOCK`` after entry ``{after}-1`` (``0-0`` from the start)."""
        start = "0-0" if after is None else f"{after}-1"
        block = max(1, round(block_seconds * _MS_PER_SECOND))
        reply = await self._client.xread({stream: start}, block=block)
        streams = cast(list[tuple[str, list[object]]], reply or [])
        return [entry for _, items in streams for entry in entries_of(items)]

    async def exists(
        self,
        stream: str,
    ) -> bool:
        """``EXISTS`` (an expired stream is gone)."""
        return bool(await self._client.exists(stream))


def entries_of(items: list[object]) -> list[Entry]:
    """The ``(seq, record)`` pairs of one ``XREAD`` reply; an entry that does not decode is
    skipped (stream data is untrusted)."""
    found: list[Entry] = []
    for item in items:
        entry = _entry(item)
        if entry is not None:
            found.append(entry)
    return found


def _entry(item: object) -> Entry | None:
    try:
        entry_id, fields = cast(tuple[str, dict[str, str]], item)
        seq = int(str(entry_id).split("-", 1)[0])
        record = json.loads(fields[_FIELD])
    except (TypeError, ValueError, KeyError):
        return None
    return (seq, cast(Record, record)) if isinstance(record, dict) else None
