"""The job system of a background scenario, in memory: what a tool call queues, and its end.

``MemoryJobPort`` is the ``JobPort`` the tools see in an evaluation: it records each submitted
job and answers queued, always under the cap. ``ended_job`` then "runs" a recorded job without
a worker: its result is the output the cassette recorded for the stored arguments (never
written here), or a fixed failure when there is none, so the run fails closed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

from evals.cassette import Cassette
from storage.job_model import Job, JobStatus
from tools.schemas import JobStatusEntry, SubmittedJob

NOT_RECORDED = "eval_job_not_recorded"  # the failure reason of a job with no recorded output


@dataclass(frozen=True)
class SubmittedRecord:
    """One job a tool call queued: who and what, as the port was given it."""

    job_id: str
    owner_id: UUID
    thread_id: str
    tool: str
    job_input: Mapping[str, object]
    queued_at: datetime


class MemoryJobPort:
    """A ``JobPort`` that keeps the submitted jobs in a list (none ever runs by itself)."""

    def __init__(self) -> None:
        self.jobs: list[SubmittedRecord] = []

    async def submit(
        self,
        owner_id: UUID,
        thread_id: str,
        tool: str,
        job_input: Mapping[str, object],
    ) -> SubmittedJob | None:
        """Record the job and answer it queued at once."""
        job_id = uuid4().hex
        self.jobs.append(
            SubmittedRecord(job_id, owner_id, thread_id, tool, dict(job_input), datetime.now(UTC)),
        )
        return {"job_id": job_id, "status": "queued", "position": 0}

    async def status(
        self,
        owner_id: UUID,
        thread_id: str,
        job_id: str | None,
    ) -> list[JobStatusEntry]:
        """The owner's jobs of the thread (one when ``job_id`` is given), with no outcome."""
        mine = [j for j in self.jobs if (j.owner_id, j.thread_id) == (owner_id, thread_id)]
        chosen = [j for j in mine if job_id is None or j.job_id == job_id]
        now = datetime.now(UTC)
        return [_entry(job, n, now) for n, job in enumerate(chosen)]


def _entry(job: SubmittedRecord, index: int, now: datetime) -> JobStatusEntry:
    """The first job runs, the others wait (a worker would take them in order)."""
    elapsed = (now - job.queued_at).total_seconds()
    entry: JobStatusEntry = {
        "job_id": job.job_id,
        "tool": job.tool,
        "status": "running" if index == 0 else "queued",
        "elapsed_seconds": elapsed,
    }
    if index:
        entry["position"] = index
    return entry


def _arguments(job_input: Mapping[str, object]) -> Mapping[str, object]:
    stored = job_input.get("arguments")
    return cast(Mapping[str, object], stored) if isinstance(stored, dict) else {}


def ended_job(submitted: SubmittedRecord, cassette: Cassette) -> Job:
    """The job as a worker would leave it: succeeded with the recorded output of its tool for
    the stored arguments, or failed with ``NOT_RECORDED`` when the cassette has none."""
    found, output = cassette.lookup(submitted.tool, _arguments(submitted.job_input))
    ok = found and isinstance(output, dict)
    return Job(
        submitted.job_id,
        submitted.owner_id,
        submitted.thread_id,
        submitted.tool,
        submitted.job_input,
        JobStatus.SUCCEEDED if ok else JobStatus.FAILED,
        submitted.queued_at,
        result_content=cast(Mapping[str, object], output) if ok else None,
        result_artifact={} if ok else None,
        failure_reason=None if ok else NOT_RECORDED,
    )
