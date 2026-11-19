"""What a job runner is given: the job store, the tool runners, the operator's keys, timing, and
the callback that follows a job's end.

``on_job_ended`` is the one seam where the follow-up turn of a finished job plugs in (task 2.5): it
receives the ended job (a copy, with its result or reason) once the final status is stored; the
default does nothing. A failure of the callback is logged and never changes the job.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

from app.operator_keys import OperatorKeys
from config.worker import WorkerSettings
from storage.job_model import Job, JobStore
from tools.schemas import JobRunner

JobEnded = Callable[[Job], Awaitable[None]]


async def no_follow_up(job: Job) -> None:
    """The default ``on_job_ended``: nothing follows a job's end."""


@dataclass(frozen=True)
class JobSettings:
    """Timing of a background job (seconds), from the ``tools`` pool.

    Attributes:
        heartbeat_seconds: How often the job's heartbeat is renewed and its cancel flag read.
        soft_limit_seconds: After this the job stops at its next check (``time_limit``).
        hard_limit_seconds: The task queue kills the process after this; halfway between the
            soft and the hard limit a tool that has not returned is abandoned.
    """

    heartbeat_seconds: float
    soft_limit_seconds: float
    hard_limit_seconds: float

    @classmethod
    def from_config(cls, worker: WorkerSettings) -> JobSettings:
        """The timing ``[worker]`` and ``[worker.tools]`` configure."""
        return cls(
            heartbeat_seconds=worker.heartbeat_seconds,
            soft_limit_seconds=worker.tools.soft_time_limit_seconds,
            hard_limit_seconds=worker.tools.time_limit_seconds,
        )


@dataclass(frozen=True)
class JobServices:
    """The collaborators of ``run_background_job`` (injected; built at the outer edge).

    Attributes:
        store: The jobs table.
        runners: Each heavy tool's runner by tool name (``agent.jobs.job_runners``).
        operator: The operator's service keys; a job never needs the user's model key.
        settings: Heartbeat and limits.
        on_job_ended: The seam for what follows a job's end (default: nothing).
    """

    store: JobStore
    runners: Mapping[str, JobRunner]
    operator: OperatorKeys
    settings: JobSettings
    on_job_ended: JobEnded = no_follow_up
