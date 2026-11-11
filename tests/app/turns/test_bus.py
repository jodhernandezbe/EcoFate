"""The turn event stream: order, reading from a ``seq``, waiting, expiry (memory and Redis)."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator

import pytest
from redis.asyncio import Redis

from app.turns.bus import MemoryBus, RedisStreamBus, TurnEventBus, entries_of, turn_stream

pytestmark = pytest.mark.anyio
STREAM = turn_stream("a" * 32, 0)


class Clock:
    """Monotonic seconds a test moves by hand."""

    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture(params=["memory", pytest.param("redis", marks=pytest.mark.redis)])
async def bus(request: pytest.FixtureRequest) -> AsyncGenerator[TurnEventBus]:
    if request.param == "memory":
        yield MemoryBus()
        return
    client = Redis.from_url(os.environ["ECOFATE_TEST_REDIS_URL"], decode_responses=True)
    try:
        await client.delete(STREAM)
        yield RedisStreamBus(client, max_length=1000)
        await client.delete(STREAM)
    finally:
        await client.aclose()


async def _fill(bus: TurnEventBus, count: int) -> None:
    for seq in range(count):
        await bus.publish(STREAM, seq, {"kind": "text", "text": f"t{seq}"}, 60)


async def test_records_come_back_in_order_from_the_start(bus: TurnEventBus) -> None:
    await _fill(bus, 3)
    entries = await bus.read(STREAM, None, 0.01)
    assert [seq for seq, _ in entries] == [0, 1, 2]
    assert entries[1][1] == {"kind": "text", "text": "t1"}


async def test_a_reader_resumes_after_its_last_seq_without_repeats(bus: TurnEventBus) -> None:
    await _fill(bus, 45)
    entries = await bus.read(STREAM, 41, 0.01)
    assert [seq for seq, _ in entries] == [42, 43, 44]
    assert await bus.read(STREAM, 44, 0.01) == []


async def test_a_waiting_reader_gets_the_next_record(bus: TurnEventBus) -> None:
    reader = asyncio.create_task(bus.read(STREAM, None, 2.0))
    await asyncio.sleep(0.05)
    await bus.publish(STREAM, 0, {"kind": "done"}, 60)
    assert await asyncio.wait_for(reader, 2.0) == [(0, {"kind": "done"})]


async def test_exists_until_published_and_streams_are_separate(bus: TurnEventBus) -> None:
    other = turn_stream("a" * 32, 1)
    assert not await bus.exists(STREAM)
    await _fill(bus, 1)
    assert await bus.exists(STREAM)
    assert not await bus.exists(other)
    assert await bus.read(other, None, 0.01) == []


async def test_a_memory_stream_expires_after_its_last_lifetime() -> None:
    clock = Clock()
    bus = MemoryBus(clock)
    await bus.publish(STREAM, 0, {"kind": "text", "text": "x"}, 60)
    clock.now += 50
    await bus.publish(STREAM, 1, {"kind": "done"}, 10)  # the end sets a shorter lifetime
    clock.now += 9
    assert await bus.exists(STREAM)
    clock.now += 2
    assert not await bus.exists(STREAM)
    assert await bus.read(STREAM, None, 0.01) == []


@pytest.mark.redis
async def test_a_redis_stream_expires() -> None:
    client = Redis.from_url(os.environ["ECOFATE_TEST_REDIS_URL"], decode_responses=True)
    try:
        bus = RedisStreamBus(client, max_length=1000)
        await bus.publish(STREAM, 0, {"kind": "done"}, 1)
        assert await bus.exists(STREAM)
        await asyncio.sleep(1.5)
        assert not await bus.exists(STREAM)
    finally:
        await client.aclose()


async def test_records_are_copies() -> None:
    bus = MemoryBus()
    record: dict[str, object] = {"kind": "text", "text": "x"}
    await bus.publish(STREAM, 0, record, 60)
    record["text"] = "changed"
    ((_, stored),) = await bus.read(STREAM, None, 0.01)
    stored["text"] = "changed too"
    assert await bus.read(STREAM, None, 0.01) == [(0, {"kind": "text", "text": "x"})]


@pytest.mark.parametrize(
    "items",
    [
        [("not-a-number-1", {"data": "{}"})],
        [("3-1", {"other": "{}"})],
        [("3-1", {"data": "not json"})],
        [("3-1", {"data": "[1, 2]"})],
        ["garbage"],
    ],
)
def test_a_redis_entry_that_does_not_decode_is_skipped(items: list[object]) -> None:
    assert entries_of(items) == []


def test_a_redis_entry_decodes_to_its_seq_and_record() -> None:
    assert entries_of([("7-1", {"data": '{"kind": "done"}'})]) == [(7, {"kind": "done"})]
