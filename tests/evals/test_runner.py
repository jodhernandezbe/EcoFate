"""Tests for running the agent and extracting the run record (scripted fake chat model)."""

from __future__ import annotations

from typing import Any

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatResult
from langchain_core.runnables import RunnableConfig
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


# --- follow-up turn after a request for missing values ----------------------------------------

ENTRY = {
    "entry_id": "iur:0-0-0",
    "quantity": "iur",
    "subject": "0-0-0",
    "accepted_units": ["1/(ug/m^3)"],
    "minimum": 1.0,
    "maximum": 2.0,
    "purpose": "test stand-in",
}
seen_declined: list[list[str]] = []


@tool
def properties(cas_number: str, config: RunnableConfig) -> dict[str, Any]:
    """Report a value as missing until the run's configuration declines it (test stand-in)."""
    declined = list((config.get("configurable") or {}).get("user_values", {}).get("declined", []))
    seen_declined.append(declined)
    return {"cas": cas_number, "missing": [] if ENTRY["entry_id"] in declined else [ENTRY]}


class RecordingModel(FakeToolModel):
    """Keeps the system message of every call, to see the note the model was given."""

    systems: list[str] = []

    def _generate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> ChatResult:
        self.systems.append(str(messages[0].content))
        return super()._generate(messages, *args, **kwargs)


def _properties_call(call_id: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": "properties", "args": {"cas_number": "0-0-0"}, "id": call_id}],
    )


def test_follow_up_continues_after_the_ask_with_the_entries_declined() -> None:
    seen_declined.clear()
    model = RecordingModel(
        messages=iter([_properties_call("c1"), _properties_call("c2"), AIMessage(content="final")]),
    )
    record = run_scenario(
        model,
        [properties],
        ("s1", "query"),
        _settings(20),
        follow_up="Proceed without them.",
    )
    assert record.completed
    assert record.report == "final"
    assert [c.name for c in record.calls] == ["properties", "properties"]
    assert seen_declined == [[], ["iur:0-0-0"]]
    assert record.calls[1].output == {"cas": "0-0-0", "missing": []}
    noted = [s for s in model.systems if "proceed without these values" in s]
    assert noted, "the follow-up turn gives the model the program's proceed-without note"
    assert all("iur:0-0-0" in s for s in noted)


def test_without_a_follow_up_the_run_ends_at_the_ask() -> None:
    model = FakeToolModel(messages=iter([_properties_call("c1")]))
    record = run_scenario(model, [properties], ("s1", "query"), _settings(20))
    assert record.completed
    assert [c.name for c in record.calls] == ["properties"]
    assert "iur" in record.report


def test_a_follow_up_is_not_sent_when_nothing_was_asked() -> None:
    # The script has one answer: a second model call would exhaust it and fail the run.
    model = FakeToolModel(messages=iter([AIMessage(content="answer")]))
    record = run_scenario(model, [lookup], ("s1", "query"), _settings(20), follow_up="Proceed.")
    assert record.completed
    assert record.report == "answer"
    assert record.calls == ()
