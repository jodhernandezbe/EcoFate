"""Helpers for the streaming tests: an SSE parser (the scripted chat model is in tests/fakes.py)."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from contextlib import aclosing
from typing import Any

from api.schemas.chat import ChatRequest, StreamEvent
from api.services.agent_runner import run_turn
from api.services.threads import ThreadStore


def parse_sse(text: str) -> list[dict[str, Any]]:
    """Decode an SSE body into its JSON events."""
    frames = [frame for frame in text.split("\n\n") if frame.strip()]
    assert all(frame.startswith("data: ") for frame in frames), frames
    return [json.loads(frame.removeprefix("data: ")) for frame in frames]


async def begun_turn(
    request: ChatRequest,
    *,
    threads: ThreadStore,
    **options: Any,
) -> AsyncGenerator[StreamEvent]:
    """``run_turn`` for a turn recorded as running first, as the chat route does."""
    turn = await threads.turns.begin(request.thread_id)
    assert turn is not None, "the thread already has an open turn"
    async with aclosing(run_turn(request, threads=threads, turn=turn, **options)) as events:
        async for event in events:
            yield event
