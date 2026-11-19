"""A thread's background jobs for the interface: list, cancel, and what ``Clear workspace`` stops.

Reads and writes go through the owner-scoped job store: a job of another user is simply not
found. Nothing here reads a job's input or result; a cancel of a job nobody has claimed ends it at
once, and a running job is asked to stop and does so after its current step.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from api.schemas.chat import JobInfo
from app.jobs.failures import JobFailure
from app.turns.thread_bus import ThreadEventBus, job_record, publish_quietly
from storage.job_model import OPEN_STATUSES, Job, JobStatus, JobStore
from storage.keys import ThreadKey


class Cancellation(StrEnum):
    """What a cancel request did."""

    ENDED = "ended"  # the job had not started: it is cancelled now
    REQUESTED = "requested"  # the job is running: it stops after its current step
    UNKNOWN = "unknown"  # no such job for this user (or another user's)
    FINISHED = "finished"  # the job had already ended


async def job_infos(store: JobStore, key: ThreadKey) -> list[JobInfo]:
    """The thread's jobs as the interface shows them, oldest first (queue position while queued)."""
    jobs = await store.for_thread(key)
    return [await _info(store, job) for job in jobs]


async def _info(store: JobStore, job: Job) -> JobInfo:
    queued = job.status is JobStatus.QUEUED
    return JobInfo(
        job_id=job.id,
        tool=job.tool,
        status=job.status.value,
        queued_at=job.queued_at,
        started_at=job.started_at,
        ended_at=job.ended_at,
        position=await store.queue_position(job.owner_id, job.id) if queued else None,
    )


async def cancel_job(
    store: JobStore,
    bus: ThreadEventBus | None,
    ttl_seconds: int,
    owner_id: UUID,
    job_id: str,
) -> Cancellation:
    """Cancel the owner's job; the owner is the signed-in user, never read from the request."""
    job = await store.get(owner_id, job_id)
    if job is None:
        return Cancellation.UNKNOWN
    if job.status not in OPEN_STATUSES:
        return Cancellation.FINISHED
    ended = await store.cancel_queued(owner_id, job_id, JobFailure.CANCELLED)
    if ended is not None:
        await publish_quietly(bus, ended.key, job_record("job.ended", ended), ttl_seconds)
        return Cancellation.ENDED
    if await store.request_cancel(owner_id, job_id):
        return Cancellation.REQUESTED
    return Cancellation.FINISHED


async def cancel_open_jobs(
    store: JobStore,
    bus: ThreadEventBus | None,
    ttl_seconds: int,
    key: ThreadKey,
) -> int:
    """Cancel every open job of the thread (``Clear workspace``); how many were open."""
    open_jobs = [j for j in await store.for_thread(key) if j.status in OPEN_STATUSES]
    for job in open_jobs:
        await cancel_job(store, bus, ttl_seconds, key.owner_id, job.id)
    return len(open_jobs)
