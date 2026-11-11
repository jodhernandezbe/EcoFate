"""Wire models of the daily turn quota: the endpoint's answer and the 429 body."""

from __future__ import annotations

from datetime import datetime

from api.schemas.base import ContractModel


class QuotaStatus(ContractModel):
    """The signed-in user's quota today.

    Attributes:
        applies: Whether the quota applies to this user (false when it is disabled or the user
            is an exempt administrator; the other figures are then absent).
        limit: Turns allowed per UTC day.
        used: Turns counted today.
        remaining: Turns left today.
        resets_at: The next 00:00 UTC (the figures start again then).
    """

    applies: bool
    limit: int | None
    used: int | None
    remaining: int | None
    resets_at: datetime | None


class QuotaExhausted(ContractModel):
    """The body of the 429 answer to a new turn over the quota.

    Attributes:
        detail: Fixed message from configuration.
        limit: Turns allowed per UTC day.
        resets_at: The next 00:00 UTC.
        correlation_id: Id to quote when asking about this refusal.
    """

    detail: str
    limit: int
    resets_at: datetime
    correlation_id: str
