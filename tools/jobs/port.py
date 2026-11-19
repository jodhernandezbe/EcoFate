"""What a tool may ask of the background job system, and who is asking.

``tools/`` never imports ``app`` or ``storage``: the program provides a ``JobPort`` for the
duration of a turn (``provided_port``, backed by a ``ContextVar`` like the keys of
``tools.credentials``), and the run's configuration names the user and thread the turn belongs
to. Both come from the authenticated session that started the turn, never from a tool's
arguments, so a model (or a prompt injection) cannot start or read another user's jobs.
"""

from __future__ import annotations

from collections.abc import Generator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Protocol, cast
from uuid import UUID

from langchain_core.runnables import RunnableConfig

from tools.schemas import JobStatusEntry, SubmittedJob

OWNER_KEY = "job_owner_id"
THREAD_KEY = "job_thread_id"
AUTOMATIC_KEY = "job_automatic"


class JobUnavailableError(Exception):
    """The job system cannot take the job now (the queue is unreachable); no job was started."""


class JobPort(Protocol):
    """The job system as a tool sees it; every call names the owner and thread."""

    async def submit(
        self,
        owner_id: UUID,
        thread_id: str,
        tool: str,
        job_input: Mapping[str, object],
    ) -> SubmittedJob | None:
        """Record and queue a job of the thread; None (nothing recorded) over the owner's cap.

        Raises:
            JobUnavailableError: The queue could not be reached (the job is not left queued).
        """
        ...

    async def status(
        self,
        owner_id: UUID,
        thread_id: str,
        job_id: str | None,
    ) -> list[JobStatusEntry]:
        """The owner's jobs of this thread (one when ``job_id`` is given); never another's."""
        ...


_PORT: ContextVar[JobPort | None] = ContextVar("job_port", default=None)


def current_port() -> JobPort | None:
    """The job system provided to this turn, or None (command line, evaluations)."""
    return _PORT.get()


@contextmanager
def provided_port(port: JobPort | None) -> Generator[None]:
    """Give ``port`` to the tools of the current context until the block exits.

    Cleared with ``set(None)``, not ``reset``: an async generator can be closed from another
    context (a client leaving), where a token is invalid.
    """
    _PORT.set(port)
    try:
        yield
    finally:
        _PORT.set(None)


def scope_config(owner_id: UUID, thread_id: str, automatic: bool = False) -> dict[str, object]:
    """The ``configurable`` entries that name the turn's user and thread for the job tools, and
    whether the system (not the user) started the turn."""
    return {OWNER_KEY: str(owner_id), THREAD_KEY: thread_id, AUTOMATIC_KEY: automatic}


def is_automatic(config: RunnableConfig | None) -> bool:
    """Whether the run is an automatic follow-up turn (only an explicit True counts)."""
    configurable = cast(Mapping[str, object], (config or {}).get("configurable") or {})
    return configurable.get(AUTOMATIC_KEY) is True


def job_scope(config: RunnableConfig | None) -> tuple[UUID, str] | None:
    """The user and thread of the run, from its configuration; None when it names none (or
    they do not fit): the tool then starts and reads nothing."""
    configurable = cast(Mapping[str, object], (config or {}).get("configurable") or {})
    owner, thread = configurable.get(OWNER_KEY), configurable.get(THREAD_KEY)
    if not isinstance(owner, str) or not isinstance(thread, str) or not thread:
        return None
    try:
        return UUID(owner), thread
    except ValueError:
        return None
