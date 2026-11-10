"""Monitoring routes: recorded sessions and one session's timeline. Thin handlers only."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path

from api.core.session_guard import require_admin
from api.dependencies import get_monitoring
from api.schemas.chat import THREAD_ID_PATTERN
from api.schemas.monitoring import SessionDetailResponse, SessionsResponse
from api.services.monitoring.service import MonitoringService

router = APIRouter(
    prefix="/api/v1/monitoring",
    tags=["monitoring"],
    dependencies=[Depends(require_admin)],
)
SessionIdPath = Annotated[str, Path(pattern=THREAD_ID_PATTERN)]
NOT_FOUND = "No such session was recorded."


@router.get("/sessions")
async def list_sessions(
    service: Annotated[MonitoringService, Depends(get_monitoring)],
) -> SessionsResponse:
    """The most recent recorded sessions, newest first."""
    return await service.sessions()


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: SessionIdPath,
    service: Annotated[MonitoringService, Depends(get_monitoring)],
) -> SessionDetailResponse:
    """One recorded session with its turns, model calls and tool calls."""
    detail = await service.session(session_id)
    if detail.state == "ok" and detail.session is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return detail
