"""Chat routes: stream a turn as server-sent events, snapshot, report and reset a thread.

Thin handlers only.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from starlette.background import BackgroundTask
from starlette.responses import StreamingResponse

from api.dependencies import get_runtime, get_service_keys, get_settings, get_threads
from api.schemas.chat import ChatRequest, ThreadId, ThreadSnapshot
from api.services.agent_runner import AgentRuntime, run_turn
from api.services.confirmation import ConfirmationError, TurnPlan, plan_turn
from api.services.report.builder import MEDIA_TYPE
from api.services.report.service import ReportUnavailable, thread_report
from api.services.snapshots import thread_snapshot
from api.services.sse import encode_event
from api.services.threads import ThreadStore
from app.key_vault import ServiceKeys
from config.ui import UiSettings

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])
UNKNOWN = "That run is no longer available."
BUSY = "A turn is already running for this thread."
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
REPORT_RESPONSES: dict[int | str, dict[str, object]] = {
    200: {
        "description": "The thread's assessment as a Word document (attachment).",
        "content": {MEDIA_TYPE: {"schema": {"type": "string", "format": "binary"}}},
    },
}


async def _frames(
    body: ChatRequest,
    keys: ServiceKeys,
    threads: ThreadStore,
    runtime: AgentRuntime,
    plan: TurnPlan,
) -> AsyncGenerator[str]:
    try:
        async for event in run_turn(body, keys=keys, threads=threads, runtime=runtime, plan=plan):
            yield encode_event(event)
    finally:
        threads.release(body.thread_id)


@router.post("/stream")
async def chat_stream(
    body: ChatRequest,
    keys: Annotated[ServiceKeys, Depends(get_service_keys)],
    threads: Annotated[ThreadStore, Depends(get_threads)],
    runtime: Annotated[AgentRuntime, Depends(get_runtime)],
) -> StreamingResponse:
    """Run one turn of ``thread_id`` and stream its events."""
    if not threads.claim(body.thread_id):
        raise HTTPException(status_code=409, detail=BUSY)
    try:
        plan = plan_turn(body, threads)
    except ConfirmationError as error:
        threads.release(body.thread_id)
        raise HTTPException(status_code=error.status, detail=error.detail) from error
    return StreamingResponse(
        _frames(body, keys, threads, runtime, plan),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
        background=BackgroundTask(threads.release, body.thread_id),
    )


@router.get("/threads/{thread_id}")
def get_thread(
    thread_id: ThreadId,
    threads: Annotated[ThreadStore, Depends(get_threads)],
    settings: Annotated[UiSettings, Depends(get_settings)],
) -> ThreadSnapshot:
    """A held thread's messages, workspace and usage, so the interface can resume it."""
    snapshot = thread_snapshot(threads, thread_id, settings.pricing)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=UNKNOWN)
    return snapshot


@router.get("/threads/{thread_id}/report", response_class=Response, responses=REPORT_RESPONSES)
def get_report(
    thread_id: ThreadId,
    threads: Annotated[ThreadStore, Depends(get_threads)],
    settings: Annotated[UiSettings, Depends(get_settings)],
) -> Response:
    """A held thread's findings as a Word report; never runs the agent or a tool."""
    try:
        report = thread_report(threads, thread_id, settings, datetime.now().astimezone())
    except ReportUnavailable as error:
        raise HTTPException(status_code=error.status, detail=error.detail) from error
    disposition = f'attachment; filename="{report.name}"'
    return Response(
        report.content,
        media_type=MEDIA_TYPE,
        headers={"Content-Disposition": disposition},
    )


@router.delete("/threads/{thread_id}", status_code=204)
def reset_thread(
    thread_id: ThreadId,
    threads: Annotated[ThreadStore, Depends(get_threads)],
) -> Response:
    """Forget a thread's history (new assessment)."""
    if not threads.reset(thread_id):
        raise HTTPException(status_code=409, detail=BUSY)
    return Response(status_code=204)
