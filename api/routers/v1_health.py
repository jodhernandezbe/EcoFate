"""Health route for container health checks: the database answers; no agent, no key."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import cast

from fastapi import APIRouter, Request, Response

from api.schemas.health import HealthResponse

router = APIRouter(prefix="/api", tags=["health"])
_UNAVAILABLE = 503


@router.get(
    "/health",
    responses={_UNAVAILABLE: {"model": HealthResponse, "description": "The database is down."}},
)
async def health(request: Request, response: Response) -> HealthResponse:
    """200 ``ok`` when the database answers within the health timeout, else 503 ``unavailable``.

    Reads no key and runs no agent; the answer never carries exception text or the URL.
    """
    check = cast(Callable[[], Awaitable[bool]], request.app.state.health_check)
    if await check():
        return HealthResponse()
    response.status_code = _UNAVAILABLE
    return HealthResponse(status="unavailable")
