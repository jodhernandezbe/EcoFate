"""LangGraph agent scaffold.

The chat model is an injected dependency: this module only knows about
``BaseChatModel`` and never imports a provider package (OpenAI, Anthropic, ...).
"""

from __future__ import annotations

from collections.abc import Hashable, Sequence

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from agent.completion import CompletionGuard, build_completion_node, route_after_completion
from agent.guardrails import ScopeGuard, build_scope_node, route_after_scope
from agent.missing import ask_for_values, route_after_tools
from agent.state import AgentState
from prompts.registry import load_prompt
from tools.registry import JOB_TOOL_NAMES, get_all_tools

DEFAULT_SYSTEM_PROMPT = "agent_system"


def _add_entry(
    graph: StateGraph[AgentState],
    model: BaseChatModel,
    scope_guard: ScopeGuard | None,
) -> None:
    """Connect START to the agent, through the scope check when there is one."""
    if scope_guard is None:
        graph.add_edge(START, "model")
        return
    graph.add_node("scope", build_scope_node(model, scope_guard))
    graph.add_edge(START, "scope")
    graph.add_conditional_edges("scope", route_after_scope, {"model": "model", END: END})


def _add_exit(
    graph: StateGraph[AgentState],
    model: BaseChatModel,
    completion_guard: CompletionGuard | None,
    has_tools: bool,
) -> None:
    """Connect the agent's answer to END, through the completion check when there is one."""
    if completion_guard is None:
        if has_tools:
            graph.add_conditional_edges("model", tools_condition)
        else:
            graph.add_edge("model", END)
        return
    graph.add_node("finish", build_completion_node(model, completion_guard))
    if has_tools:
        route: dict[Hashable, str] = {"tools": "tools", END: "finish"}
        graph.add_conditional_edges("model", tools_condition, route)
    else:
        graph.add_edge("model", "finish")
    graph.add_conditional_edges("finish", route_after_completion, {"model": "model", END: END})


def turn_tools(has_jobs: bool) -> list[BaseTool]:
    """The tools of one turn: every registered tool, but the job-status tool only once the
    conversation has a background job. Measured (docs/load-test.md): offering it in every turn
    made the model state a CAS number recalled from a chemical's name; a turn with nothing to
    check gets exactly the tools it had before background jobs existed."""
    tools = get_all_tools()
    return tools if has_jobs else [tool for tool in tools if tool.name not in JOB_TOOL_NAMES]


def build_agent(
    model: BaseChatModel,
    tools: Sequence[BaseTool] | None = None,
    system_prompt: str | None = None,
    checkpointer: BaseCheckpointSaver[str] | None = None,
    scope_guard: ScopeGuard | None = None,
    completion_guard: CompletionGuard | None = None,
) -> CompiledStateGraph[AgentState, None, AgentState, AgentState]:
    """Compile a tool-calling agent graph around an injected chat model.

    Args:
        model: Any LangChain chat model that supports tool calling. Constructed
            by the caller so the provider can be swapped without touching this module.
        tools: Tools to bind. Defaults to everything in the tool registry.
        system_prompt: System prompt text. Defaults to ``prompts/agent_system.md``.
        checkpointer: Keeps each thread's history between invocations (pass a ``thread_id``
            in the run config). None, the default, keeps no history between calls.
        scope_guard: When given, every user turn is first classified by ``model`` and an
            off-topic one is answered with a redirect without running the agent or its tools.
            None, the default, leaves the graph exactly as without the check.
        completion_guard: When given, every answer is reviewed by ``model`` and one that only
            announces the work it will do next sends the agent back to work (a bounded number
            of times). None, the default, leaves the graph exactly as without the check.

    Returns:
        A compiled graph; invoke it with ``{"messages": [...]}``.
    """
    bound_tools = list(tools) if tools is not None else get_all_tools()
    prompt_text = system_prompt if system_prompt is not None else load_prompt(DEFAULT_SYSTEM_PROMPT)
    runnable = model.bind_tools(bound_tools) if bound_tools else model

    def call_model(state: AgentState) -> AgentState:
        note = state.get("answers_note", "")
        instructions = f"{prompt_text}\n\n{note}" if note else prompt_text
        messages = [SystemMessage(content=instructions), *state["messages"]]
        return {"messages": [runnable.invoke(messages)]}

    graph = StateGraph(AgentState)
    graph.add_node("model", call_model)
    _add_entry(graph, model, scope_guard)
    if bound_tools:
        graph.add_node("tools", ToolNode(bound_tools))
        graph.add_node("ask", ask_for_values)
        graph.add_conditional_edges("tools", route_after_tools, {"ask": "ask", "model": "model"})
        graph.add_edge("ask", END)
    _add_exit(graph, model, completion_guard, bool(bound_tools))
    return graph.compile(checkpointer=checkpointer)
