"""Tests for running the agent and extracting the run record (scripted fake chat model)."""

from __future__ import annotations

from typing import Any

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from config.agent import AgentSettings
from evals.cassette import Cassette, replay_tools
from evals.runner import run_scenario


class FakeToolModel(GenericFakeChatModel):
    def bind_tools(self, tools: Any, **kwargs: Any) -> FakeToolModel:
        return self


@tool
def lookup(name: str) -> dict[str, str]:
    """Look up a name (test stand-in)."""
    return {"found": name.upper()}


def _settings(recursion_limit: int) -> AgentSettings:
    return AgentSettings("openai", "fake", "UNUSED_KEY_VAR", 1.0, recursion_limit, 0.0, 3)


def _call(call_id: str, name: str = "abc") -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": "lookup", "args": {"name": name}, "id": call_id}],
    )


def test_completed_run_pairs_calls_with_outputs_in_order() -> None:
    script = iter([_call("c1", "abc"), _call("c2", "xyz"), AIMessage(content="done")])
    record = run_scenario(FakeToolModel(messages=script), [lookup], ("s1", "query"), _settings(20))
    assert record.completed
    assert record.report == "done"
    assert [(c.name, dict(c.args)) for c in record.calls] == [
        ("lookup", {"name": "abc"}),
        ("lookup", {"name": "xyz"}),
    ]
    assert record.calls[0].output == {"found": "ABC"}
    assert not record.calls[0].unrecorded


def test_unrecorded_replay_is_marked() -> None:
    tools = replay_tools([lookup], Cassette(), live_tools=())
    script = iter([_call("c1"), AIMessage(content="done")])
    record = run_scenario(FakeToolModel(messages=script), tools, ("s1", "query"), _settings(20))
    assert record.calls[0].unrecorded


def test_step_limit_ends_the_run_with_an_error_record() -> None:
    script = iter([_call(f"c{i}") for i in range(20)])
    record = run_scenario(FakeToolModel(messages=script), [lookup], ("s1", "query"), _settings(3))
    assert not record.completed
    assert record.error is not None and "GraphRecursionError" in record.error
    assert record.calls, "calls made before the limit are kept"
