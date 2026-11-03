"""Scope guardrail: a model-based check, before the tool-bound agent, that a request is on topic.

An opt-in node of the agent graph. The injected chat model classifies the latest user turn,
judged in the light of a short window of the conversation, as in or out of scope. Off-topic turns
get a short, warm redirect and end there: the tool-bound model is not called and no tool runs.
The module never imports a provider package; the model is injected.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, cast

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END
from pydantic import BaseModel

from agent.completion import is_nudge
from agent.state import AgentState

logger = logging.getLogger(__name__)
REDIRECT_NAME = "scope_redirect"  # the name carried by the redirect message


class ScopeVerdict(BaseModel):
    """The classifier's answer: whether the turn is in scope and, if not, the reply to show."""

    in_scope: bool
    reply: str


@dataclass(frozen=True)
class ScopeGuard:
    """What the scope check needs besides the model.

    Attributes:
        classifier_prompt: System prompt of the classifier.
        fallback_reply: Redirect shown when the classifier gives none.
        history_window: Earlier messages the classifier sees besides the latest user message.
    """

    classifier_prompt: str
    fallback_reply: str
    history_window: int = 6


def _speaker(message: BaseMessage) -> str | None:
    if is_nudge(message):
        return None  # the completion guardrail's own words, not the user's
    if isinstance(message, HumanMessage):
        return "User"
    return "Assistant" if isinstance(message, AIMessage) else None


def _latest_user(messages: Sequence[BaseMessage]) -> int | None:
    """Index of the latest message the user wrote (a nudge is not one)."""
    for index in reversed(range(len(messages))):
        message = messages[index]
        if isinstance(message, HumanMessage) and not is_nudge(message):
            return index
    return None


def _conversation(messages: Sequence[BaseMessage], window: int) -> str | None:
    """The window of earlier turns and the latest user message, as material to judge."""
    latest = _latest_user(messages)
    if latest is None:
        return None
    lines = [
        f"{_speaker(m)}: {m.text.strip()}"
        for m in messages[:latest]
        if _speaker(m) and m.text.strip()
    ]
    earlier = lines[-window:] if window > 0 else []
    return (
        "<conversation>\n"
        + "\n".join(earlier)
        + "\n</conversation>\n<latest_user_message>\n"
        + messages[latest].text.strip()
        + "\n</latest_user_message>"
    )


def _log_failure(error: Exception) -> None:
    """Log a failed scope check; a provider refusal (no credits, bad key) carries an HTTP status
    and is reported by the agent that follows, so it needs no traceback here."""
    known = getattr(error, "status_code", None) is not None
    logger.warning(
        "scope check failed (%s); letting the turn through",
        type(error).__name__,
        exc_info=not known,
    )


def classify(
    model: BaseChatModel,
    guard: ScopeGuard,
    messages: Sequence[BaseMessage],
    config: RunnableConfig,
) -> ScopeVerdict | None:
    """Ask the model for a verdict on the latest turn; None when it cannot give a usable one.

    This fails open on purpose (the one deliberate exception to failing closed here): the agent
    that follows stays bound to its tools and system prompt, so a classifier error costs at
    most one unneeded agent run, whereas failing closed would refuse legitimate assessments.
    Any provider, network or parsing failure is expected here, so all are caught and logged.
    """
    material = _conversation(messages, guard.history_window)
    if material is None:
        return None
    structured = model.with_structured_output(ScopeVerdict, include_raw=True)
    prompt = [SystemMessage(content=guard.classifier_prompt), HumanMessage(content=material)]
    try:
        result = cast(Mapping[str, object], structured.invoke(prompt, config))
    except Exception as error:  # fail open, see the docstring
        _log_failure(error)
        return None
    verdict = result.get("parsed")
    if not isinstance(verdict, ScopeVerdict):
        logger.warning("scope check gave no usable verdict; letting the turn through")
        return None
    return verdict


class ScopeNode(Protocol):
    """The shape of a graph node that also receives the run configuration."""

    def __call__(self, state: AgentState, config: RunnableConfig) -> AgentState: ...


def build_scope_node(model: BaseChatModel, guard: ScopeGuard) -> ScopeNode:
    """The graph node: adds the redirect message for an off-topic turn, nothing otherwise."""

    def scope(state: AgentState, config: RunnableConfig) -> AgentState:
        verdict = classify(model, guard, state["messages"], config)
        if verdict is None or verdict.in_scope:
            return {"messages": []}
        reply = verdict.reply.strip() or guard.fallback_reply.strip()
        return {"messages": [AIMessage(content=reply, name=REDIRECT_NAME)]}

    return scope


def route_after_scope(state: AgentState) -> str:
    """End after a redirect; otherwise continue to the agent."""
    last = state["messages"][-1] if state["messages"] else None
    redirected = isinstance(last, AIMessage) and last.name == REDIRECT_NAME
    return END if redirected else "model"
