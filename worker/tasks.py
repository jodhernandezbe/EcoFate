"""The worker's one task: ``ecofate.run_turn(turn_id, owner_id)``, ids only.

The task validates its two ids (untrusted), then runs the turn on this child's loop through
``app.turns.job.run_background_turn``, which reads the turn's input from the database, decrypts
the owner's key itself and releases it when the turn ends. A failure of the turn is recorded by
the job; the task itself only fails when its message is malformed.
"""

from __future__ import annotations

import logging
from typing import cast

from celery import Task

from app.task_queue import TASK_NAME, TurnJob
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
