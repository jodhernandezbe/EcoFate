"""Chat routes: stream a turn as server-sent events, snapshot, report and reset a thread.

Thin handlers only.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Callable
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Response
from pydantic import Field
from starlette.responses import StreamingResponse

from api.core.session_guard import CurrentUser, current_user
from api.dependencies import (
    get_key_services,
    get_quota,
    get_runtime,
    get_settings,
    get_threads,
    get_turn_queue,
)
from api.schemas.chat import ChatRequest, StreamEvent, ThreadId, ThreadSnapshot
from api.schemas.quota import QuotaExhausted
from api.services.agent_runner import AgentRuntime, relay_turn, resume_steps
from api.services.confirmation import ConfirmationError, plan_turn
from api.services.key_setup import KeyServices, turn_key_loader
from api.services.quota import QuotaService
from api.services.report.builder import MEDIA_TYPE
from api.services.report.service import ReportUnavailable, thread_report
from api.services.snapshots import SnapshotOptions, thread_snapshot
from api.services.sse import encode_event
from api.services.threads import ThreadStore
from api.services.turn_lifecycle import BUSY, TurnRefused, resume_turn_record, start_turn
from api.services.turn_queue import (
    EVENTS_EXPIRED,
    UNAVAILABLE,
    QueueUnavailableError,
    Refund,
    TurnQueue,
    submit,
)
from app.turns.bus import turn_stream
from config.ui import UiSettings
from storage.keys import ThreadKey
from storage.turn_model import OPEN_STATUSES, TURN_ID_PATTERN, PlannedInput, Turn

router = APIRouter(prefix="/api/v1/chat", tags=["chat"], dependencies=[Depends(current_user)])
UNKNOWN = "That run is no longer available."
FINISHED = "That turn has already finished."
TurnId = Annotated[str, Path(pattern=TURN_ID_PATTERN)]
LastEventId = Annotated[int, Field(ge=0)]
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
REPORT_RESPONSES: dict[int | str, dict[str, object]] = {
    200: {
        "description": "The thread's assessment as a Word document (attachment).",
        "content": {MEDIA_TYPE: {"schema": {"type": "string", "format": "binary"}}},
    },
}


async def _frames(events: AsyncGenerator[StreamEvent]) -> AsyncGenerator[str]:
    """Encode the turn's events. The turn runs in the worker: a client that leaves stops only
    its own reading, never the turn."""
    async for event in events:
        yield encode_event(event)


def _streaming(events: AsyncGenerator[StreamEvent]) -> StreamingResponse:
    return StreamingResponse(_frames(events), media_type="text/event-stream", headers=SSE_HEADERS)


def _relay(
    turn: Turn,
    queue: TurnQueue,
    threads: ThreadStore,
    runtime: AgentRuntime,
    after_seq: int | None = None,
) -> StreamingResponse:
    events = relay_turn(
        turn,
        bus=queue.bus,
        threads=threads,
        runtime=runtime,
        timing=queue.timing,
        after_seq=after_seq,
    )
    return _streaming(events)


async def _submitted(
    turn: Turn,
    queue: TurnQueue,
    threads: ThreadStore,
    runtime: AgentRuntime,
    refund: Refund | None = None,
) -> None:
    """Enqueue the turn; 503 with a fixed message when the queue cannot be reached."""
    try:
        await submit(turn, queue, threads, refund, runtime.telemetry)
    except QueueUnavailableError:
        raise HTTPException(status_code=503, detail=UNAVAILABLE) from None


async def _holding_lease[T](
    threads: ThreadStore,
    key: ThreadKey,
    prepare: Callable[[], Awaitable[T]],
) -> T:
    """Claim the thread (409 when busy) and prepare its turn; the lease is released when the
    preparation is refused or fails."""
    if not await threads.claim(key):
        raise HTTPException(status_code=409, detail=BUSY)
    try:
        return await prepare()
    except (ConfirmationError, TurnRefused) as error:
        await threads.release(key)
        raise HTTPException(status_code=error.status, detail=error.detail) from error
    except BaseException:
        await threads.release(key)
        raise


@router.post("/stream", responses={429: {"model": QuotaExhausted}})
async def chat_stream(
    body: ChatRequest,
    user: CurrentUser,
    threads: Annotated[ThreadStore, Depends(get_threads)],
    runtime: Annotated[AgentRuntime, Depends(get_runtime)],
    quota: Annotated[QuotaService, Depends(get_quota)],
    queue: Annotated[TurnQueue, Depends(get_turn_queue)],
) -> StreamingResponse:
    """Queue one turn of ``thread_id`` for the worker and stream its events (an interrupted
    turn is abandoned); 503 when the queue cannot be reached.

    A new message counts against the user's daily quota (429 over it) once the thread is claimed
    and before anything runs; an answer to the thread's open request continues a counted turn
    and is free.
    """
    key = ThreadKey(user.id, body.thread_id)

    async def prepare() -> tuple[Turn, bool]:
        counted = body.answers is None and await quota.require(user)
        plan = await plan_turn(body, threads, key)
        planned = PlannedInput(body.message, plan.message, plan.note, counted)
        return await start_turn(threads, key, planned), counted

    turn, counted = await _holding_lease(threads, key, prepare)
    await _submitted(turn, queue, threads, runtime, quota.refund if counted else None)
    return _relay(turn, queue, threads, runtime)


@router.post("/threads/{thread_id}/resume")
async def resume_chat(
    thread_id: ThreadId,
    user: CurrentUser,
    keys: Annotated[KeyServices, Depends(get_key_services)],
    threads: Annotated[ThreadStore, Depends(get_threads)],
    runtime: Annotated[AgentRuntime, Depends(get_runtime)],
    queue: Annotated[TurnQueue, Depends(get_turn_queue)],
) -> StreamingResponse:
    """Queue the thread's interrupted turn to continue from where it stopped and stream its
    events; 503 when the queue cannot be reached."""
    key = ThreadKey(user.id, thread_id)
    loader = turn_key_loader(keys, user.id)
    if not await threads.holds(key):
        raise HTTPException(status_code=404, detail=UNKNOWN)

    async def steps() -> tuple[str, ...]:
        return await resume_steps(key, keys=loader, threads=threads, runtime=runtime)

    async def prepare() -> Turn:
        return await resume_turn_record(threads, key, runtime.max_resumes_per_turn, steps)

    turn = await _holding_lease(threads, key, prepare)
    await _submitted(turn, queue, threads, runtime)
    return _relay(turn, queue, threads, runtime)


@router.get("/turns/{turn_id}/events")
async def turn_events(
    turn_id: TurnId,
    user: CurrentUser,
    threads: Annotated[ThreadStore, Depends(get_threads)],
    runtime: Annotated[AgentRuntime, Depends(get_runtime)],
    queue: Annotated[TurnQueue, Depends(get_turn_queue)],
    last_event_id: Annotated[LastEventId | None, Header()] = None,
) -> StreamingResponse:
    """Reattach to a turn's events after the ``Last-Event-ID`` (from the first when absent);
    404 for an unknown or another user's turn, 410 once its events have expired."""
    turn = await threads.turns.get(user.id, turn_id)
    if turn is None:
        raise HTTPException(status_code=404, detail=UNKNOWN)
    if not await queue.bus.exists(turn_stream(turn.id, turn.resume_count)):
        raise HTTPException(status_code=410, detail=EVENTS_EXPIRED)
    return _relay(turn, queue, threads, runtime, last_event_id)


