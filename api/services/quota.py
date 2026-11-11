"""The daily quota of agent turns: who it applies to, counting, refunds and status.

The store counts atomically in the database (``storage.quota``); this module decides whether the
quota applies to a user (``[limits]``: enabled, administrators exempt) and what a refusal tells
the caller: the limit, the next 00:00 UTC and the seconds until then. It never reads the clock
to decide a day (the database does); the clock only words the reset time.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Protocol
from uuid import UUID

from api.core.exceptions import QuotaExhaustedError
from app.turns import FailureReason, resumable
from config.limits import LimitSettings
from storage.account_model import Role, User
from storage.errors import DATABASE_ERRORS

logger = logging.getLogger(__name__)
Refund = Callable[[str], Awaitable[bool]]


class QuotaStore(Protocol):
    """What the service needs from storage (``storage.quota.QuotaRepository``)."""

    async def consume(self, user_id: UUID, limit: int) -> int | None: ...

    async def refund(self, user_id: UUID, turn_id: str) -> bool: ...

    async def usage(self, user_id: UUID) -> int: ...


class UncountedQuota:
    """The store behind a quota that is switched off: it counts nothing and is never asked to."""

    async def consume(self, user_id: UUID, limit: int) -> int | None:
        """Never called by a disabled quota; accepts the turn without counting it."""
        return 0

    async def refund(self, user_id: UUID, turn_id: str) -> bool:
        """Nothing was counted, so nothing is given back."""
        return False

    async def usage(self, user_id: UUID) -> int:
        """No turns are counted."""
        return 0


@dataclass(frozen=True)
class Reset:
    """When the day's count starts again.

    Attributes:
        at: The next 00:00 UTC.
        seconds: Whole seconds until then, at least 1 (the ``Retry-After`` value).
    """

    at: datetime
    seconds: int


@dataclass(frozen=True)
class Standing:
    """A user's quota today (only for a user it applies to).

    Attributes:
        limit: Turns allowed per UTC day.
        used: Turns counted today.
        reset: When the count starts again.
    """

    limit: int
    used: int
    reset: Reset

    @property
    def remaining(self) -> int:
        """Turns left today (never negative, even after the limit was lowered)."""
        return max(self.limit - self.used, 0)


@dataclass(frozen=True)
class Admission:
    """Whether a new turn may start.

    Attributes:
        accepted: True when the turn may run.
        counted: True when it used one of the user's turns (false when the quota does not
            apply), so a refund is only ever made for a counted turn.
        reset: When the quota resets (set when refused).
    """

    accepted: bool
    counted: bool
    reset: Reset | None = None


def _utc_now() -> datetime:
    return datetime.now(UTC)


class QuotaService:
    """The daily quota over a store and the ``[limits]`` settings.

    Args:
        store: Counts turns per user and day.
        settings: The ``[limits]`` settings.
        now: The current time (a test replaces it); only used to word the reset time.
    """

    def __init__(
        self,
        store: QuotaStore,
        settings: LimitSettings,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._store = store
        self._settings = settings
        self._now = now

    @property
    def limit(self) -> int:
        """Turns allowed per user per UTC day."""
        return self._settings.daily_turns_per_user

    @property
    def message(self) -> str:
        """The fixed text of a refusal."""
        return self._settings.exhausted_message

    def applies_to(self, user: User) -> bool:
        """Whether ``user``'s turns are counted."""
        if not self._settings.enabled:
            return False
        return not (self._settings.admin_exempt and user.role is Role.ADMIN)

    def reset(self) -> Reset:
        """The next 00:00 UTC and the seconds until it."""
        now = self._now().astimezone(UTC)
        at = datetime.combine(now.date() + timedelta(days=1), time(), tzinfo=UTC)
        return Reset(at, max(1, math.ceil((at - now).total_seconds())))

    async def admit(self, user: User) -> Admission:
        """Count one new turn for ``user``, or refuse it when the limit is reached."""
        if not self.applies_to(user):
            return Admission(accepted=True, counted=False)
        if await self._store.consume(user.id, self.limit) is None:
            return Admission(accepted=False, counted=False, reset=self.reset())
        return Admission(accepted=True, counted=True)

    async def require(self, user: User) -> bool:
        """Count one new turn for ``user``.

        Returns:
            True when the turn was counted (False when the quota does not apply to the user).

        Raises:
            QuotaExhaustedError: The limit is reached (nothing is counted).
        """
        admission = await self.admit(user)
        if not admission.accepted and admission.reset is not None:
            reset = admission.reset
            raise QuotaExhaustedError(self.message, self.limit, reset.at, reset.seconds)
        return admission.counted

    async def refund(self, user_id: UUID, turn_id: str) -> bool:
        """Give back a counted turn that ended before its first model call (once)."""
        return await self._store.refund(user_id, turn_id)

    async def standing(self, user: User) -> Standing | None:
        """``user``'s quota today; None when the quota does not apply to them."""
        if not self.applies_to(user):
            return None
        return Standing(self.limit, await self._store.usage(user.id), self.reset())


async def refund_if_unused(
    refund: Refund | None,
    turn_id: str,
    *,
    reason: FailureReason | None,
    model_calls: int,
) -> bool:
    """Give back a counted turn that stopped before it reached the model.

    Only a turn that stopped for a reason it cannot resume from, with no model call recorded,
    is given back. A resumable stop is not: the turn continues for free, so refunding it too
    would let one count pay for any number of turns. A database failure is logged (class only)
    and never fails the turn.

    Args:
        refund: Gives the turn back by id; None when the turn was not counted.
        turn_id: The turn's id.
        reason: Why the turn stopped; None when it did not stop.
        model_calls: Model calls recorded for the turn.

    Returns:
        True when the count went down.
    """
    if refund is None or reason is None or resumable(reason) or model_calls > 0:
        return False
    try:
        return await refund(turn_id)
    except DATABASE_ERRORS as error:
        logger.warning("Quota refund failed: %s", type(error).__name__)
        return False
