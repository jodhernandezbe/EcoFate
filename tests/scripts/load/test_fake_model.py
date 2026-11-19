"""Tests for scripts/load/fake_model.py: the scripted chat model's decisions."""

from __future__ import annotations

import asyncio

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from pydantic import BaseModel

from scripts.load.fake_model import (
    ANSWER_REPLY,
    ASSESS,
    RESULT_REPLY,
    RUNNING_REPLY,
    STARTED_REPLY,
    STATUS,
    ScriptedChatModel,
    passing_verdict,
    scripted_reply,
)

ARGS: dict[str, object] = {"cas_number": "placeholder"}


class Verdict(BaseModel):
    """A small verdict schema."""

    in_scope: bool
    reason: str


def _human(text: str) -> list[BaseMessage]:
    return [HumanMessage(content=text)]


def _tool(name: str, content: str) -> list[BaseMessage]:
    return [ToolMessage(content=content, name=name, tool_call_id="call_1")]


def test_assess_words_call_assess_facilities_with_args() -> None:
    reply = scripted_reply(_human("Please ASSESS this"), ARGS)
    assert reply.tool_calls[0]["name"] == ASSESS
    assert reply.tool_calls[0]["args"] == ARGS


def test_status_words_call_check_job_status() -> None:
    reply = scripted_reply(_human("What is the status?"), ARGS)
    assert reply.tool_calls[0]["name"] == STATUS


def test_status_wins_over_assess_words() -> None:
    reply = scripted_reply(_human("status of the assessment"), ARGS)
    assert reply.tool_calls[0]["name"] == STATUS


def test_status_tool_result_is_running_reply() -> None:
    assert scripted_reply(_tool(STATUS, "{}"), ARGS).content == RUNNING_REPLY


def test_queued_notice_is_started_reply() -> None:
    notice = '{"status": "queued", "position": 1}'
    assert scripted_reply(_tool(ASSESS, notice), ARGS).content == STARTED_REPLY


def test_other_tool_result_is_result_reply() -> None:
    assert scripted_reply(_tool(ASSESS, "{}"), ARGS).content == RESULT_REPLY


def test_queued_without_position_is_result_reply() -> None:
    assert scripted_reply(_tool(ASSESS, '{"status": "queued"}'), ARGS).content == RESULT_REPLY


def test_plain_question_gets_answer_reply() -> None:
    reply = scripted_reply(_human("what does screening-level mean?"), ARGS)
    assert reply.content == ANSWER_REPLY
    assert not reply.tool_calls


def test_empty_messages_do_not_crash() -> None:
    assert scripted_reply([], ARGS).content == ANSWER_REPLY


def test_passing_verdict_fills_bool_and_str() -> None:
    verdict = passing_verdict(Verdict)
    assert isinstance(verdict, Verdict)
    assert verdict.in_scope is True
    assert verdict.reason == "load test"


def test_model_invoke_sync_returns_scripted_message() -> None:
    model = ScriptedChatModel(model_seconds=0, assess_args=ARGS)
    reply = model.invoke("hello there")
    assert reply.content == ANSWER_REPLY


def test_model_invoke_async_returns_scripted_message() -> None:
    model = ScriptedChatModel(model_seconds=0, assess_args=ARGS)
    reply = asyncio.run(model.ainvoke("please assess"))
    assert isinstance(reply, AIMessage)
    assert reply.tool_calls[0]["name"] == ASSESS
    assert reply.tool_calls[0]["args"] == ARGS


def test_bind_tools_returns_the_model() -> None:
    model = ScriptedChatModel(model_seconds=0)
    assert model.bind_tools([]) is model


def test_structured_output_with_raw_returns_parsed_verdict() -> None:
    model = ScriptedChatModel(model_seconds=0)
    out = model.with_structured_output(Verdict, include_raw=True).invoke("anything")
    assert isinstance(out, dict)
    assert isinstance(out["parsed"], Verdict)
    assert out["parsing_error"] is None


def test_structured_output_without_raw_returns_verdict() -> None:
    model = ScriptedChatModel(model_seconds=0)
    out = model.with_structured_output(Verdict).invoke("anything")
    assert isinstance(out, Verdict)