@router.post("/turns/{turn_id}/cancel", status_code=202)
async def cancel_turn(
    turn_id: TurnId,
    user: CurrentUser,
    threads: Annotated[ThreadStore, Depends(get_threads)],
) -> Response:
    """Ask a queued or running turn to stop after its current step (202); its stream then ends
    as interrupted (``cancelled``). 409 for a finished turn, 404 for an unknown one."""
    turn = await threads.turns.get(user.id, turn_id)
    if turn is None:
        raise HTTPException(status_code=404, detail=UNKNOWN)
    if turn.status not in OPEN_STATUSES or not await threads.turns.request_cancel(user.id, turn_id):
        raise HTTPException(status_code=409, detail=FINISHED)
    return Response(status_code=202)


async def _snapshot(
    threads: ThreadStore,
    key: ThreadKey,
    settings: UiSettings,
    runtime: AgentRuntime,
    queue: TurnQueue,
) -> ThreadSnapshot:
    options = SnapshotOptions(
        pricing=settings.pricing,
        max_resumes=runtime.max_resumes_per_turn,
        rules=runtime.workspace_rules,
        stale_after=queue.timing.stale_after,
    )
    snapshot = await thread_snapshot(threads, key, options)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=UNKNOWN)
    return snapshot


@router.get("/current-thread")
async def get_current_thread(
    user: CurrentUser,
    threads: Annotated[ThreadStore, Depends(get_threads)],
    settings: Annotated[UiSettings, Depends(get_settings)],
    runtime: Annotated[AgentRuntime, Depends(get_runtime)],
    queue: Annotated[TurnQueue, Depends(get_turn_queue)],
) -> ThreadSnapshot:
    """The snapshot of the user's most recently used thread, so a reloaded page continues it
    (and reattaches to a turn still running); 404 when the user has none."""
    thread_id = await threads.latest_thread(user.id)
    if thread_id is None:
        raise HTTPException(status_code=404, detail=UNKNOWN)
    return await _snapshot(threads, ThreadKey(user.id, thread_id), settings, runtime, queue)


