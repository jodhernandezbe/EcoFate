"""Jobs whose worker is gone become ``interrupted``, never stuck ``running`` and never re-run.

``sweep_stale_jobs`` (the worker's start-up) interrupts every running job whose heartbeat is
older than the stale age, and every queued job older than the visibility timeout (a task message
that was lost would otherwise hold its owner's cap forever); ``interrupt_lost_job`` interrupts
the job of a task whose child was lost or killed at the hard limit. Both call ``on_job_ended``
for each job they interrupt (the seam of the follow-up; default nothing). They take the store,
so they run against any implementation.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from app.jobs.failures import JobFailure
from app.jobs.services import JobEnded, no_follow_up
from app.task_queue import ToolJob
from storage.job_model import Job, JobStore

logger = logging.getLogger("app.jobs")


async def _notify(on_ended: JobEnded, job: Job) -> None:
    try:
        await on_ended(job)
    except Exception as error:
        logger.warning("Follow-up of job %s failed: %s", job.id, type(error).__name__)


async def sweep_stale_jobs(
    store: JobStore,
    stale_after: timedelta,
    on_ended: JobEnded = no_follow_up,
    unclaimed_after: timedelta | None = None,
) -> int:
    """Interrupt every running job whose heartbeat is stale (``worker_lost``) and, when
    ``unclaimed_after`` is given, every queued job older than that (its task message was lost:
    ``not_started``, so it stops holding its owner's cap); how many."""
    jobs = await store.interrupt_stale(stale_after, JobFailure.WORKER_LOST)
    if unclaimed_after is not None:
        jobs += await store.interrupt_unclaimed(unclaimed_after, JobFailure.NOT_STARTED)
    for job in jobs:
        await _notify(on_ended, job)
    if jobs:
        logger.info("Interrupted %d job(s) whose worker was lost", len(jobs))
    return len(jobs)


async def interrupt_lost_job(
    store: JobStore,
    task: ToolJob,
    reason: JobFailure,
    on_ended: JobEnded = no_follow_up,
) -> bool:
    """Interrupt the task's job if it is still open; whether it was."""
    job = await store.interrupt(task.owner_id, task.job_id, reason)
    if job is None:
        return False
    await _notify(on_ended, job)
    return True
