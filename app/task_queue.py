"""The task queue between the web program and its background workers (Celery over Redis).

One task, ``ecofate.run_turn``, runs one queued turn segment. Its message carries the turn id
and its owner's id and nothing else (checked by ``commons.payload_guard`` before it is sent):
the turn's input is in the database, the keys are decrypted by the worker. The web program
enqueues by task name and never imports the worker; ``build_celery`` configures both sides
alike from ``[worker]``. ``InProcessEnqueuer`` runs the same job in the calling process
(``[worker].eager``, tests).
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from celery import Celery
from kombu.exceptions import KombuError
from redis.exceptions import RedisError

from commons.payload_guard import assert_ids_only
from config.worker import WorkerSettings
from storage.turn_model import TURN_ID_PATTERN

TASK_NAME = "ecofate.run_turn"
_TURN_ID = re.compile(TURN_ID_PATTERN)


class EnqueueError(RuntimeError):
    """The turn could not be handed to the queue (the broker is unreachable or slow); the
    message is the exception class only."""


class BrokerSetupError(RuntimeError):
    """The Redis URL is not set; the message names the variable (never a value)."""


def redis_url(environ: Mapping[str, str], settings: WorkerSettings) -> str:
    """The Redis URL from the variable ``[worker]`` names (it may carry a password).

    Raises:
        BrokerSetupError: The variable is missing or blank.
    """
    value = environ.get(settings.redis_url_env_var, "").strip()
    if not value:
        raise BrokerSetupError(
            f"Set {settings.redis_url_env_var} to the Redis URL (see .env.example) before "
            "starting the web program or the worker.",
        )
    return value


@dataclass(frozen=True)
class TurnJob:
    """What a task message names: one turn and its owner (ids only)."""

    turn_id: str
    owner_id: UUID

    def payload(self) -> list[str]:
        """The task's arguments: the turn id and the owner id, as strings."""
        return [self.turn_id, str(self.owner_id)]

    @classmethod
    def from_payload(cls, turn_id: object, owner_id: object) -> TurnJob:
        """The job of a received task message (untrusted).

        Raises:
            ValueError: The ids do not have the shape of a turn id and a user id.
        """
        if not isinstance(turn_id, str) or _TURN_ID.fullmatch(turn_id) is None:
            raise ValueError("turn id has the wrong shape")
        if not isinstance(owner_id, str):
            raise ValueError("owner id has the wrong shape")
        return cls(turn_id, UUID(owner_id))


class TurnEnqueuer(Protocol):
    """Hands a queued turn to a worker."""

    async def enqueue(self, job: TurnJob) -> None:
        """Enqueue ``job``; raises ``EnqueueError`` when it could not be enqueued."""
        ...


def build_celery(settings: WorkerSettings, broker_url: str) -> Celery:
    """The Celery app of both sides: acknowledged late, one task prefetched, never re-run when
    a worker is lost, the hard time limit (the soft one is enforced by the job itself), and a
    visibility timeout above it. ``broker_url`` carries a password: never log it."""
    app = Celery("ecofate", broker=broker_url)  # no result backend: a task returns nothing
    app.conf.update(
        task_acks_late=True,
        worker_prefetch_multiplier=settings.prefetch_multiplier,
        task_reject_on_worker_lost=False,
        task_time_limit=settings.time_limit_seconds,
        task_default_queue=settings.queue,
        task_ignore_result=True,
        task_serializer="json",
        accept_content=["json"],
        task_always_eager=settings.eager,
        worker_concurrency=settings.concurrency,
        worker_hijack_root_logger=False,
        broker_connection_timeout=settings.broker_timeout_seconds,
        broker_connection_retry_on_startup=True,
        broker_transport_options=_transport_options(settings),
    )
    return app


def _transport_options(settings: WorkerSettings) -> dict[str, object]:
    timeout = settings.broker_timeout_seconds
    return {
        "visibility_timeout": settings.visibility_timeout_seconds,
        "socket_connect_timeout": timeout,
        "socket_timeout": timeout,
        "max_retries": 0,
    }


class CeleryEnqueuer:
    """Sends ``ecofate.run_turn`` by name through the broker, bounded in time.

    Args:
        celery: The configured app (``build_celery``).
        settings: Queue name and broker timeout.
        protected: Secret values that must never appear in a message (the operator's keys).
    """

    def __init__(
        self,
        celery: Celery,
        settings: WorkerSettings,
        protected: Iterable[str] = (),
    ) -> None:
        self._celery = celery
        self._settings = settings
        self._protected = tuple(protected)

    def _send(self, payload: list[str]) -> None:
        self._celery.send_task(TASK_NAME, args=payload, queue=self._settings.queue, retry=False)  # pyright: ignore[reportUnknownMemberType]

    async def enqueue(self, job: TurnJob) -> None:
        """Send the task; raises ``EnqueueError`` when the broker refuses or does not answer."""
        payload = job.payload()
        assert_ids_only(payload, self._protected)
        try:
            await asyncio.wait_for(
                asyncio.to_thread(self._send, payload),
                self._settings.broker_timeout_seconds,
            )
        except (TimeoutError, OSError, KombuError, RedisError) as error:
            raise EnqueueError(type(error).__name__) from None


class InProcessEnqueuer:
    """Runs each job as a task of the calling event loop, through the same code as a worker.

    Args:
        run: The job (``app.turns.job.run_background_turn`` bound to its services).
        running: Where the started jobs are kept until they end (shared by every enqueuer of a
            process, so a job outlives the request that started it).
    """

    def __init__(
        self,
        run: Callable[[TurnJob], Awaitable[None]],
        running: set[asyncio.Task[None]] | None = None,
    ) -> None:
        self._run = run
        self._running = running if running is not None else set[asyncio.Task[None]]()

    async def enqueue(self, job: TurnJob) -> None:
        """Start the job in the background (the payload rule is checked as for a real queue)."""
        assert_ids_only(job.payload())
        task = asyncio.create_task(self._job(job))
        self._running.add(task)
        task.add_done_callback(self._running.discard)

    async def _job(self, job: TurnJob) -> None:
        await self._run(job)

    async def drain(self) -> None:
        """Wait for every job started so far (tests, shutdown)."""
        while self._running:
            await asyncio.gather(*self._running, return_exceptions=True)
