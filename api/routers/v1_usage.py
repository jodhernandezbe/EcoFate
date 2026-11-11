"""Usage routes: the signed-in user's daily turn quota. Thin handlers only."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from api.core.session_guard import CurrentUser, current_user
from api.dependencies import get_quota
from api.schemas.quota import QuotaStatus
from api.services.quota import QuotaService

router = APIRouter(prefix="/api/v1/usage", tags=["usage"], dependencies=[Depends(current_user)])


@router.get("/quota")
async def get_quota_status(
    user: CurrentUser,
    quota: Annotated[QuotaService, Depends(get_quota)],
) -> QuotaStatus:
    """The signed-in user's quota today: limit, used, remaining and the next reset (UTC).

    ``applies`` is false (and the figures absent) when the quota is disabled or the user is an
    exempt administrator. Only the caller's own count is ever read.
    """
    standing = await quota.standing(user)
    if standing is None:
        return QuotaStatus(applies=False, limit=None, used=None, remaining=None, resets_at=None)
    return QuotaStatus(
        applies=True,
        limit=standing.limit,
        used=standing.used,
        remaining=standing.remaining,
        resets_at=standing.reset.at,
    )
