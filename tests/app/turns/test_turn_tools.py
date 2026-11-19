"""The job-status tool is offered to a turn only when its conversation has a background job."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.turns import TurnRequest, TurnServices
from app.turns.keys import TurnKeys
from app.turns.runner import _has_jobs  # pyright: ignore[reportPrivateUsage]
from app.usage_meter import CallUsage
from tests.fakes import ScriptedChatModel
from tools.jobs.port import JobUnavailableError
from tools.schemas import JobStatusEntry, SubmittedJob

OWNER = uuid4()
REQUEST = TurnRequest(thread_id="t1", question="q", message="q", user_id=str(OWNER))


class _Port:
    """A job system holding the given jobs for (owner, thread); records what was asked."""

    def __init__(self, jobs: Mapping[tuple[UUID, str], list[JobStatusEntry]]) -> None:
        self.jobs = jobs
        self.asked: list[tuple[UUID, str]] = []

    async def submit(
        self,
        owner_id: UUID,
        thread_id: str,
        tool: str,
        job_input: Mapping[str, object],
    ) -> SubmittedJob | None:
        raise AssertionError("a turn's tool selection never submits")

    async def status(
        self,
        owner_id: UUID,
        thread_id: str,
        job_id: str | None,
    ) -> list[JobStatusEntry]:
        self.asked.append((owner_id, thread_id))
        return self.jobs.get((owner_id, thread_id), [])


async def _no_keys() -> TurnKeys:
    raise AssertionError("not needed")


async def _no_values() -> object:
    raise AssertionError("not needed")


async def _usage(calls: object) -> list[CallUsage]:
    return []


def _services(port: _Port | None) -> TurnServices:
    return TurnServices(
        load_keys=_no_keys,
        build_model=lambda key: ScriptedChatModel([]),
        checkpointer=InMemorySaver(),
        user_values=_no_values,  # type: ignore[arg-type]
        record_usage=_usage,  # type: ignore[arg-type]
        jobs=port,
    )


ENTRY: JobStatusEntry = {"job_id": "j1", "tool": "assess_facilities", "status": "running"}  # type: ignore[typeddict-item]


@pytest.mark.anyio
async def test_no_job_system_means_no_jobs() -> None:
    assert await _has_jobs(REQUEST, _services(None)) is False


@pytest.mark.anyio
async def test_a_conversation_without_jobs_has_none() -> None:
    port = _Port({})
    assert await _has_jobs(REQUEST, _services(port)) is False
    assert port.asked == [(OWNER, "t1")]


@pytest.mark.anyio
async def test_a_conversation_with_a_job_has_one() -> None:
    port = _Port({(OWNER, "t1"): [ENTRY]})
    assert await _has_jobs(REQUEST, _services(port)) is True


@pytest.mark.anyio
async def test_another_users_job_does_not_count() -> None:
    port = _Port({(uuid4(), "t1"): [ENTRY]})
    assert await _has_jobs(REQUEST, _services(port)) is False


@pytest.mark.anyio
async def test_a_run_without_a_user_asks_nothing() -> None:
    port = _Port({(OWNER, "t1"): [ENTRY]})
    assert await _has_jobs(replace(REQUEST, user_id=None), _services(port)) is False
    assert port.asked == []


class _DownPort(_Port):
    async def status(
        self,
        owner_id: UUID,
        thread_id: str,
        job_id: str | None,
    ) -> list[JobStatusEntry]:
        raise JobUnavailableError


@pytest.mark.anyio
async def test_an_unreachable_job_store_does_not_fail_the_turn() -> None:
    assert await _has_jobs(REQUEST, _services(_DownPort({}))) is False
