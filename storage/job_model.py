"""A background tool job as stored: its status, input, result and times, and the store contract.

A job is ``queued`` when recorded, ``running`` once a worker claims it, and ends ``succeeded``,
``failed`` or ``cancelled`` (the worker's own end), or ``interrupted`` (its worker was lost; the
sweep or the task failure handler moves it, nothing re-runs it). A status changes only along those
moves. The failure reason is an opaque fixed code here; the program decodes it. ``JobStore`` is
the contract of the PostgreSQL store (``storage.jobs``) and of the in-memory one used by tests.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from storage.keys import ThreadKey

# Every job id: 32 lowercase hex digits (a random UUID's hex); anything else names no job.
JOB_ID_PATTERN = r"^[0-9a-f]{32}$"
# A JSON object as stored (input, model view, workspace artifact); never trusted when read back.
JsonObject = Mapping[str, object]


class JobStatus(StrEnum):
    """Where a job is in its life."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


# The statuses of a job that counts against the owner's cap on open jobs.
OPEN_STATUSES = (JobStatus.QUEUED, JobStatus.RUNNING)
# The statuses that carry a failure reason (and only these).
REASONED_STATUSES = (JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.INTERRUPTED)
# The statuses a worker may end a running job with (interrupted is the sweep's alone).
FINISH_STATUSES = (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED)


@dataclass(frozen=True)
class JobOutcome:
    """How a running job ended: a result when it succeeded, a fixed reason otherwise.

    Attributes:
        status: ``succeeded``, ``failed`` or ``cancelled``.
        content: The model's view of the result (succeeded only).
        artifact: The workspace data of the result (succeeded only).
        reason: A fixed reason code, never exception text (failed or cancelled only).

    Raises:
        ValueError: The pieces do not fit the status (nothing is stored then).
    """

    status: JobStatus
    content: JsonObject | None = None
    artifact: JsonObject | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.status not in FINISH_STATUSES:
            raise ValueError(f"a worker cannot end a job as {self.status}")
        if (self.status is JobStatus.SUCCEEDED) != (self.content is not None):
            raise ValueError("only a succeeded job has a result (and it needs one)")
        if (self.status is JobStatus.SUCCEEDED) != (self.artifact is not None):
            raise ValueError("only a succeeded job has an artifact (and it needs one)")
        if (self.status is JobStatus.SUCCEEDED) == bool(self.reason):
            raise ValueError("a job that did not succeed needs a reason; a succeeded one has none")


@dataclass(frozen=True)
class Job:
    """One stored job (a copy; changing the job goes through its store).

    Attributes:
        id: The job's id.
        owner_id: The user whose job it is.
        thread_id: The conversation that started it (one of that user's).
        tool: The tool the job runs.
        input: The tool's arguments, recorded so a task message carries ids only.
        status: Where it is in its life.
        queued_at: When it was recorded.
        started_at: When a worker claimed it; None while queued.
        ended_at: When it ended; None before.
        heartbeat_at: When its worker last reported it alive; None before it ran.
        cancel_requested: The user asked to stop it; its worker stops at the next check.
        result_content: What the model reads; set when it succeeded.
        result_artifact: What the workspace reads; set when it succeeded.
        failure_reason: A fixed code for failed, cancelled and interrupted jobs.
    """

    id: str
    owner_id: UUID
    thread_id: str
    tool: str
    input: JsonObject
    status: JobStatus
    queued_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None
    heartbeat_at: datetime | None = None
    cancel_requested: bool = False
    result_content: JsonObject | None = None
    result_artifact: JsonObject | None = None
    failure_reason: str | None = None

    @property
    def key(self) -> ThreadKey:
        """The thread the job belongs to, with its owner."""
        return ThreadKey(self.owner_id, self.thread_id)


class JobStore(Protocol):
    """What the program needs of the jobs table. Every call names the owner: a job of another
    user is never found, and answers exactly as an unknown id does."""

    async def create(
        self,
        key: ThreadKey,
        tool: str,
        job_input: JsonObject,
        max_open: int,
    ) -> Job | None:
        """Record a queued job of the thread, atomically per owner: None (nothing recorded)
        when the owner already has ``max_open`` queued or running jobs."""
        ...

    async def get(self, owner_id: UUID, job_id: str) -> Job | None:
        """The owner's job; None when the owner has no such job (or it does not decode)."""
        ...

    async def claim(self, owner_id: UUID, job_id: str) -> Job | None:
        """Move the owner's queued job to running with a first heartbeat; None (nothing
        changed) when it is not queued, so a second delivery does nothing."""
        ...

    async def heartbeat(self, owner_id: UUID, job_id: str) -> bool:
        """Record that the owner's running job is alive; whether it is still running."""
        ...

    async def request_cancel(self, owner_id: UUID, job_id: str) -> bool:
        """Ask the owner's open job to stop; whether it was open (safe to repeat)."""
        ...

    async def cancel_requested(self, owner_id: UUID, job_id: str) -> bool:
        """Whether the user asked the owner's job to stop."""
        ...

    async def finish(self, owner_id: UUID, job_id: str, outcome: JobOutcome) -> Job | None:
        """End the owner's running job with ``outcome``; None (nothing changed) when it is not
        running (a sweep may have interrupted it)."""
        ...

    async def interrupt(self, owner_id: UUID, job_id: str, reason: str) -> Job | None:
        """Interrupt the owner's open job (its worker is gone); None when it is not open."""
        ...

    async def interrupt_stale(self, older_than: timedelta, reason: str) -> list[Job]:
        """Interrupt the running jobs of every user whose heartbeat is older than
        ``older_than`` (recovery only); the jobs interrupted."""
        ...

    async def for_thread(self, key: ThreadKey) -> list[Job]:
        """The owner's jobs of one thread, oldest first."""
        ...
