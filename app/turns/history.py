"""Keep a thread's history valid for the provider when an interrupted turn is abandoned.

A turn interrupted between the model asking for tools and the tools answering leaves tool
calls without results; providers reject such a history. Before a new message runs, each of
those calls gets a result saying it was not run.
"""

from __future__ import annotations

from collections.abc import Sequence

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

# What the model reads in place of a tool's result (not shown to the user).
NOT_RUN = "Not run: the turn was interrupted and not resumed. Call the tool again if still needed."


def unanswered_calls(messages: Sequence[BaseMessage]) -> list[tuple[str, str]]:
    """``(call id, tool name)`` of each tool call of the last assistant message with no result."""
    answered: set[str] = set()
    for message in reversed(messages):
        if isinstance(message, ToolMessage):
            answered.add(message.tool_call_id)
        elif isinstance(message, AIMessage):
            calls = message.tool_calls
            return [(str(c["id"]), c["name"]) for c in calls if c["id"] not in answered]
    return []


def not_run_results(messages: Sequence[BaseMessage]) -> list[ToolMessage]:
    """A "not run" error result for each unanswered tool call of the last assistant message."""
    return [
        ToolMessage(NOT_RUN, tool_call_id=call_id, name=name, status="error")
        for call_id, name in unanswered_calls(messages)
    ]
