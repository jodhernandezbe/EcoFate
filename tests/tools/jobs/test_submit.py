"""The submitter of a heavy tool and ``check_job_status``: whose job it is, what is asked first."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

import pytest
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool

from tools.jobs import check_job_status, heavy_submitter
from tools.jobs.port import JobUnavailableError, provided_port, scope_config
from tools.schemas import JobStatusEntry, SubmittedJob

pytestmark = pytest.mark.anyio
OWNER = UUID(int=7)
FOREIGN = UUID(int=8)
CALLS: list[dict[str, Any]] = []


@tool(response_format="content_and_artifact")
def heavy(cas_number: str, radius_km: float | None = None, *, config: RunnableConfig) -> Any:
    """Do the heavy work.

    Args:
        cas_number: A CAS number.
        radius_km: A radius.
    """
    CALLS.append({"cas": cas_number, "config": config})
    return {"done": True}, {"full": True}


class FakePort:
    """A job port that records what it was asked and answers as scripted."""

    def __init__(self, *, over_cap: bool = False, down: bool = False) -> None:
        self.submitted: list[tuple[UUID, str, str, Mapping[str, object]]] = []
        self.asked: list[tuple[UUID, str, str | None]] = []
        self.over_cap, self.down = over_cap, down

    async def submit(
        self,
        owner_id: UUID,
        thread_id: str,
        tool: str,
        job_input: Mapping[str, object],
    ) -> SubmittedJob | None:
        if self.down:
            raise JobUnavailableError
        self.submitted.append((owner_id, thread_id, tool, job_input))
        return None if self.over_cap else SubmittedJob(job_id="a" * 32, status="queued", position=2)

    async def status(
        self,
        owner_id: UUID,
        thread_id: str,
        job_id: str | None,
    ) -> list[JobStatusEntry]:
        self.asked.append((owner_id, thread_id, job_id))
        return [
            JobStatusEntry(job_id="a" * 32, tool="heavy", status="running", elapsed_seconds=3.0),
        ]


def _config(owner: UUID | None = OWNER, thread: str = "t1", **extra: object) -> RunnableConfig:
    scope = scope_config(owner, thread) if owner is not None else {}
    return {"configurable": {**scope, **extra}}


def _submitter(early: Any = None) -> BaseTool:
    return heavy_submitter(heavy, lambda arguments, config: early)


@pytest.fixture(autouse=True)
def _clear() -> None:
    CALLS.clear()


async def test_a_call_queues_a_job_with_the_stored_input_shape() -> None:
    port = FakePort()
    answers = {"supplied": {"vapor_pressure:x": 1.5}, "declined": ["rfc:x"]}
    with provided_port(port):
        result = await _submitter().ainvoke(
            {"cas_number": "110-54-3", "radius_km": 2.0},
            _config(user_values=answers),
        )
    assert result == {"job_id": "a" * 32, "status": "queued", "position": 2}
    assert CALLS == []  # the work did not run in the turn
    ((owner, thread, name, stored),) = port.submitted
    assert (owner, thread, name) == (OWNER, "t1", "heavy")
    assert stored == {
        "arguments": {"cas_number": "110-54-3", "radius_km": 2.0},
        "user_values": answers,
    }


async def test_the_job_belongs_to_the_run_not_to_the_tool_arguments() -> None:
    port = FakePort()
    hostile = {"cas_number": "110-54-3", "owner_id": str(FOREIGN), "thread_id": "other"}
    with provided_port(port):
        await _submitter().ainvoke(hostile, _config(OWNER, "mine"))
    ((owner, thread, _, stored),) = port.submitted
    assert (owner, thread) == (OWNER, "mine")
    assert "owner_id" not in str(stored) and "other" not in str(stored)


async def test_a_run_without_a_user_starts_nothing() -> None:
    port = FakePort()
    with provided_port(port):
        result = await _submitter().ainvoke({"cas_number": "110-54-3"}, _config(None))
    assert isinstance(result, dict) and result["status"] == "unavailable"
    assert port.submitted == []


async def test_a_malformed_scope_starts_nothing() -> None:
    port = FakePort()
    bad: RunnableConfig = {"configurable": {"job_owner_id": "not-a-uuid", "job_thread_id": "t"}}
    with provided_port(port):
        result = await _submitter().ainvoke({"cas_number": "110-54-3"}, bad)
    assert isinstance(result, dict) and result["status"] == "unavailable"
    assert port.submitted == []


async def test_what_the_tool_must_settle_first_is_returned_and_no_job_is_recorded() -> None:
    port = FakePort()
    early = ({"missing": [{"entry_id": "rfc:x"}]}, {"asked": True})
    with provided_port(port):
        result = await _submitter(early).ainvoke({"cas_number": "110-54-3"}, _config())
    assert result == {"missing": [{"entry_id": "rfc:x"}]}
    assert port.submitted == []


async def test_an_automatic_follow_up_turn_cannot_start_a_job() -> None:
    port = FakePort()
    config: RunnableConfig = {"configurable": scope_config(OWNER, "t1", automatic=True)}
    with provided_port(port):
        result = await _submitter().ainvoke({"cas_number": "110-54-3"}, config)
    assert isinstance(result, dict) and result["status"] == "unavailable"
    assert port.submitted == []
    assert CALLS == []


async def test_only_an_explicit_true_marks_a_turn_automatic() -> None:
    port = FakePort()
    config = _config(job_automatic="yes")
    with provided_port(port):
        await _submitter().ainvoke({"cas_number": "110-54-3"}, config)
    assert len(port.submitted) == 1


async def test_over_the_cap_answers_a_fixed_message_and_records_nothing() -> None:
    port = FakePort(over_cap=True)
    with provided_port(port):
        result = await _submitter().ainvoke({"cas_number": "110-54-3"}, _config())
    assert isinstance(result, dict) and result["status"] == "limit_reached"
    assert "limit" in result["message"]


async def test_an_unreachable_queue_answers_a_fixed_message() -> None:
    with provided_port(FakePort(down=True)):
        result = await _submitter().ainvoke({"cas_number": "110-54-3"}, _config())
    assert isinstance(result, dict) and result["status"] == "unavailable"


async def test_without_a_job_system_the_tool_runs_as_it_always_did() -> None:
    result = await _submitter().ainvoke({"cas_number": "110-54-3"}, _config())
    assert result == {"done": True}
    assert [call["cas"] for call in CALLS] == ["110-54-3"]


def test_the_submitter_is_the_same_tool_to_the_model() -> None:
    submitter = _submitter()
    assert submitter.name == heavy.name and submitter.args_schema is heavy.args_schema
    assert submitter.description.startswith(heavy.description)
    assert "job_id" in submitter.description and "queued" in submitter.description


async def test_check_job_status_reads_the_runs_own_thread_only() -> None:
    port = FakePort()
    with provided_port(port):
        result = await check_job_status.ainvoke({"job_id": None}, _config(OWNER, "mine"))
    assert port.asked == [(OWNER, "mine", None)]
    assert result["jobs"][0]["status"] == "running" and "never state its results" in result["note"]


async def test_check_job_status_ignores_a_user_named_in_its_arguments() -> None:
    port = FakePort()
    with provided_port(port):
        await check_job_status.ainvoke(
            {"job_id": "b" * 32, "owner_id": str(FOREIGN)},
            _config(OWNER, "mine"),
        )
    assert port.asked == [(OWNER, "mine", "b" * 32)]


async def test_check_job_status_without_a_scope_reads_nothing() -> None:
    port = FakePort()
    with provided_port(port):
        result = await check_job_status.ainvoke({}, _config(None))
    assert result["jobs"] == [] and port.asked == []
