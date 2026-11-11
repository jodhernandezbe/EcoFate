"""The thread store contract: what the web program needs from wherever threads are kept.

Production uses ``storage.threads.PostgresThreadStore``; unit tests use the in-memory store in
``tests/fakes.py``. Both honour this protocol (one contract test suite runs against both).
A thread is claimed for one turn at a time, across every process that serves the program.

A thread belongs to one user. Every method names it with a ``ThreadKey`` (the owner from the
session and the thread id from the request), so a lookup can only reach the caller's own
threads: another user's id is simply not found. The two operations across users are
``purge_idle`` (retention) and the start-up recovery ``TurnStore.interrupt_all_open``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import timedelta
from typing import Protocol
from uuid import UUID

from langchain_core.messages import BaseMessage
from langgraph.checkpoint.base import BaseCheckpointSaver

from api.schemas.workspace import WorkspaceState
from app.usage_meter import CallUsage
from storage.keys import ThreadKey
from storage.turn_model import PlannedInput, Turn, TurnStatus
from tools.schemas import ConfirmationRequest


class TurnStore(Protocol):
    """Every turn's durable status; at most one open (queued or running) turn per thread.

    Honoured by ``storage.turns.TurnRepository`` and the in-memory fake in ``tests/fakes.py``.
    """

    async def begin(self, key: ThreadKey, planned: PlannedInput | None = None) -> Turn | None:
        """Record a new queued turn of the thread with its input; None while the thread has an
        open turn."""
        ...

    async def resume(self, owner_id: UUID, turn_id: str, max_resumes: int) -> Turn | None:
        """Queue the owner's interrupted turn again, counting the resume; None (nothing changed)
        when the owner has no such turn, it is not interrupted, reached ``max_resumes`` or its
        thread is busy."""
        ...

    async def get(self, owner_id: UUID, turn_id: str) -> Turn | None:
        """The owner's turn; None when the owner has no such turn."""
        ...

    async def start(self, owner_id: UUID, turn_id: str) -> Turn | None:
        """Move the owner's queued turn to running; None when it is not queued."""
        ...

    async def heartbeat(self, owner_id: UUID, turn_id: str) -> bool:
        """Record that the owner's running turn is alive; whether it is still running."""
        ...

    async def request_cancel(self, owner_id: UUID, turn_id: str) -> bool:
        """Ask the owner's open turn to stop; whether it was open."""
        ...

    async def cancel_requested(self, owner_id: UUID, turn_id: str) -> bool:
        """Whether the user asked the owner's turn to stop."""
        ...

    async def interrupt_stale(
        self,
        older_than: timedelta,
        reason: str,
        key: ThreadKey | None = None,
    ) -> list[ThreadKey]:
        """Interrupt running turns whose heartbeat is older than ``older_than`` (of one thread
        when ``key`` is given); the threads they belong to."""
        ...

    async def queue_position(self, turn_id: str) -> int:
        """How many queued turns were recorded before this one."""
        ...

    async def move(
        self,
        owner_id: UUID,
        turn_id: str,
        target: TurnStatus,
        reason: str | None = None,
    ) -> Turn:
        """Move the owner's turn to ``target``; raises ``TurnTransitionError`` (nothing changed)
        when the move is not allowed, ``ValueError`` when the reason does not fit the status."""
        ...

    async def abandon(self, owner_id: UUID, turn_id: str, reason: str) -> bool:
        """Interrupt the owner's turn if it is still open; whether it was (safe to repeat)."""
        ...

    async def interrupt_open(self, key: ThreadKey, reason: str) -> None:
        """Interrupt the thread's open turn, if it has one."""
        ...

    async def interrupt_all_open(self, reason: str) -> list[ThreadKey]:
        """Interrupt every open turn of every user (the server's start-up recovery only); the
        threads they belong to."""
        ...

    async def latest(self, key: ThreadKey) -> Turn | None:
        """The thread's most recent turn; None when it has none."""
        ...


