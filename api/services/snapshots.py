"""A held thread as the interface restores it: its text messages, workspace and usage."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from agent.completion import is_nudge
from api.schemas.chat import ConfirmationPrompt, RunningTurn, ThreadMessage, ThreadSnapshot
from api.schemas.workspace import WorkspaceState
from api.services.confirmation import request_event
from api.services.jobs import job_infos
from api.services.projectors.rules import WorkspaceRules
from api.services.threads import ThreadStore
from api.services.turn_lifecycle import interruption
from api.services.usage_meter import summarize
from api.services.workspace_sync import current_workspace
from app.turns import FailureReason
from app.turns.follow_up import AUTOMATIC
from config.ui import ModelPrice
from storage.keys import ThreadKey
from storage.turn_model import OPEN_STATUSES, Turn
from tools.schemas import ConfirmationRequest


def _text(message: BaseMessage) -> str:
    """The message's text; content blocks other than text (tool calls, images) are left out."""
    content = message.content
    if isinstance(content, str):
        return content.strip()
    parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
    return "".join(part for part in parts if isinstance(part, str)).strip()


def _is_notice(message: BaseMessage) -> bool:
    """Whether the message is the notice of a background job's end (for the agent, not the chat)."""
    return isinstance(message, HumanMessage) and AUTOMATIC in message.additional_kwargs


def _shown_text(shown: list[ThreadMessage], message: BaseMessage, text: str, fresh: bool) -> bool:
    """Add an assistant message's text (joined to the turn's earlier text unless ``fresh``);
    whether the next assistant text still belongs to the same message."""
    if shown and shown[-1].role == "assistant" and not fresh:
        shown[-1] = ThreadMessage(role="assistant", text=f"{shown[-1].text}\n\n{text}")
    else:
        shown.append(ThreadMessage(role="assistant", text=text))
    return False


def thread_messages(messages: Sequence[BaseMessage]) -> list[ThreadMessage]:
    """The user and assistant text of ``messages``, one assistant message per turn.

    Assistant text written between tool calls is joined with a blank line, as the live chat
    shows it; tool calls, tool results, empty messages and the completion guardrail's nudges
    are dropped (the text written after a nudge joins the same assistant message). A user
    message, or the notice of a background job's end, starts a new assistant message.
    """
    shown: list[ThreadMessage] = []
    fresh = True
    for message in messages:
        text = _text(message)
        if _is_notice(message):
            fresh = True
        elif not text or is_nudge(message):
            continue
        elif isinstance(message, HumanMessage):
            shown.append(ThreadMessage(role="user", text=text))
            fresh = True
        elif isinstance(message, AIMessage):
            fresh = _shown_text(shown, message, text, fresh)
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


@dataclass(frozen=True)
class SnapshotOptions:
    """How a snapshot is reported.

    Attributes:
        pricing: Model name -> token prices.
        max_resumes: How often one interrupted turn may be resumed.
        rules: Rebuilds the workspace from the stored tool results (a turn nobody watched still
            shows); None reports the stored workspace.
        stale_after: A running turn with an older heartbeat is first interrupted as
            ``worker_lost``; None checks nothing.
    """

    pricing: Mapping[str, ModelPrice]
    max_resumes: int
    rules: WorkspaceRules | None = None
    stale_after: timedelta | None = None


async def thread_snapshot(
    threads: ThreadStore,
    key: ThreadKey,
    options: SnapshotOptions,
) -> ThreadSnapshot | None:
    """The snapshot of a held thread, or None when the program does not hold it.

    ``interrupted`` reports the latest turn when it was interrupted (resumable while it has been
    resumed fewer than ``max_resumes`` times); ``running_turn_id`` names a queued or running
    latest turn, so a reloaded page can reattach to its events.
    """
    if not await threads.holds(key):
        return None
    await threads.touch(key)
    latest = await _latest(threads, key, options.stale_after)
    running = latest if latest is not None and latest.status in OPEN_STATUSES else None
    messages = await threads.messages(key)
    return ThreadSnapshot(
        thread_id=key.thread_id,
        messages=thread_messages(_before(messages, running)),
        workspace=await _workspace(threads, key, options.rules),
        usage=summarize(await threads.session_calls(key), options.pricing),
        confirmation=_prompt(await threads.pending(key)),
        interrupted=interruption(latest, options.max_resumes),
        running_turn=_running(running),
        jobs=await job_infos(threads.jobs, key),
    )


def _running(turn: Turn | None) -> RunningTurn | None:
    if turn is None:
        return None
    # A follow-up's input is the system's notice, not something the user said: never shown.
    question = turn.planned.question if turn.planned is not None and not turn.automatic else None
    return RunningTurn(turn_id=turn.id, resumed=turn.resume_count > 0, question=question)


def _before(messages: list[BaseMessage], running: Turn | None) -> list[BaseMessage]:
    """The history before the running turn's input: what the turn adds is shown from its
    events, so it is never shown twice. A turn whose input is not in the history yet (still
    queued) cuts nothing."""
    if running is None or running.planned is None:
        return messages
    sent = running.planned.message
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if isinstance(message, HumanMessage) and message.content == sent:
            return messages[:index]
    return messages


async def _latest(
    threads: ThreadStore,
    key: ThreadKey,
    stale_after: timedelta | None,
) -> Turn | None:
    """The thread's latest turn, after a running one whose worker was lost is interrupted."""
    if stale_after is not None:
        stale = await threads.turns.interrupt_stale(stale_after, FailureReason.WORKER_LOST, key)
        if stale:
            await threads.release(key)
    return await threads.turns.latest(key)


async def _workspace(
    threads: ThreadStore,
    key: ThreadKey,
    rules: WorkspaceRules | None,
) -> WorkspaceState:
    if rules is None or not await threads.tool_messages(key):
        return await threads.workspace(key) or WorkspaceState()
    return await current_workspace(threads, key, rules)
