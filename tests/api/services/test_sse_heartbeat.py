"""Tests for the keepalive of a quiet event stream (``with_heartbeat``)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

import pytest

from api.services.sse import KEEPALIVE, with_heartbeat

pytestmark = pytest.mark.anyio
TICK = 0.02


async def _frames(*items: tuple[float, str]) -> AsyncGenerator[str]:
    for delay, frame in items:
        await asyncio.sleep(delay)
        yield frame


async def _collect(frames: AsyncGenerator[str]) -> list[str]:
    return [frame async for frame in frames]


async def test_frames_that_keep_coming_pass_through_unchanged() -> None:
    out = await _collect(with_heartbeat(_frames((0, "a"), (0, "b")), TICK * 10))
    assert out == ["a", "b"]


async def test_a_quiet_stretch_sends_keepalives_and_loses_no_frame() -> None:
    out = await _collect(with_heartbeat(_frames((0, "a"), (TICK * 6, "b")), TICK))
    assert out[0] == "a" and out[-1] == "b"
    keepalives = out[1:-1]
    assert keepalives and set(keepalives) == {KEEPALIVE}


async def test_keepalive_is_an_sse_comment() -> None:
    assert KEEPALIVE.startswith(":") and KEEPALIVE.endswith("\n\n")


async def test_an_empty_stream_ends_without_frames() -> None:
    assert await _collect(with_heartbeat(_frames(), TICK)) == []


async def test_leaving_early_cancels_the_pending_read() -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def slow() -> AsyncGenerator[str]:
        started.set()
        try:
            await asyncio.sleep(10)
            yield "never"
        except asyncio.CancelledError:
            cancelled.set()
            raise

    stream = with_heartbeat(slow(), TICK)
    assert await anext(stream) == KEEPALIVE
    await stream.aclose()
    await asyncio.sleep(0)
    assert started.is_set() and cancelled.is_set()


async def test_leaving_early_closes_the_wrapped_stream() -> None:
    closed = asyncio.Event()

    async def frames() -> AsyncGenerator[str]:
        try:
            yield "a"
            await asyncio.sleep(10)
            yield "never"
        finally:
            closed.set()

    stream = with_heartbeat(frames(), TICK)
    assert await anext(stream) == "a"
    await stream.aclose()
    assert closed.is_set()
