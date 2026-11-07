"""A held thread as the interface restores it: its text messages, workspace and usage."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from agent.completion import is_nudge
from api.schemas.chat import ConfirmationPrompt, ThreadMessage, ThreadSnapshot
from api.schemas.workspace import WorkspaceState
from api.services.confirmation import request_event
from api.services.threads import ThreadStore
from api.services.usage_meter import summarize
from config.ui import ModelPrice
from tools.schemas import ConfirmationRequest


def _text(message: BaseMessage) -> str:
    """The message's text; content blocks other than text (tool calls, images) are left out."""
    content = message.content
    if isinstance(content, str):
        return content.strip()
    parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
    return "".join(part for part in parts if isinstance(part, str)).strip()


def thread_messages(messages: Sequence[BaseMessage]) -> list[ThreadMessage]:
    """The user and assistant text of ``messages``, one assistant message per turn.

    Assistant text written between tool calls is joined with a blank line, as the live chat
    shows it; tool calls, tool results, empty messages and the completion guardrail's nudges
    are dropped (the text written after a nudge joins the same assistant message).
    """
    shown: list[ThreadMessage] = []
    for message in messages:
        text = _text(message)
        if not text or is_nudge(message):
            continue
        if isinstance(message, HumanMessage):
            shown.append(ThreadMessage(role="user", text=text))
        elif isinstance(message, AIMessage) and shown and shown[-1].role == "assistant":
            shown[-1] = ThreadMessage(role="assistant", text=f"{shown[-1].text}\n\n{text}")
        elif isinstance(message, AIMessage):
            shown.append(ThreadMessage(role="assistant", text=text))
    return shown


def last_answer(messages: Sequence[BaseMessage]) -> str | None:
    """The text of the last assistant message as the chat shows it; None when there is none."""
    shown = thread_messages(messages)
    return next((m.text for m in reversed(shown) if m.role == "assistant"), None)


def _prompt(pending: ConfirmationRequest | None) -> ConfirmationPrompt | None:
    """The open request as the snapshot shows it, or None when nothing is open."""
    if pending is None:
        return None
    event = request_event(0, pending)
    return ConfirmationPrompt(request_id=event.request_id, entries=event.entries)


async def thread_snapshot(
    threads: ThreadStore,
    thread_id: str,
    pricing: Mapping[str, ModelPrice],
) -> ThreadSnapshot | None:
    """The snapshot of a held thread, or None when the program does not hold it."""
    if not await threads.holds(thread_id):
        return None
    await threads.touch(thread_id)
    return ThreadSnapshot(
        thread_id=thread_id,
        messages=thread_messages(await threads.messages(thread_id)),
        workspace=await threads.workspace(thread_id) or WorkspaceState(),
        usage=summarize(await threads.session_calls(thread_id), pricing),
        confirmation=_prompt(await threads.pending(thread_id)),
    )
