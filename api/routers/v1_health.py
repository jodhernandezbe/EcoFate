"""Liveness route for container health checks: no agent, no key, no external call."""

from __future__ import annotations

from fastapi import APIRouter

from api.schemas.health import HealthResponse

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health() -> HealthResponse:
    """Answer while the web program is serving; reads nothing and calls nothing."""
    return HealthResponse()