@router.get("/threads/{thread_id}")
async def get_thread(
    thread_id: ThreadId,
    user: CurrentUser,
    threads: Annotated[ThreadStore, Depends(get_threads)],
    settings: Annotated[UiSettings, Depends(get_settings)],
    runtime: Annotated[AgentRuntime, Depends(get_runtime)],
    queue: Annotated[TurnQueue, Depends(get_turn_queue)],
) -> ThreadSnapshot:
    """A held thread's messages, workspace, usage, interruption and running turn, so the
    interface can restore it (and reattach to a turn still running)."""
    return await _snapshot(threads, ThreadKey(user.id, thread_id), settings, runtime, queue)


@router.get("/threads/{thread_id}/report", response_class=Response, responses=REPORT_RESPONSES)
async def get_report(
    thread_id: ThreadId,
    user: CurrentUser,
    threads: Annotated[ThreadStore, Depends(get_threads)],
    settings: Annotated[UiSettings, Depends(get_settings)],
) -> Response:
    """A held thread's findings as a Word report; never runs the agent or a tool."""
    try:
        key = ThreadKey(user.id, thread_id)
        report = await thread_report(threads, key, settings, datetime.now().astimezone())
    except ReportUnavailable as error:
        raise HTTPException(status_code=error.status, detail=error.detail) from error
    disposition = f'attachment; filename="{report.name}"'
    return Response(
        report.content,
        media_type=MEDIA_TYPE,
        headers={"Content-Disposition": disposition},
    )


@router.delete("/threads/{thread_id}", status_code=204)
async def reset_thread(
    thread_id: ThreadId,
    user: CurrentUser,
    threads: Annotated[ThreadStore, Depends(get_threads)],
) -> Response:
    """Forget a thread's history (new assessment)."""
    key = ThreadKey(user.id, thread_id)
    if not await threads.holds(key):  # unknown and another user's look the same
        raise HTTPException(status_code=404, detail=UNKNOWN)
    if not await threads.reset(key):
        raise HTTPException(status_code=409, detail=BUSY)
    return Response(status_code=204)
