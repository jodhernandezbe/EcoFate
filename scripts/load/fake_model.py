"""A scripted chat model for the load test: it calls no provider and costs nothing.

It plays the agent's part in the load test's conversation, deciding from the last message only:
a request to assess calls ``assess_facilities`` (with the recorded arguments), a status question
calls ``check_job_status``, and any other message, or a tool result, gets a short reply. Every
call waits ``model_seconds`` first, the recorded latency of one model call. The scope and
completion checks get a passing verdict, so every turn runs the agent. Load test only: it is
installed by ``scripts.load.celery_app`` and never registered as a provider.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from typing import cast

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable, RunnableLambda
from langchain_core.tools import BaseTool
from pydantic import BaseModel

ASSESS = "assess_facilities"
STATUS = "check_job_status"
ASSESS_WORDS = ("assess", "risk")
STATUS_WORDS = ("status", "finished", "done yet", "how is it going")
STARTED_REPLY = "The assessment has started in the background. I will explain it when it ends."
RUNNING_REPLY = "The assessment is still running; I can answer other questions meanwhile."
RESULT_REPLY = "The assessment has ended. Here is what it found, facility by facility."
ANSWER_REPLY = "Screening-level means a conservative first look, not a full risk assessment."


def _text(message: BaseMessage) -> str:
    content = message.content
    return content if isinstance(content, str) else json.dumps(content)


def _call(name: str, args: Mapping[str, object]) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": dict(args), "id": f"call_{uuid.uuid4().hex[:24]}"}],
    )


def _after_tool(message: ToolMessage) -> AIMessage:
    """The reply to a tool result: started, still running, or the ended job explained."""
    text = _text(message)
    if message.name == STATUS:
        return AIMessage(content=RUNNING_REPLY)
    if '"queued"' in text and "position" in text:
        return AIMessage(content=STARTED_REPLY)
    return AIMessage(content=RESULT_REPLY)


def scripted_reply(messages: Sequence[BaseMessage], assess_args: Mapping[str, object]) -> AIMessage:
    """The agent's next message for the conversation so far (pure, no waiting)."""
    last = messages[-1] if messages else HumanMessage(content="")
    if isinstance(last, ToolMessage):
        return _after_tool(last)
    asked = _text(last).lower()
    if any(word in asked for word in STATUS_WORDS):
        return _call(STATUS, {})
    if any(word in asked for word in ASSESS_WORDS):
        return _call(ASSESS, assess_args)
    return AIMessage(content=ANSWER_REPLY)


def passing_verdict(schema: type[BaseModel]) -> BaseModel:
    """A verdict of ``schema`` that lets the turn through: every bool True, every str a note."""
    values: dict[str, object] = {}
    for name, field in schema.model_fields.items():
        values[name] = True if field.annotation is bool else "load test"
    return schema.model_validate(values)


class ScriptedChatModel(BaseChatModel):
    """The load test's agent model (see the module docstring)."""

    model_seconds: float = 2.0
    assess_args: dict[str, object] = {}

    @property
    def _llm_type(self) -> str:
        return "load-test-scripted"

    def _result(self, messages: list[BaseMessage]) -> ChatResult:
        reply = scripted_reply(messages, self.assess_args)
        return ChatResult(generations=[ChatGeneration(message=reply)])

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: object,
    ) -> ChatResult:
        time.sleep(self.model_seconds)
        return self._result(messages)

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: object,
    ) -> ChatResult:
        await asyncio.sleep(self.model_seconds)
        return self._result(messages)

    def bind_tools(
        self,
        tools: Sequence[Mapping[str, object] | type | Callable[..., object] | BaseTool],
        *,
        tool_choice: str | None = None,
        **kwargs: object,
    ) -> Runnable[LanguageModelInput, AIMessage]:
        """The script already knows the tools it calls, so binding changes nothing."""
        return cast(Runnable[LanguageModelInput, AIMessage], self)

    def with_structured_output(  # type: ignore[override]  # the guards' one call shape only
        self,
        schema: object,
        *,
        include_raw: bool = False,
        **kwargs: object,
    ) -> Runnable[LanguageModelInput, object]:
        """A passing verdict for the scope and completion checks, after one model latency."""
        verdict_type = cast(type[BaseModel], schema)

        def verdict(_: LanguageModelInput) -> object:
            time.sleep(self.model_seconds)
            parsed = passing_verdict(verdict_type)
            if not include_raw:
                return parsed
            return {"raw": AIMessage(content=""), "parsed": parsed, "parsing_error": None}

        return RunnableLambda(verdict)
