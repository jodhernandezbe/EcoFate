"""Tests for opening a confirmation request from a turn's tool results."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

from agent.graph import build_agent
from agent.missing import ask_text, collect_missing, open_request
from tools.schemas import MissingEntry


def _entry(entry_id: str, quantity: str = "iur", subject: str = "71-43-2") -> MissingEntry:
    return MissingEntry(
        entry_id=entry_id,
        quantity=quantity,
        subject=subject,
        accepted_units=["1/(ug/m^3)", "1/(mg/m^3)"],
        minimum=1e-9,
        maximum=1000.0,
        purpose="the cancer risk",
    )


def _result(call_id: str, payload: object) -> ToolMessage:
    return ToolMessage(content=json.dumps(payload), tool_call_id=call_id)


class FakeToolModel(GenericFakeChatModel):
    def bind_tools(self, tools: Any, **kwargs: Any) -> FakeToolModel:
        return self


def test_missing_entries_are_collected_from_tool_results() -> None:
    messages = [
        HumanMessage(content="assess"),
        _result("1", {"missing": [_entry("iur:71-43-2")]}),
    ]
    assert [e["entry_id"] for e in collect_missing(messages)] == ["iur:71-43-2"]


def test_repeated_entries_are_listed_once_in_order() -> None:
    messages = [
        HumanMessage(content="assess"),
        _result("1", {"missing": [_entry("iur:A"), _entry("rfc:A", "rfc")]}),
        _result("2", {"missing": [_entry("iur:A")]}),
    ]
    assert [e["entry_id"] for e in collect_missing(messages)] == ["iur:A", "rfc:A"]


def test_entries_from_an_earlier_turn_are_not_collected() -> None:
    messages = [
        HumanMessage(content="first"),
        _result("1", {"missing": [_entry("iur:A")]}),
        HumanMessage(content="second"),
        _result("2", {"missing": []}),
    ]
    assert collect_missing(messages) == []


def test_results_without_a_usable_list_contribute_nothing() -> None:
    messages = [
        HumanMessage(content="assess"),
        ToolMessage(content="not json", tool_call_id="1"),
        _result("2", ["a", "list"]),
        _result("3", {"missing": "nope"}),
        _result("4", {"missing": [{"quantity": "iur"}, "x", None]}),
    ]
    assert collect_missing(messages) == []


def test_request_has_a_new_identifier_each_time() -> None:
    first = open_request([_entry("iur:A")])
    second = open_request([_entry("iur:A")])
    assert first["request_id"] != second["request_id"]
    assert first["entries"] == second["entries"]


def test_ask_text_names_each_value_its_purpose_and_units() -> None:
    text = ask_text(open_request([_entry("iur:71-43-2")]))
    assert "iur for 71-43-2" in text
    assert "the cancer risk" in text
    assert "1/(ug/m^3), 1/(mg/m^3)" in text
    assert "proceed without it" in text


@tool
def fetch_benchmark(cas: str) -> str:
    """Test tool that reports one missing benchmark."""
    return json.dumps({"cas": cas, "missing": [_entry(f"iur:{cas}")]})


@tool
def fetch_nothing(cas: str) -> str:
    """Test tool that reports nothing missing."""
    return json.dumps({"cas": cas, "missing": []})


def _call(name: str, call_id: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": {"cas": "71-43-2"}, "id": call_id}],
    )


def test_turn_stops_with_a_request_when_a_tool_reports_missing() -> None:
    model = FakeToolModel(
        messages=iter([_call("fetch_benchmark", "c1"), AIMessage(content="never")]),
    )
    agent = build_agent(model, tools=[fetch_benchmark])
    result = agent.invoke({"messages": [HumanMessage(content="assess")]})
    assert result["pending"] is not None
    assert [e["entry_id"] for e in result["pending"]["entries"]] == ["iur:71-43-2"]
    assert result["messages"][-1].content.startswith("I could not find")
    assert "never" not in [m.content for m in result["messages"]]


def test_turn_continues_when_nothing_is_missing() -> None:
    model = FakeToolModel(
        messages=iter([_call("fetch_nothing", "c1"), AIMessage(content="the answer")]),
    )
    agent = build_agent(model, tools=[fetch_nothing])
    result = agent.invoke({"messages": [HumanMessage(content="assess")]})
    assert result.get("pending") is None
    assert result["messages"][-1].content == "the answer"
