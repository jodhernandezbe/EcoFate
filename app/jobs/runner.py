"""Run one queued background tool job: the body of the worker's ``ecofate.run_job`` (and of
in-process runs).

``run_background_job`` claims the job (``queued -> running``; a job that is no longer queued is
left alone, so a second delivery does nothing), runs the job's tool on a thread with the
operator's keys, and always stores a final status. While it runs, a supervisor renews the
heartbeat, reads the cancel flag, and enforces the soft time limit: the tool is asked to stop
(``should_stop``) and does so between its tiers; a tool that has not returned halfway to the hard
limit is abandoned. A failure is stored as a fixed reason (``JobFailure``), never exception text.
Once the final status is stored, ``services.on_job_ended`` is called (the seam of the follow-up).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass

from app.jobs.failures import JobFailure
from app.jobs.keys import provided_operator
from app.jobs.result import storable
from app.jobs.services import JobEnded, JobServices, JobSettings
from app.task_queue import ToolJob
from app.turns.failures import new_correlation_id
from commons.stop import StoppedError
from storage.errors import DATABASE_ERRORS
from storage.job_model import Job, JobOutcome, JobStatus, JsonObject
from tools.schemas import InvalidJobInputError, JobResult, JobRunner

logger = logging.getLogger("app.jobs")


@dataclass
class JobRun:
    """The state of one running job: what the supervisor asked for and what the tool produced."""

    job: Job
    services: JobServices
    stop_reason: JobFailure | None = None
    forced: bool = False
    failure: JobFailure | None = None
    result: tuple[JsonObject, JsonObject] | None = None

    def should_stop(self) -> bool:
        """What the tool asks between its tiers (read from the tool's thread)."""
        return self.stop_reason is not None


async def run_background_job(task: ToolJob, services: JobServices) -> None:
    """Run the queued job ``task`` names to its end; never raises for a failure of the job."""
    job = await services.store.claim(task.owner_id, task.job_id)
    if job is None:
        logger.info("Job %s is not queued; nothing to run", task.job_id)
        return
    run = JobRun(job, services)
    await _notify(services.on_job_started, job)
    try:
        await _run_supervised(run)
    except Exception:
        run.failure = JobFailure.UNEXPECTED
        logger.exception("Background job %s failed (%s)", job.id, new_correlation_id())
    finally:
        await _finish(run)


async def _run_supervised(run: JobRun) -> None:
    """Run the tool while the supervisor watches it; a cancelled or abandoned job still ends."""
    if run.job.cancel_requested:  # cancelled while it waited: it does not start
        run.stop_reason = JobFailure.CANCELLED
        return
    pump = asyncio.create_task(_pump(run))
    supervisor = asyncio.create_task(_supervise(run, pump))
    try:
        await pump
    except asyncio.CancelledError:
        if not run.forced:
            raise
        run.stop_reason = JobFailure.TIME_LIMIT
    finally:
        supervisor.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await supervisor


async def _pump(run: JobRun) -> None:
    """Run the job's tool on a thread under the operator's keys and keep its stored result."""
    runner = run.services.runners.get(run.job.tool)
    if runner is None:
        run.failure = JobFailure.UNKNOWN_TOOL
        return
    try:
        with provided_operator(run.services.operator):
            run.result = storable(await asyncio.to_thread(_call, runner, run))
    except StoppedError:
        run.failure = None if run.stop_reason is not None else JobFailure.UNEXPECTED
    except InvalidJobInputError:
        run.failure = JobFailure.BAD_INPUT
    except TypeError:  # a result that is not data
        logger.exception("Job %s returned a result that is not data", run.job.id)
        run.failure = JobFailure.INVALID_RESULT


def _call(runner: JobRunner, run: JobRun) -> JobResult:
    return runner(run.job.input, run.should_stop)


# --- supervision --------------------------------------------------------------------------------


async def _supervise(run: JobRun, pump: asyncio.Task[None]) -> None:
    """Renew the heartbeat, read the cancel flag, ask the tool to stop at the soft limit and
    abandon a tool that has not returned halfway to the hard limit."""
    timing, loop = run.services.settings, asyncio.get_running_loop()
    started = loop.time()
    while not pump.done():
        await asyncio.sleep(_tick(timing, loop.time() - started))
        await _beat(run)
        elapsed = loop.time() - started
        if elapsed >= timing.soft_limit_seconds and run.stop_reason is None:
            run.stop_reason = JobFailure.TIME_LIMIT
        if elapsed >= _abandon_after(timing):
            run.forced = True
            pump.cancel()
            return


def _abandon_after(timing: JobSettings) -> float:
    return (timing.soft_limit_seconds + timing.hard_limit_seconds) / 2


def _tick(timing: JobSettings, elapsed: float) -> float:
    """Seconds until the next heartbeat or limit, whichever comes first."""
    deadlines = (timing.soft_limit_seconds, _abandon_after(timing))
    ahead = [deadline - elapsed for deadline in deadlines if deadline > elapsed]
    return max(min([timing.heartbeat_seconds, *ahead]), 0.0)


async def _beat(run: JobRun) -> None:
    """Record the heartbeat and read the cancel flag; a database hiccup is only logged. A job
    that is no longer running (a sweep interrupted it) is asked to stop."""
    job, store = run.job, run.services.store
    try:
        if not await store.heartbeat(job.owner_id, job.id):
            run.stop_reason = run.stop_reason or JobFailure.WORKER_LOST
        elif run.stop_reason is None and await store.cancel_requested(job.owner_id, job.id):
            run.stop_reason = JobFailure.CANCELLED
    except DATABASE_ERRORS as error:
        logger.warning("Heartbeat of job %s failed: %s", job.id, type(error).__name__)


# --- the end ------------------------------------------------------------------------------------


def outcome_of(run: JobRun) -> JobOutcome:
    """How the job ends: a result wins (the tool finished); else the stop, else the failure."""
    if run.result is not None:
        return JobOutcome(JobStatus.SUCCEEDED, run.result[0], run.result[1])
    reason = run.stop_reason or run.failure or JobFailure.UNEXPECTED
    status = JobStatus.CANCELLED if reason is JobFailure.CANCELLED else JobStatus.FAILED
    return JobOutcome(status, reason=reason.value)


async def _finish(run: JobRun) -> None:
    """Store the final status, then call the follow-up seam (each step only logged when it
    cannot be done: a recovery sweep may have interrupted the job already)."""
    job, services = run.job, run.services
    try:
        ended = await services.store.finish(job.owner_id, job.id, outcome_of(run))
    except DATABASE_ERRORS as error:
        logger.warning("Job %s could not be finished: %s", job.id, type(error).__name__)
        return
    if ended is None:
        logger.warning("Job %s was no longer running at its end", job.id)
        return
    await _notify(services.on_job_ended, ended)


async def _notify(callback: JobEnded, job: Job) -> None:
    """Call a seam; its failure is logged (class only) and never changes the job."""
    try:
        await callback(job)
    except Exception as error:
        logger.warning("Callback of job %s failed: %s", job.id, type(error).__name__)
