"""Tests that the agent accepts an injected chat model."""

from __future__ import annotations

from typing import Any

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver

from agent.graph import build_agent


class FakeToolModel(GenericFakeChatModel):
    def bind_tools(self, tools: Any, **kwargs: Any) -> FakeToolModel:
        return self


def test_build_agent_with_injected_model() -> None:
    model = FakeToolModel(messages=iter([AIMessage(content="done")]))
    agent = build_agent(model)
    result = agent.invoke({"messages": [HumanMessage(content="hi")]})
    assert result["messages"][-1].content == "done"


def test_default_graph_has_no_checkpointer_and_the_same_nodes() -> None:
    agent = build_agent(FakeToolModel(messages=iter([])))
    assert agent.checkpointer is None
    assert set(agent.get_graph().nodes) == {"__start__", "model", "tools", "ask", "__end__"}


def test_checkpointer_keeps_the_thread_history() -> None:
    model = FakeToolModel(messages=iter([AIMessage(content="one"), AIMessage(content="two")]))
    agent = build_agent(model, checkpointer=InMemorySaver())
    config: RunnableConfig = {"configurable": {"thread_id": "t1"}}
    agent.invoke({"messages": [HumanMessage(content="first")]}, config)
    result = agent.invoke({"messages": [HumanMessage(content="second")]}, config)
    texts = [message.content for message in result["messages"]]
    assert texts == ["first", "one", "second", "two"]


def test_the_job_status_tool_is_offered_only_with_a_job() -> None:
    from agent.graph import turn_tools
    from tools.registry import JOB_TOOL_NAMES, get_all_tools

    every = {tool.name for tool in get_all_tools()}
    assert {tool.name for tool in turn_tools(has_jobs=True)} == every
    assert {tool.name for tool in turn_tools(has_jobs=False)} == every - JOB_TOOL_NAMES
    assert "check_job_status" in JOB_TOOL_NAMES
