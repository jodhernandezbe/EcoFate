"""The worker's Celery app and its process signals (``celery -A worker.celery_app worker``).

Configured from ``[worker]`` like the web program's client (``app.task_queue.build_celery``);
the Redis URL comes from the variable ``[worker]`` names. Each prefork child opens its own
resources when it starts (``worker_process_init``) and closes them when it stops. The main
process sweeps stale turns when the worker is ready and interrupts the turn of a task whose
child was lost or killed. Logging goes through the redaction filter; process secrets are
protected for the life of the process.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Sequence
from typing import Protocol, cast

from celery import Celery
from celery.signals import (
    setup_logging,
    task_failure,
    worker_process_init,
    worker_process_shutdown,
    worker_ready,
)

from app.process_secrets import process_secret_values
from app.redaction import REDACTED_LOGGERS, install_redaction, protect_for_process
from app.task_queue import BrokerSetupError, TurnJob, build_celery, redis_url
from app.telemetry import configure_telemetry, instrument_task_queue
from config.telemetry import get_telemetry_settings
from config.worker import get_worker_settings
from storage.errors import DATABASE_ERRORS
from worker import recovery
from worker.resources import open_child

logger = logging.getLogger("worker")
WORKER_LOGGERS = (*REDACTED_LOGGERS, "celery", "celery.app.trace", "celery.worker", "worker")
_LOG_FORMAT = "%(asctime)s %(levelname)s %(processName)s %(name)s: %(message)s"


def _celery() -> Celery:
    settings = get_worker_settings()
    try:
        url = redis_url(os.environ, settings)
    except BrokerSetupError as error:
        raise SystemExit(str(error)) from None
    app = build_celery(settings, url)
    app.conf.include = ["worker.tasks"]
    return app


class ChildRunner(Protocol):
    """Runs turns in this process (``worker.resources.ChildRuntime``)."""

    def run(self, job: TurnJob) -> None: ...

    def close(self) -> None: ...


class _Child:
    """The runtime of this child process, once it is open (one per process, no user data)."""

    runtime: ChildRunner | None = None


def child_runtime() -> ChildRunner:
    """This child's runtime; raises when the child did not open one."""
    if _Child.runtime is None:
        raise RuntimeError("the worker child has no runtime (worker_process_init did not run)")
    return _Child.runtime


def install_child_runtime(runtime: ChildRunner | None) -> None:
    """Set (or clear) this process's runtime: the child at start-up, tests in-process."""
    _Child.runtime = runtime


@setup_logging.connect
def _logging(**_: object) -> None:
    """Our own logging (Celery then leaves the root logger alone), redacted from the start."""
    logging.basicConfig(level=logging.INFO, format=_LOG_FORMAT)
    install_redaction(WORKER_LOGGERS)
    protect_for_process(process_secret_values(os.environ))
    configure_telemetry(get_telemetry_settings(), process_secret_values(os.environ))
    instrument_task_queue(get_telemetry_settings())


@worker_process_init.connect
def _open_child(**_: object) -> None:
    install_child_runtime(open_child(os.environ))


@worker_process_shutdown.connect
def _close_child(**_: object) -> None:
    if _Child.runtime is not None:
        _Child.runtime.close()
        install_child_runtime(None)


@worker_ready.connect
def _sweep_stale(**_: object) -> None:
    try:
        asyncio.run(recovery.sweep_stale_env(os.environ))
    except DATABASE_ERRORS as error:
        logger.warning("Stale turn sweep failed: %s", type(error).__name__)


@task_failure.connect
def _task_failed(args: object = None, exception: BaseException | None = None, **_: object) -> None:
    """A task whose child was lost or hit the hard limit leaves its turn resumable."""
    reason = recovery.lost_reason(exception)
    job = recovery.job_of(cast(Sequence[object], args) if isinstance(args, list | tuple) else None)
    if reason is None or job is None:
        return
    try:
        asyncio.run(recovery.interrupt_lost_env(job, reason, os.environ))
    except DATABASE_ERRORS as error:
        logger.warning("Could not interrupt turn %s: %s", job.turn_id, type(error).__name__)


celery = _celery()
