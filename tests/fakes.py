"""Shared test doubles that honour the real contracts (Liskov)."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Sequence
from typing import Any

from keyring.errors import KeyringError, PasswordDeleteError
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, UsageMetadata
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import PrivateAttr


class FakeCredentialStore:
    """In-memory stand-in for the ``keyring`` module; records every call.

    ``fail`` makes every call raise ``KeyringError``, like a missing OS backend.
    """

    def __init__(self, *, fail: bool = False) -> None:
        self.entries: dict[tuple[str, str], str] = {}
        self.calls: list[tuple[str, str, str]] = []
        self.fail = fail

    def _check(self, op: str, service: str, account: str) -> None:
        self.calls.append((op, service, account))
        if self.fail:
            raise KeyringError("no backend")

    def get_password(self, service_name: str, username: str) -> str | None:
        self._check("get", service_name, username)
        return self.entries.get((service_name, username))

    def set_password(self, service_name: str, username: str, password: str) -> None:
        self._check("set", service_name, username)
        self.entries[(service_name, username)] = password

    def delete_password(self, service_name: str, username: str) -> None:
        self._check("delete", service_name, username)
        if (service_name, username) not in self.entries:
            raise PasswordDeleteError("not found")
        del self.entries[(service_name, username)]


# Where the shipped settings keep each key (service, account), for tests that seed the store.
SERVICE = "epa-chemical-risk-agent"
OPENAI_ENTRY = (SERVICE, "openai_api_key")
CENSUS_ENTRY = (SERVICE, "census_api_key")
COMPTOX_ENTRY = (SERVICE, "comptox_api_key")


class ScriptedChatModel(BaseChatModel):
    """Answers each call with the next scripted ``AIMessage``, streaming it like a real model.

    Text streams word by word and tool calls as one ``tool_call_chunks`` chunk. Running out of
    script raises ``IndexError`` (a model failure). ``bind_tools`` returns the model itself.

    ``classifier`` scripts the answers of ``with_structured_output`` (one JSON verdict message
    per call, see ``verdict``); it is a model call like any other, so callbacks see it. ``inputs``
    records the messages of every call, and ``calls`` counts them.
    """

    _script: list[AIMessage] = PrivateAttr(default_factory=list[AIMessage])
    _cursor: int = PrivateAttr(default=0)
    _inputs: list[list[BaseMessage]] = PrivateAttr(default_factory=list[list[BaseMessage]])
    _classifier: ScriptedChatModel | None = PrivateAttr(default=None)

    def __init__(
        self,
        script: Sequence[AIMessage],
        classifier: Sequence[AIMessage] | None = None,
    ) -> None:
        super().__init__()
        self._script = list(script)
        if classifier is not None:
            self._classifier = ScriptedChatModel(classifier)

    @property
    def calls(self) -> int:
        """How many times this model was called."""
        return self._cursor

    @property
    def inputs(self) -> list[list[BaseMessage]]:
        """The messages of each call, in order."""
        return self._inputs

    @property
    def classifier(self) -> ScriptedChatModel:
        """The scripted classifier model (raises if none was given)."""
        if self._classifier is None:
            raise AssertionError("this model was built without a scripted classifier")
        return self._classifier

    def with_structured_output(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        schema: Any,
        *,
        include_raw: bool = False,
        **kwargs: Any,
    ) -> Runnable[Any, Any]:
        def parse(message: AIMessage) -> dict[str, Any]:
            try:
                return {
                    "raw": message,
                    "parsed": schema.model_validate_json(message.text),
                    "parsing_error": None,
                }
            except ValueError as error:
                return {"raw": message, "parsed": None, "parsing_error": error}

        return self.classifier | RunnableLambda(parse)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> ScriptedChatModel:
        return self

    def _next(self, messages: list[BaseMessage] | None = None) -> AIMessage:
        self._inputs.append(list(messages or []))
        message = self._script[self._cursor]
        self._cursor += 1
        return message

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._next(messages))])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        message = self._next(messages)
        for token in re.split(r"(\s)", message.text) if message.text else []:
            chunk = ChatGenerationChunk(message=AIMessageChunk(content=token, id=message.id))
            if run_manager:
                run_manager.on_llm_new_token(token, chunk=chunk)
            yield chunk
        yield from self._tool_and_usage_chunks(message)

    def _tool_and_usage_chunks(self, message: AIMessage) -> Iterator[ChatGenerationChunk]:
        if message.tool_calls:
            calls = [
                {"name": c["name"], "args": json.dumps(c["args"]), "id": c["id"], "index": i}
                for i, c in enumerate(message.tool_calls)
            ]
            yield ChatGenerationChunk(
                message=AIMessageChunk(content="", id=message.id, tool_call_chunks=calls),  # pyright: ignore[reportArgumentType]
            )
        if message.usage_metadata:
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    id=message.id,
                    usage_metadata=message.usage_metadata,
                ),
            )


def reply(text: str, input_tokens: int, output_tokens: int, cached: int = 0) -> AIMessage:
    """An answer that reports its token usage, as a provider does."""
    usage = UsageMetadata(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        input_token_details={"cache_read": cached},
    )
    return AIMessage(content=text, usage_metadata=usage)


def scripted(*texts: str) -> ScriptedChatModel:
    """A model that answers each call with the next text (no usage reported)."""
    return ScriptedChatModel([AIMessage(content=text) for text in texts])


def verdict(
    in_scope: bool,
    reply_text: str = "",
    usage: tuple[int, int] | None = None,
) -> AIMessage:
    """A scripted classifier answer: the JSON the scope check parses."""
    body = json.dumps({"in_scope": in_scope, "reply": reply_text})
    if usage is None:
        return AIMessage(content=body)
    return AIMessage(content=body, usage_metadata=reply(body, *usage).usage_metadata)


def completion_verdict(complete: bool, reason: str = "") -> AIMessage:
    """A scripted reviewer answer: the JSON the completion check parses."""
    return AIMessage(content=json.dumps({"complete": complete, "reason": reason}))
