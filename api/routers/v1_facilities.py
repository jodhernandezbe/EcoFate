"""Facility route: one facility of a thread's workspace. Thin handler only."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path

from api.core.session_guard import CurrentUser, current_user
from api.dependencies import get_threads
from api.schemas.chat import ThreadId
from api.schemas.workspace import Facility
from api.services.threads import ThreadStore
from storage.keys import ThreadKey

router = APIRouter(
    prefix="/api/v1/facilities",
    tags=["facilities"],
    dependencies=[Depends(current_user)],
)
FrsId = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
NOT_FOUND = "No such facility in this thread."


@router.get("/{frs_id}")
async def get_facility(
    frs_id: FrsId,
    thread_id: ThreadId,
    user: CurrentUser,
    threads: Annotated[ThreadStore, Depends(get_threads)],
) -> Facility:
    """The facility with this FRS ID as the thread's workspace currently shows it."""
    state = await threads.workspace(ThreadKey(user.id, thread_id))
    found = next((f for f in state.facilities if f.frs_id == frs_id), None) if state else None
    if found is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return found
