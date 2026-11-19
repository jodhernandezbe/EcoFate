"""The worker's tasks: ``ecofate.run_turn(turn_id, owner_id)`` and ``ecofate.run_job(job_id,
owner_id)``, ids only.

Each task validates its two ids (untrusted), then runs the turn on this child's loop through
``app.turns.job.run_background_turn``, which reads the turn's input from the database, decrypts
the owner's key itself and releases it when the turn ends. A failure of the turn is recorded by
the job; the task itself only fails when its message is malformed. ``run_job`` runs a background
tool job (``app.jobs.runner``) with the operator's keys only: it never reads the user's key.
"""

from __future__ import annotations

import logging
from typing import cast

from celery import Task

from app.task_queue import JOB_TASK_NAME, TASK_NAME, ToolJob, TurnJob
from worker.celery_app import celery, child_runtime

logger = logging.getLogger("worker")


def run_turn(turn_id: object, owner_id: object) -> None:
    """Run the queued turn ``turn_id`` of ``owner_id``.

    Raises:
        ValueError: The ids do not have the expected shape (the message is dropped).
    """
    job = TurnJob.from_payload(turn_id, owner_id)
    logger.info("Running turn %s", job.turn_id)
    child_runtime().run(job)


run_turn_task = cast(Task, celery.task(name=TASK_NAME)(run_turn))  # pyright: ignore[reportUnknownMemberType, reportMissingTypeArgument]


def run_job(job_id: object, owner_id: object) -> None:
    """Run the queued background tool job ``job_id`` of ``owner_id``.

    Raises:
        ValueError: The ids do not have the expected shape (the message is dropped).
    """
    job = ToolJob.from_payload(job_id, owner_id)
    logger.info("Running job %s", job.job_id)
    child_runtime().run_job(job)


run_job_task = cast(Task, celery.task(name=JOB_TASK_NAME)(run_job))  # pyright: ignore[reportUnknownMemberType, reportMissingTypeArgument]
