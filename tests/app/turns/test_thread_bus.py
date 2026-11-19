"""The thread-level stream: reconnection without gaps or repeats, expiry, tenancy by name."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator
from uuid import UUID

import pytest
from redis.asyncio import Redis

from app.turns.bus import entries_text
from app.turns.thread_bus import (
    MemoryThreadBus,
    RedisThreadBus,
    ThreadEventBus,
    is_entry_id,
    publish_quietly,
    thread_stream,
)
from storage.keys import ThreadKey

pytestmark = pytest.mark.anyio
STREAM = thread_stream(ThreadKey(UUID(int=99), "contract"))


@pytest.fixture(params=["memory", pytest.param("redis", marks=pytest.mark.redis)])
async def shared(request: pytest.FixtureRequest) -> AsyncGenerator[ThreadEventBus]:
    """The bus under test: in memory, and over a real Redis Stream (``make test-redis``)."""
    if request.param == "memory":
        yield MemoryThreadBus()
        return
    client = Redis.from_url(os.environ["ECOFATE_TEST_REDIS_URL"], decode_responses=True)
    try:
        await client.delete(STREAM)
        yield RedisThreadBus(client, max_length=1000)
        await client.delete(STREAM)
    finally:
        await client.aclose()


async def test_entries_come_in_order_and_a_reader_resumes_without_gap_or_repeat(
    shared: ThreadEventBus,
) -> None:
    for n in range(5):
        await shared.publish(STREAM, {"kind": "job.running", "n": n}, 60)
    everything = await shared.read(STREAM, None, 0.05)
    assert [r["n"] for _, r in everything] == [0, 1, 2, 3, 4]
    assert len({i for i, _ in everything}) == 5 and all(is_entry_id(i) for i, _ in everything)
    seen = everything[2][0]  # the connection dropped after the third entry
    assert [r["n"] for _, r in await shared.read(STREAM, seen, 0.05)] == [3, 4]
    assert await shared.read(STREAM, everything[-1][0], 0.05) == []


async def test_a_stream_of_one_thread_is_not_the_stream_of_another(shared: ThreadEventBus) -> None:
    other = thread_stream(ThreadKey(UUID(int=98), "contract"))
    await shared.publish(STREAM, {"kind": "job.ended"}, 60)
    assert await shared.read(other, None, 0.05) == []


def test_a_redis_entry_decodes_to_its_id_and_record() -> None:
    items: list[object] = [("7-1", {"data": '{"kind": "done"}'}), ("8-0", {"data": "[1]"})]
    assert entries_text(items) == [("7-1", {"kind": "done"})]


async def _ids(bus: MemoryThreadBus, stream: str, after: str | None) -> list[str]:
    return [entry_id for entry_id, _ in await bus.read(stream, after, 0.01)]


async def test_a_reader_that_reconnects_with_the_last_id_misses_and_repeats_nothing() -> None:
    bus, stream = MemoryThreadBus(), "s"
    for n in range(5):
        await bus.publish(stream, {"kind": "job.running", "n": n}, 60)
    first = await _ids(bus, stream, None)
    assert len(first) == 5
    seen = first[:3]  # the connection dropped after the third entry
    await bus.publish(stream, {"kind": "job.ended"}, 60)
    again = await _ids(bus, stream, seen[-1])
    assert again == [*first[3:], "6-0"]
    assert await _ids(bus, stream, again[-1]) == []


async def test_a_blocked_reader_is_woken_by_a_publish() -> None:
    bus = MemoryThreadBus()
    waiting = asyncio.create_task(bus.read("s", None, 5.0))
    await asyncio.sleep(0.01)
    await bus.publish("s", {"kind": "job.queued"}, 60)
    assert [r["kind"] for _, r in await waiting] == ["job.queued"]


async def test_the_stream_is_capped_and_expires() -> None:
    now = [0.0]
    bus = MemoryThreadBus(lambda: now[0], max_length=3)
    for n in range(5):
        await bus.publish("s", {"n": n}, 10)
    assert [r["n"] for _, r in await bus.read("s", None, 0.01)] == [2, 3, 4]
    now[0] = 11.0
    assert await bus.read("s", None, 0.01) == []


def test_two_users_with_the_same_thread_id_have_different_streams() -> None:
    mine, theirs = ThreadKey(UUID(int=1), "same"), ThreadKey(UUID(int=2), "same")
    assert thread_stream(mine) != thread_stream(theirs)


async def test_a_publish_failure_never_reaches_the_caller() -> None:
    class Broken:
        async def publish(self, stream: str, record: dict[str, object], ttl: int) -> None:
            raise OSError("down")

        async def read(self, *args: object) -> list[object]:
            return []

    await publish_quietly(Broken(), ThreadKey(UUID(int=1), "t"), {"kind": "x"}, 1)  # type: ignore[arg-type]


def test_an_entry_id_has_the_shape_redis_writes() -> None:
    assert is_entry_id("1700000000000-0") and is_entry_id("3-0")
    assert not any(is_entry_id(v) for v in ("", "abc", "1", "1-", "1-2-3", "$", "1; DROP"))
