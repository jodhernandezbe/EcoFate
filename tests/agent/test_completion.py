"""Tests for the completion guardrail: a reply that only announces its next steps is nudged."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import cast

import pytest
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig, RunnableLambda
from langchain_core.tools import tool
from langgraph.graph import END

from agent.completion import (
    NUDGE_NAME,
    CompletionGuard,
    CompletionVerdict,
    is_nudge,
    judge,
    nudges_in_turn,
    route_after_completion,
)
from agent.graph import build_agent
from agent.guardrails import ScopeGuard
from agent.state import AgentState
from prompts.registry import load_prompt
from tests.fakes import ScriptedChatModel, completion_verdict, verdict

GUARD = CompletionGuard(classifier_prompt="REVIEW", nudge="CONTINUE", max_nudges=2)
TOOL_CALLS: list[str] = []


@tool
def lookup() -> str:
    """A tool the agent calls once it gets back to work."""
    TOOL_CALLS.append("lookup")
    return "result"


@pytest.fixture(autouse=True)
def _tools(monkeypatch: pytest.MonkeyPatch) -> None:
    TOOL_CALLS.clear()
    monkeypatch.setattr("agent.graph.get_all_tools", lambda: [lookup])


def _call(name: str = "lookup") -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": {}, "id": "c1"}])


def _run(
    model: ScriptedChatModel,
    text: str = "map hexane",
    guard: CompletionGuard | None = GUARD,
) -> AgentState:
    state: AgentState = {"messages": [HumanMessage(content=text)]}
    return cast(AgentState, build_agent(model, completion_guard=guard).invoke(state))


def _texts(state: AgentState) -> list[str]:
    return [m.text for m in state["messages"] if isinstance(m, AIMessage)]


# --- the graph ---------------------------------------------------------------------------------


def test_a_complete_reply_ends_the_turn() -> None:
    model = ScriptedChatModel([AIMessage(content="Done.")], classifier=[completion_verdict(True)])
    state = _run(model)
    assert _texts(state) == ["Done."]
    assert model.calls == 1 and model.classifier.calls == 1


def test_a_reply_that_defers_its_work_is_nudged_and_the_agent_continues() -> None:
    model = ScriptedChatModel(
        [AIMessage(content="I will now gather the data."), _call(), AIMessage(content="Report.")],
        classifier=[completion_verdict(False, "announces work"), completion_verdict(True)],
    )
    state = _run(model)
    assert _texts(state) == ["I will now gather the data.", "", "Report."]
    assert TOOL_CALLS == ["lookup"]
    nudges = [m for m in state["messages"] if is_nudge(m)]
    assert len(nudges) == 1 and nudges[0].text == "CONTINUE"
    # The agent saw the nudge as the latest message when it continued.
    assert is_nudge(model.inputs[1][-1])


def test_nudges_stop_at_the_limit() -> None:
    model = ScriptedChatModel(
        [
            AIMessage(content="Soon."),
            AIMessage(content="Very soon."),
            AIMessage(content="Any minute."),
        ],
        classifier=[completion_verdict(False)] * 3,
    )
    state = _run(model)
    assert _texts(state) == ["Soon.", "Very soon.", "Any minute."]
    assert nudges_in_turn(state["messages"]) == 2
    assert model.classifier.calls == 2  # the limit is checked before asking again


def test_a_failed_review_lets_the_reply_stand(caplog: pytest.LogCaptureFixture) -> None:
    model = ScriptedChatModel([AIMessage(content="Soon.")], classifier=[AIMessage(content="??")])
    with caplog.at_level(logging.WARNING, logger="agent.completion"):
        state = _run(model)
    assert _texts(state) == ["Soon."]
    assert "letting the reply stand" in caplog.text


def test_without_the_guard_the_graph_is_as_before() -> None:
    model = ScriptedChatModel([AIMessage(content="Soon.")])
    assert _texts(_run(model, guard=None)) == ["Soon."]


def test_a_second_user_turn_gets_its_own_nudges() -> None:
    once = CompletionGuard(classifier_prompt="REVIEW", nudge="CONTINUE", max_nudges=1)
    texts = ("Soon.", "Later.", "Soon again.", "Done.")
    model = ScriptedChatModel(
        [AIMessage(content=text) for text in texts],
        classifier=[completion_verdict(False)] * 3,
    )
    first = _run(model, guard=once)
    assert nudges_in_turn(first["messages"]) == 1
    state: AgentState = {"messages": [*first["messages"], HumanMessage(content="and benzene?")]}
    second = cast(AgentState, build_agent(model, completion_guard=once).invoke(state))
    assert _texts(second)[-2:] == ["Soon again.", "Done."]
    assert nudges_in_turn(second["messages"]) == 1


def test_works_with_the_scope_check_too() -> None:
    scope = ScopeGuard(classifier_prompt="CLASSIFY", fallback_reply="FALLBACK")
    model = ScriptedChatModel(
        [AIMessage(content="Soon."), AIMessage(content="Done.")],
        classifier=[verdict(True), completion_verdict(False), completion_verdict(True)],
    )
    state: AgentState = {"messages": [HumanMessage(content="map hexane")]}
    graph = build_agent(model, scope_guard=scope, completion_guard=GUARD)
    result = cast(AgentState, graph.invoke(state))
    assert _texts(result) == ["Soon.", "Done."]


# --- the review itself -------------------------------------------------------------------------


def _judge(messages: Sequence[AnyMessage], *answers: AIMessage) -> CompletionVerdict | None:
    model = ScriptedChatModel([], classifier=list(answers))
    return judge(model, GUARD, messages, cast(RunnableConfig, {}))


def test_the_reviewer_sees_the_request_and_the_reply_only() -> None:
    model = ScriptedChatModel([], classifier=[completion_verdict(True)])
    messages: list[AnyMessage] = [
        HumanMessage(content="earlier question"),
        AIMessage(content="earlier answer"),
        HumanMessage(content="map hexane"),
        AIMessage(content="", tool_calls=[{"name": "lookup", "args": {}, "id": "1"}]),
        ToolMessage(content="result", tool_call_id="1"),
        AIMessage(content="I will now gather the data."),
    ]
    judge(model, GUARD, messages, cast(RunnableConfig, {}))
    material = model.classifier.inputs[0][-1].text
    assert "<user_request>\nmap hexane\n</user_request>" in material
    assert "<reply>\nI will now gather the data.\n</reply>" in material
    assert "earlier" not in material and "result" not in material
    assert model.classifier.inputs[0][0].text == "REVIEW"


def test_a_reply_with_tool_calls_or_no_text_is_not_reviewed() -> None:
    messages: list[AnyMessage] = [HumanMessage(content="q"), _call()]
    assert _judge(messages, completion_verdict(False)) is None
    assert (
        _judge([HumanMessage(content="q"), AIMessage(content="  ")], completion_verdict(False))
        is None
    )


def test_the_request_is_the_users_latest_message_not_a_nudge() -> None:
    model = ScriptedChatModel([], classifier=[completion_verdict(True)])
    messages: list[AnyMessage] = [
        HumanMessage(content="map hexane"),
        AIMessage(content="Soon."),
        HumanMessage(content="CONTINUE", name=NUDGE_NAME),
        AIMessage(content="Still soon."),
    ]
    judge(model, GUARD, messages, cast(RunnableConfig, {}))
    assert "<user_request>\nmap hexane\n</user_request>" in model.classifier.inputs[0][-1].text
    assert nudges_in_turn(messages) == 1


class Refusal(Exception):
    """A provider refusal: it carries an HTTP status."""

    status_code = 402


class RefusingModel(ScriptedChatModel):
    """A model whose structured calls are refused by the provider."""

    def __init__(self) -> None:
        super().__init__([])

    def with_structured_output(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        schema: object,
        *,
        include_raw: bool = False,
        **kwargs: object,
    ) -> RunnableLambda[object, object]:
        def fail(_: object) -> object:
            raise Refusal("no credits")

        return RunnableLambda(fail)


def test_a_provider_failure_is_logged_without_a_traceback_and_fails_open(
    caplog: pytest.LogCaptureFixture,
) -> None:
    messages: list[AnyMessage] = [HumanMessage(content="q"), AIMessage(content="Soon.")]
    with caplog.at_level(logging.WARNING, logger="agent.completion"):
        assert judge(RefusingModel(), GUARD, messages, cast(RunnableConfig, {})) is None
    assert "Refusal" in caplog.text and "Traceback" not in caplog.text


def test_routing_after_the_check() -> None:
    assert route_after_completion({"messages": [AIMessage(content="Done.")]}) == END
    assert (
        route_after_completion({"messages": [HumanMessage(content="go", name=NUDGE_NAME)]})
        == "model"
    )
    assert route_after_completion({"messages": []}) == END


def test_the_shipped_prompts_load_and_name_no_tool() -> None:
    check = load_prompt("completion_check")
    assert all(tag in check for tag in ("<role>", "<context>", "<instructions>", "<output_format>"))
    assert "complete" in check and "waiting" in check.lower()
    assert "lookup" not in check
    assert "Continue now" in load_prompt("completion_nudge")
