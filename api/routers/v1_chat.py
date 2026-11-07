"""Chat routes: stream a turn as server-sent events, snapshot, report and reset a thread.

Thin handlers only.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Callable
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from starlette.background import BackgroundTask
from starlette.responses import StreamingResponse

from api.dependencies import (
    get_max_resumes,
    get_runtime,
    get_service_keys,
    get_settings,
    get_threads,
)
from api.schemas.chat import ChatRequest, StreamEvent, ThreadId, ThreadSnapshot
from api.services.agent_runner import AgentRuntime, resume_steps, run_resume, run_turn
from api.services.confirmation import ConfirmationError, TurnPlan, plan_turn
from api.services.report.builder import MEDIA_TYPE
from api.services.report.service import ReportUnavailable, thread_report
from api.services.snapshots import thread_snapshot
from api.services.sse import encode_event
from api.services.threads import ThreadStore
from api.services.turn_lifecycle import BUSY, TurnRefused, resume_turn_record, start_turn
from app.key_vault import ServiceKeys
from app.turns import FailureReason
from config.ui import UiSettings
from storage.turn_model import Turn

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])
UNKNOWN = "That run is no longer available."
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
REPORT_RESPONSES: dict[int | str, dict[str, object]] = {
    200: {
        "description": "The thread's assessment as a Word document (attachment).",
        "content": {MEDIA_TYPE: {"schema": {"type": "string", "format": "binary"}}},
    },
}


async def _frames(
    events: AsyncGenerator[StreamEvent],
    threads: ThreadStore,
    turn: Turn,
) -> AsyncGenerator[str]:
    """Encode the turn's events; a turn whose stream ends without a status (the client left)
    is interrupted so it can be resumed, and the thread's lease is released on every path."""
    try:
        async for event in events:
            yield encode_event(event)
    finally:
        await threads.turns.abandon(turn.id, FailureReason.WORKER_LOST)
        await threads.release(turn.thread_id)


def _streaming(
    frames: AsyncGenerator[str],
    threads: ThreadStore,
    thread_id: str,
) -> StreamingResponse:
    return StreamingResponse(
        frames,
        media_type="text/event-stream",
        headers=SSE_HEADERS,
        background=BackgroundTask(threads.release, thread_id),
    )


async def _holding_lease[T](
    threads: ThreadStore,
    thread_id: str,
    prepare: Callable[[], Awaitable[T]],
) -> T:
    """Claim the thread (409 when busy) and prepare its turn; the lease is released when the
    preparation is refused or fails."""
    if not await threads.claim(thread_id):
        raise HTTPException(status_code=409, detail=BUSY)
    try:
        return await prepare()
    except (ConfirmationError, TurnRefused) as error:
        await threads.release(thread_id)
        raise HTTPException(status_code=error.status, detail=error.detail) from error
    except BaseException:
        await threads.release(thread_id)
        raise


@router.post("/stream")
async def chat_stream(
    body: ChatRequest,
    keys: Annotated[ServiceKeys, Depends(get_service_keys)],
    threads: Annotated[ThreadStore, Depends(get_threads)],
    runtime: Annotated[AgentRuntime, Depends(get_runtime)],
) -> StreamingResponse:
    """Run one turn of ``thread_id`` and stream its events (an interrupted turn is abandoned)."""

    async def prepare() -> tuple[TurnPlan, Turn]:
        plan = await plan_turn(body, threads)
        return plan, await start_turn(threads, body.thread_id)

    plan, turn = await _holding_lease(threads, body.thread_id, prepare)
    events = run_turn(body, keys=keys, threads=threads, runtime=runtime, turn=turn, plan=plan)
    return _streaming(_frames(events, threads, turn), threads, body.thread_id)


@router.post("/threads/{thread_id}/resume")
async def resume_chat(
    thread_id: ThreadId,
    keys: Annotated[ServiceKeys, Depends(get_service_keys)],
    threads: Annotated[ThreadStore, Depends(get_threads)],
    runtime: Annotated[AgentRuntime, Depends(get_runtime)],
) -> StreamingResponse:
    """Continue the thread's interrupted turn from where it stopped and stream its events."""
    if not await threads.holds(thread_id):
        raise HTTPException(status_code=404, detail=UNKNOWN)

    async def steps() -> tuple[str, ...]:
        return await resume_steps(thread_id, keys=keys, threads=threads, runtime=runtime)

    async def prepare() -> Turn:
        return await resume_turn_record(threads, thread_id, runtime.max_resumes_per_turn, steps)

    turn = await _holding_lease(threads, thread_id, prepare)
    events = run_resume(keys=keys, threads=threads, runtime=runtime, turn=turn)
    return _streaming(_frames(events, threads, turn), threads, thread_id)


@router.get("/threads/{thread_id}")
async def get_thread(
    thread_id: ThreadId,
    threads: Annotated[ThreadStore, Depends(get_threads)],
    settings: Annotated[UiSettings, Depends(get_settings)],
    max_resumes: Annotated[int, Depends(get_max_resumes)],
) -> ThreadSnapshot:
    """A held thread's messages, workspace, usage and interruption, so the interface can
    restore it."""
    snapshot = await thread_snapshot(threads, thread_id, settings.pricing, max_resumes)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=UNKNOWN)
    return snapshot


@router.get("/threads/{thread_id}/report", response_class=Response, responses=REPORT_RESPONSES)
async def get_report(
    thread_id: ThreadId,
    threads: Annotated[ThreadStore, Depends(get_threads)],
    settings: Annotated[UiSettings, Depends(get_settings)],
) -> Response:
    """A held thread's findings as a Word report; never runs the agent or a tool."""
    try:
        report = await thread_report(threads, thread_id, settings, datetime.now().astimezone())
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
    threads: Annotated[ThreadStore, Depends(get_threads)],
) -> Response:
    """Forget a thread's history (new assessment)."""
    if not await threads.reset(thread_id):
        raise HTTPException(status_code=409, detail=BUSY)
    return Response(status_code=204)