class ThreadStore(Protocol):
    """Every thread's history, dashboard state and usage, and who is mid-turn."""

    @property
    def checkpointer(self) -> BaseCheckpointSaver[str]:
        """Keeps each thread's messages; given to the agent."""
        ...

    @property
    def turns(self) -> TurnStore:
        """Every turn's status (the thread's lease is taken with ``claim`` first)."""
        ...

    async def claim(self, key: ThreadKey) -> bool:
        """Mark the thread as running a turn; False if a turn is already running."""
        ...

    async def extend(self, key: ThreadKey) -> None:
        """Renew a held lease for another lease period (the worker's heartbeat)."""
        ...

    async def release(self, key: ThreadKey) -> None:
        """Mark the thread idle (safe to call more than once)."""
        ...

    async def touch(self, key: ThreadKey) -> None:
        """Mark the thread as most recently used, creating it when it is new."""
        ...

    async def holds(self, key: ThreadKey) -> bool:
        """Whether the thread exists (it was claimed or touched and not deleted)."""
        ...

    async def latest_thread(self, owner_id: UUID) -> str | None:
        """The id of the owner's most recently used thread; None when they have none."""
        ...

    async def running(self, key: ThreadKey) -> bool:
        """Whether the thread is running a turn now."""
        ...

    async def messages(self, key: ThreadKey) -> list[BaseMessage]:
        """The thread's conversation as of its last finished step (a copy)."""
        ...

    async def add_usage(
        self,
        key: ThreadKey,
        calls: Sequence[CallUsage],
        turn_id: str | None = None,
    ) -> None:
        """Add a finished turn's (or resumed segment's) model calls to the thread's usage."""
        ...

    async def session_calls(self, key: ThreadKey) -> list[CallUsage]:
        """Every model call of the thread so far (a copy)."""
        ...

    async def turn_calls(self, key: ThreadKey, turn_id: str) -> list[CallUsage]:
        """Every model call of one turn, its resumed segments included (a copy)."""
        ...

    async def add_tool_messages(self, key: ThreadKey, messages: Sequence[BaseMessage]) -> None:
        """Keep a thread's tool calls and results, from which its workspace is rebuilt."""
        ...

    async def tool_messages(self, key: ThreadKey) -> list[BaseMessage]:
        """The thread's tool calls and results so far (a copy)."""
        ...

    async def workspace(self, key: ThreadKey) -> WorkspaceState | None:
        """The workspace last stored for the thread; None before any tool result."""
        ...

    async def set_workspace(self, key: ThreadKey, state: WorkspaceState) -> None:
        """Remember the workspace just sent for the thread."""
        ...

    async def pending(self, key: ThreadKey) -> ConfirmationRequest | None:
        """The thread's open confirmation request, or None when nothing is open."""
        ...

    async def set_pending(self, key: ThreadKey, request: ConfirmationRequest | None) -> None:
        """Open a confirmation request for the thread, or close it (None)."""
        ...

    async def answers(self, key: ThreadKey) -> tuple[dict[str, float], frozenset[str]]:
        """The values the user supplied in this thread and the entries declined (copies)."""
        ...

    async def record_answers(
        self,
        key: ThreadKey,
        supplied: Mapping[str, float],
        declined: Iterable[str],
    ) -> None:
        """Keep the user's answers; a supplied value is never replaced and beats a decline."""
        ...

    async def reset(self, key: ThreadKey) -> bool:
        """Delete the thread's state; False (nothing changed) while a turn runs."""
        ...

    async def purge_idle(self, older_than: timedelta) -> list[ThreadKey]:
        """Delete idle threads of every user unused for ``older_than`` (never a running one)."""
        ...

    async def forget_owner(self, owner_id: UUID) -> int:
        """Delete every thread of one user, running or not, with its checkpoints (account
        deletion); how many there were."""
        ...
