"""The thread store contract: what the web program needs from wherever threads are kept.

Production uses ``storage.threads.PostgresThreadStore``; unit tests use the in-memory store in
``tests/fakes.py``. Both honour this protocol (one contract test suite runs against both).
A thread is claimed for one turn at a time, across every process that serves the program.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import timedelta
from typing import Protocol

from langchain_core.messages import BaseMessage
from langgraph.checkpoint.base import BaseCheckpointSaver

from api.schemas.workspace import WorkspaceState
from app.usage_meter import CallUsage
from tools.schemas import ConfirmationRequest


class ThreadStore(Protocol):
    """Every thread's history, dashboard state and usage, and who is mid-turn."""

    @property
    def checkpointer(self) -> BaseCheckpointSaver[str]:
        """Keeps each thread's messages; given to the agent."""
        ...

    async def claim(self, thread_id: str) -> bool:
        """Mark the thread as running a turn; False if a turn is already running."""
        ...

    async def release(self, thread_id: str) -> None:
        """Mark the thread idle (safe to call more than once)."""
        ...

    async def touch(self, thread_id: str) -> None:
        """Mark the thread as most recently used, creating it when it is new."""
        ...

    async def holds(self, thread_id: str) -> bool:
        """Whether the thread exists (it was claimed or touched and not deleted)."""
        ...

    async def running(self, thread_id: str) -> bool:
        """Whether the thread is running a turn now."""
        ...

    async def messages(self, thread_id: str) -> list[BaseMessage]:
        """The thread's conversation as of its last finished step (a copy)."""
        ...

    async def add_usage(self, thread_id: str, calls: Sequence[CallUsage]) -> None:
        """Add a finished turn's model calls to the thread's session usage."""
        ...

    async def session_calls(self, thread_id: str) -> list[CallUsage]:
        """Every model call of the thread so far (a copy)."""
        ...

    async def add_tool_messages(self, thread_id: str, messages: Sequence[BaseMessage]) -> None:
        """Keep a thread's tool calls and results, from which its workspace is rebuilt."""
        ...

    async def tool_messages(self, thread_id: str) -> list[BaseMessage]:
        """The thread's tool calls and results so far (a copy)."""
        ...

    async def workspace(self, thread_id: str) -> WorkspaceState | None:
        """The workspace last stored for the thread; None before any tool result."""
        ...

    async def set_workspace(self, thread_id: str, state: WorkspaceState) -> None:
        """Remember the workspace just sent for the thread."""
        ...

    async def pending(self, thread_id: str) -> ConfirmationRequest | None:
        """The thread's open confirmation request, or None when nothing is open."""
        ...

    async def set_pending(self, thread_id: str, request: ConfirmationRequest | None) -> None:
        """Open a confirmation request for the thread, or close it (None)."""
        ...

    async def answers(self, thread_id: str) -> tuple[dict[str, float], frozenset[str]]:
        """The values the user supplied in this thread and the entries declined (copies)."""
        ...

    async def record_answers(
        self,
        thread_id: str,
        supplied: Mapping[str, float],
        declined: Iterable[str],
    ) -> None:
        """Keep the user's answers; a supplied value is never replaced and beats a decline."""
        ...

    async def reset(self, thread_id: str) -> bool:
        """Delete the thread's state; False (nothing changed) while a turn runs."""
        ...

    async def purge_idle(self, older_than: timedelta) -> list[str]:
        """Delete idle threads unused for ``older_than`` (never a running one); their ids."""
        ...
