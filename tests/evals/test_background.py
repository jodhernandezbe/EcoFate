"""A background scenario end to end with a scripted fake chat model: no network, no OpenAI.

The heavy tool is a stand-in wrapped by the real submitter; its "job" ends from a cassette built
here with synthetic placeholder names (no real data).
"""

from __future__ import annotations

import asyncio
from typing import Any, cast
from uuid import uuid4

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool

from config.agent import AgentSettings
from evals import checks as c
from evals.cassette import Cassette, call_key
from evals.jobs import NOT_RECORDED, MemoryJobPort, ended_job
from evals.record import RunRecord
from evals.runner import run_scenario
from storage.job_model import JobStatus
from tools.jobs.submit import heavy_submitter

ARGS = {"cas_number": "0-0-0"}
RESULT = {
    "facilities": [{"frs_id": "F1", "facility_name": "Placeholder Plant"}],
    "facilities_found": 1,
}
CASSETTE = Cassette({c.ASSESSMENT: {call_key(ARGS): RESULT}})


class FakeToolModel(GenericFakeChatModel):
    def bind_tools(self, tools: Any, **kwargs: Any) -> FakeToolModel:
        return self


@tool(c.ASSESSMENT, response_format="content_and_artifact")
def assess(cas_number: str, config: RunnableConfig) -> tuple[dict[str, str], None]:
    """Assess the facilities (test stand-in); it must never run inside a background turn."""
    raise AssertionError("the stand-in ran inside the turn")


def _tools() -> list[BaseTool]:
    return [heavy_submitter(assess, lambda arguments, config: None)]


def _settings() -> AgentSettings:
    return AgentSettings("openai", "fake", "UNUSED_KEY_VAR", 1.0, 20, 0.0, 3)


def _call() -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": c.ASSESSMENT, "args": ARGS, "id": "c1"}])


def _run(cassette: Cassette, first: AIMessage, second: AIMessage) -> RunRecord:
    # A turn that queued a job is not reviewed by the completion guard (its work is running), so
    # turn 1 asks the model nothing after its reply; the follow-up's review finds the script
    # exhausted, which lets its reply stand.
    model = FakeToolModel(messages=iter([_call(), first, second]))
    return run_scenario(
        model,
        _tools(),
        ("s", "query"),
        _settings(),
        background=True,
        cassette=cassette,
    )


def test_job_is_queued_then_explained_in_a_second_turn() -> None:
    record = _run(
        CASSETTE,
        AIMessage(content="The assessment has started."),
        AIMessage(content="Report: Placeholder Plant (F1) was assessed."),
    )
    assert record.completed
    assert record.interim == "The assessment has started."
    assert record.report.startswith("Report")
    queued, explained = record.calls
    assert queued.output["status"] == "queued"  # type: ignore[index]
    assert explained.output == RESULT
    for check in (
        c.completed(),
        c.no_unrecorded(),
        c.submitted_as_job(),
        c.interim_states_no_results(),
        c.every_facility_covered(),
        c.every_covered_facility_reported(),
    ):
        assert check.evaluate(record).passed, check.name


def test_a_leaking_first_reply_fails_the_interim_check() -> None:
    record = _run(CASSETTE, AIMessage(content="Placeholder Plant is fine."), AIMessage(content="r"))
    assert not c.interim_states_no_results().evaluate(record).passed


def test_a_job_without_a_recording_fails_closed() -> None:
    record = _run(Cassette(), AIMessage(content="started"), AIMessage(content="could not finish"))
    queued = cast(dict[str, object], record.calls[0].output)
    assert record.calls[1].output == {
        "job_id": queued["job_id"],
        "status": "failed",
        "reason": NOT_RECORDED,
    }
    assert not c.every_covered_facility_reported().evaluate(record).passed


def test_memory_port_records_and_reports_jobs() -> None:
    port, owner = MemoryJobPort(), uuid4()
    submitted = asyncio.run(port.submit(owner, "t", c.ASSESSMENT, {"arguments": ARGS}))
    assert submitted is not None and submitted["status"] == "queued"
    (entry,) = asyncio.run(port.status(owner, "t", None))
    assert entry["job_id"] == submitted["job_id"] and "outcome" not in entry
    assert asyncio.run(port.status(uuid4(), "t", None)) == []
    assert asyncio.run(port.status(owner, "t", "0" * 32)) == []


def test_ended_job_takes_its_result_from_the_cassette() -> None:
    port, owner = MemoryJobPort(), uuid4()
    asyncio.run(port.submit(owner, "t", c.ASSESSMENT, {"arguments": ARGS}))
    job = ended_job(port.jobs[0], CASSETTE)
    assert job.status is JobStatus.SUCCEEDED and job.result_content == RESULT
    assert ended_job(port.jobs[0], Cassette()).status is JobStatus.FAILED
