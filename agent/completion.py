"""Completion guardrail: a model-based check, after the agent answers, that it did not stop early.

An opt-in node of the agent graph. A model that ends its turn by announcing the work it will
do next ("I will now gather the stack data…") leaves the assessment undone. The injected chat
model judges the final reply against the user's request; a reply that defers the copilot's own
work gets a nudge and the agent runs again, at most a few times per turn. The nudge is a named
user message, so the interface and the scope check can leave it out of what they show and judge.
The module never imports a provider package; the model is injected.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, cast

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END
from pydantic import BaseModel

from agent.state import AgentState
from tools.registry import is_queued_job

logger = logging.getLogger(__name__)

NUDGE_NAME = "completion_nudge"  # the name carried by the nudge message


class CompletionVerdict(BaseModel):
    """The reviewer's answer: whether the reply finishes what the copilot can do by itself."""

    complete: bool
    reason: str


@dataclass(frozen=True)
class CompletionGuard:
    """What the completion check needs besides the model.

    Attributes:
        classifier_prompt: System prompt of the reviewer.
        nudge: The message that sends the agent back to work.
        max_nudges: Most nudges in one user turn; past it the reply stands as it is.
    """

    classifier_prompt: str
    nudge: str
    max_nudges: int = 2


def is_nudge(message: BaseMessage) -> bool:
    """Whether the message is a nudge of this guardrail (not something the user wrote)."""
    return isinstance(message, HumanMessage) and message.name == NUDGE_NAME


def _turn(messages: Sequence[BaseMessage]) -> list[BaseMessage]:
    """The messages since (and including) the latest message the user wrote."""
    for index in reversed(range(len(messages))):
        message = messages[index]
        if isinstance(message, HumanMessage) and not is_nudge(message):
            return list(messages[index:])
    return []


def nudges_in_turn(messages: Sequence[BaseMessage]) -> int:
    """How many times this turn has been nudged already."""
    return sum(1 for message in _turn(messages) if is_nudge(message))


def queued_a_job(messages: Sequence[BaseMessage]) -> bool:
    """Whether this turn queued a background job: its work is running, so a reply that says so
    has done what the turn can do (reviewing it would send the agent back to work it does not
    have, and it would write the results it has not seen)."""
    return any(
        isinstance(message, ToolMessage) and is_queued_job(message.name, message.content)
        for message in _turn(messages)
    )


def _material(turn: Sequence[BaseMessage]) -> str | None:
    """The user's request and the reply under review, as material to judge."""
    reply = turn[-1] if turn else None
    if not isinstance(reply, AIMessage) or reply.tool_calls or not reply.text.strip():
        return None
    request = turn[0].text.strip()
    return f"<user_request>\n{request}\n</user_request>\n<reply>\n{reply.text.strip()}\n</reply>"


def _log_failure(error: Exception) -> None:
    """Log a failed check; a provider refusal carries an HTTP status and needs no traceback."""
    known = getattr(error, "status_code", None) is not None
    logger.warning(
        "completion check failed (%s); letting the reply stand",
        type(error).__name__,
        exc_info=not known,
    )


def judge(
    model: BaseChatModel,
    guard: CompletionGuard,
    messages: Sequence[BaseMessage],
    config: RunnableConfig,
) -> CompletionVerdict | None:
    """Ask the model whether the reply is complete; None when it cannot say.

    This fails open on purpose: an unjudged reply stands as the agent wrote it, which costs
    at most an answer that stopped early, whereas failing closed would nudge every reply.
    Any provider, network or parsing failure is expected here, so all are caught and logged.
    """
    material = _material(_turn(messages))
    if material is None:
        return None
    structured = model.with_structured_output(CompletionVerdict, include_raw=True)
    prompt = [SystemMessage(content=guard.classifier_prompt), HumanMessage(content=material)]
    try:
        result = cast(Mapping[str, object], structured.invoke(prompt, config))
    except Exception as error:  # fail open, see the docstring
        _log_failure(error)
        return None
    verdict = result.get("parsed")
    if not isinstance(verdict, CompletionVerdict):
        logger.warning("completion check gave no usable verdict; letting the reply stand")
        return None
    return verdict


class CompletionNode(Protocol):
    """The shape of a graph node that also receives the run configuration."""

    def __call__(self, state: AgentState, config: RunnableConfig) -> AgentState: ...


def build_completion_node(model: BaseChatModel, guard: CompletionGuard) -> CompletionNode:
    """The graph node: adds the nudge for a reply that stopped early, nothing otherwise."""

    def finish(state: AgentState, config: RunnableConfig) -> AgentState:
        messages = state["messages"]
        if nudges_in_turn(messages) >= guard.max_nudges or queued_a_job(messages):
            return {"messages": []}
        verdict = judge(model, guard, messages, config)
        if verdict is None or verdict.complete:
            return {"messages": []}
        logger.info("reply stopped early (%s); nudging the agent", verdict.reason)
        return {"messages": [HumanMessage(content=guard.nudge, name=NUDGE_NAME)]}

    return finish


def route_after_completion(state: AgentState) -> str:
    """Back to the agent after a nudge; otherwise the turn ends."""
    last = state["messages"][-1] if state["messages"] else None
    return "model" if last is not None and is_nudge(last) else END
