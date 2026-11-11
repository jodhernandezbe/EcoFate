"""An in-memory quota store with the contract of ``storage.quota.QuotaRepository``."""

from __future__ import annotations

from uuid import UUID


class InMemoryQuota:
    """Counts turns per user for one day; a refund works once per turn id.

    Attributes:
        calls: The ``(user_id, limit)`` of every ``consume`` call, in order.
        refunded: The ids of the turns given back.
    """

    def __init__(self) -> None:
        self._turns: dict[UUID, int] = {}
        self.calls: list[tuple[UUID, int]] = []
        self.refunded: list[str] = []

    async def consume(self, user_id: UUID, limit: int) -> int | None:
        """Count one turn while below ``limit``; None (nothing counted) at the limit."""
        self.calls.append((user_id, limit))
        count = self._turns.get(user_id, 0)
        if count >= limit:
            return None
        self._turns[user_id] = count + 1
        return count + 1

    async def refund(self, user_id: UUID, turn_id: str) -> bool:
        """Give back one turn, once per ``turn_id``; never below zero."""
        if turn_id in self.refunded:
            return False
        self.refunded.append(turn_id)
        self._turns[user_id] = max(self._turns.get(user_id, 0) - 1, 0)
        return True

    async def usage(self, user_id: UUID) -> int:
        """The turns counted for ``user_id``."""
        return self._turns.get(user_id, 0)
