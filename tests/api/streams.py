"""Helpers for the streaming tests: an SSE parser, and a turn run the way the chat route runs it
(queued, run by the worker's job in-process, relayed from its stream). The scripted chat model
is in tests/fakes.py."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import replace
from functools import partial
from typing import Any
from uuid import UUID

from api.main import queue_setup
from api.schemas.chat import ChatRequest, StreamEvent
from api.services.agent_runner import AgentRuntime, relay_turn
from api.services.confirmation import TurnPlan
from api.services.key_setup import KeyLoader
from api.services.threads import ThreadStore
from api.services.turn_queue import TurnQueue, submit
from app.task_queue import InProcessEnqueuer
from app.turns.bus import MemoryBus
from app.turns.job import run_background_turn
from app.turns.recording import BackgroundServices
from storage.turn_model import PlannedInput
from tests.api.keys import OWNER, owned

Refund = Callable[[str], Awaitable[bool]]


def parse_sse(text: str) -> list[dict[str, Any]]:
    """Decode an SSE body into its JSON events; each frame's id is its event's ``seq``."""
    frames = [frame for frame in text.split("\n\n") if frame.strip()]
    events: list[dict[str, Any]] = []
    for frame in frames:
        lines = frame.split("\n")
        data = [line for line in lines if line.startswith("data: ")]
        assert len(data) == 1, frame
        event = json.loads(data[0].removeprefix("data: "))
        assert f"id: {event['seq']}" in lines, frame
        events.append(event)
    return events


def in_process_queue(
    threads: ThreadStore,
    runtime: AgentRuntime,
    keys: KeyLoader,
    refund: Refund | None = None,
) -> TurnQueue:
    """A queue that runs each turn with the worker's job in this process."""
    setup = queue_setup(MemoryBus(), None)

    async def give_back(user_id: UUID, turn_id: str) -> bool:
        return await refund(turn_id) if refund is not None else False

    services = BackgroundServices(
        threads=threads,
        bus=setup.bus,
        load_keys=lambda user_id: keys(),
        build_model=runtime.build_model,
        refund=give_back,
        turn_settings=runtime.turn_settings(),
        settings=replace(setup.background, max_resumes=runtime.max_resumes_per_turn),
    )
    enqueuer = InProcessEnqueuer(partial(run_background_turn, services=services), setup.running)
    return TurnQueue(setup.bus, enqueuer, setup.timing, setup.background)


async def begun_turn(
    request: ChatRequest,
    *,
    threads: ThreadStore,
    runtime: AgentRuntime,
    keys: KeyLoader,
    owner_id: UUID = OWNER,
    plan: TurnPlan | None = None,
    refund: Refund | None = None,
) -> AsyncGenerator[StreamEvent]:
    """One turn as the chat route runs it: recorded as queued with its input, run by the
    worker's job in this process, and relayed from its stream."""
    chosen = plan or TurnPlan(message=request.message, note="")
    planned = PlannedInput(request.message, chosen.message, chosen.note, counted=refund is not None)
    turn = await threads.turns.begin(owned(request.thread_id, owner_id), planned)
    assert turn is not None, "the thread already has an open turn"
    queue = in_process_queue(threads, runtime, keys, refund)
    await submit(turn, queue, threads, None, runtime.telemetry)
    relayed = relay_turn(turn, bus=queue.bus, threads=threads, runtime=runtime, timing=queue.timing)
    async for event in relayed:
        yield event
