"""Shared test doubles that honour the real contracts (Liskov)."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from keyring.errors import KeyringError, PasswordDeleteError
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, UsageMetadata
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.runnables import Runnable, RunnableLambda
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import PrivateAttr

from api.schemas.workspace import WorkspaceState
from app.usage_meter import CallUsage
from storage.turn_model import (
    OPEN_STATUSES,
    REASONED_STATUSES,
    Turn,
    TurnStatus,
    TurnTransitionError,
    check_transition,
)
from tools.schemas import ConfirmationRequest


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


def _utc_now() -> datetime:
    return datetime.now(UTC)


class InMemoryTurnStore:
    """The ``TurnStore`` contract in process memory (same moves and refusals as PostgreSQL)."""

    def __init__(self, clock: Callable[[], datetime] = _utc_now) -> None:
        self._clock = clock
        self._turns: dict[str, Turn] = {}  # in creation order
        self._count = 0

    def _open(self, thread_id: str) -> Turn | None:
        return next(
            (
                t
                for t in self._turns.values()
                if t.thread_id == thread_id and t.status in OPEN_STATUSES
            ),
            None,
        )

    def _set(self, turn: Turn, status: TurnStatus, reason: str | None, **extra: Any) -> Turn:
        now = self._clock()
        changes: dict[str, Any] = {"status": status, "reason": reason, "updated_at": now}
        if status is TurnStatus.RUNNING:
            changes |= {"started_at": turn.started_at or now, "finished_at": None}
        if status in (TurnStatus.COMPLETED, TurnStatus.FAILED):
            changes["finished_at"] = now
        self._turns[turn.id] = replace(turn, **changes, **extra)
        return self._turns[turn.id]

    async def begin(self, thread_id: str) -> Turn | None:
        if self._open(thread_id) is not None:
            return None
        self._count += 1
        now = self._clock()
        turn = Turn(
            f"turn-{self._count}",
            thread_id,
            TurnStatus.RUNNING,
            None,
            0,
            now,
            now,
            now,
            None,
        )
        self._turns[turn.id] = turn
        return turn

    async def resume(self, turn_id: str, max_resumes: int) -> Turn | None:
        turn = self._turns.get(turn_id)
        if turn is None or turn.status is not TurnStatus.INTERRUPTED:
            return None
        if turn.resume_count >= max_resumes or self._open(turn.thread_id) is not None:
            return None
        return self._set(turn, TurnStatus.RUNNING, None, resume_count=turn.resume_count + 1)

    async def move(self, turn_id: str, target: TurnStatus, reason: str | None = None) -> Turn:
        if (reason is not None) != (target in REASONED_STATUSES):
            raise ValueError(f"reason does not fit {target}")
        turn = self._turns.get(turn_id)
        if turn is None:
            raise TurnTransitionError(f"turn {turn_id} does not exist")
        check_transition(turn_id, turn.status, target)
        return self._set(turn, target, reason)

    async def abandon(self, turn_id: str, reason: str) -> bool:
        turn = self._turns.get(turn_id)
        if turn is None or turn.status not in OPEN_STATUSES:
            return False
        self._set(turn, TurnStatus.INTERRUPTED, reason)
        return True

    async def interrupt_open(self, reason: str, thread_id: str | None = None) -> list[str]:
        stale = [
            t
            for t in self._turns.values()
            if t.status in OPEN_STATUSES and thread_id in (None, t.thread_id)
        ]
        for turn in stale:
            self._set(turn, TurnStatus.INTERRUPTED, reason)
        return [turn.thread_id for turn in stale]

    async def latest(self, thread_id: str) -> Turn | None:
        return next((t for t in reversed(self._turns.values()) if t.thread_id == thread_id), None)

    def forget(self, thread_id: str) -> None:
        """Delete the thread's turns (its thread was deleted)."""
        self._turns = {k: t for k, t in self._turns.items() if t.thread_id != thread_id}


@dataclass
class _ThreadRow:
    last_used_at: datetime
    busy_until: datetime | None = None


class InMemoryThreadStore:
    """The ``ThreadStore`` contract in process memory, for unit tests.

    Honours the same rules as ``storage.threads.PostgresThreadStore``: a claim takes a lease
    that expires, a supplied value is never replaced and beats a decline, ``reset`` and
    ``purge_idle`` skip a running thread. ``clock`` lets a test move time.
    """

    def __init__(
        self,
        *,
        lease: timedelta = timedelta(minutes=10),
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.checkpointer = InMemorySaver()
        self.turns = InMemoryTurnStore(clock)
        self._lease = lease
        self._clock = clock
        self._rows: dict[str, _ThreadRow] = {}
        self._usage: dict[str, list[tuple[str | None, CallUsage]]] = {}
        self._tool_messages: dict[str, list[BaseMessage]] = {}
        self._workspaces: dict[str, WorkspaceState] = {}
        self._pending: dict[str, ConfirmationRequest] = {}
        self._answers: dict[str, dict[str, float | None]] = {}

    def _row(self, thread_id: str) -> _ThreadRow:
        return self._rows.setdefault(thread_id, _ThreadRow(self._clock()))

    def _busy(self, thread_id: str) -> bool:
        row = self._rows.get(thread_id)
        return row is not None and row.busy_until is not None and row.busy_until > self._clock()

    async def claim(self, thread_id: str) -> bool:
        if self._busy(thread_id):
            return False
        row = self._row(thread_id)
        row.busy_until = self._clock() + self._lease
        row.last_used_at = self._clock()
        return True

    async def release(self, thread_id: str) -> None:
        if thread_id in self._rows:
            self._rows[thread_id].busy_until = None

    async def touch(self, thread_id: str) -> None:
        self._row(thread_id).last_used_at = self._clock()

    async def holds(self, thread_id: str) -> bool:
        return thread_id in self._rows

    async def running(self, thread_id: str) -> bool:
        return self._busy(thread_id)

    async def messages(self, thread_id: str) -> list[BaseMessage]:
        found = self.checkpointer.get_tuple({"configurable": {"thread_id": thread_id}})
        if found is None:
            return []
        return list(found.checkpoint["channel_values"].get("messages", []))

    async def add_usage(
        self,
        thread_id: str,
        calls: Sequence[CallUsage],
        turn_id: str | None = None,
    ) -> None:
        self._row(thread_id)
        self._usage.setdefault(thread_id, []).extend((turn_id, call) for call in calls)

    async def session_calls(self, thread_id: str) -> list[CallUsage]:
        return [call for _, call in self._usage.get(thread_id, [])]

    async def turn_calls(self, thread_id: str, turn_id: str) -> list[CallUsage]:
        return [call for owner, call in self._usage.get(thread_id, []) if owner == turn_id]

    async def add_tool_messages(self, thread_id: str, messages: Sequence[BaseMessage]) -> None:
        self._row(thread_id)
        self._tool_messages.setdefault(thread_id, []).extend(messages)

    async def tool_messages(self, thread_id: str) -> list[BaseMessage]:
        return list(self._tool_messages.get(thread_id, []))

    async def workspace(self, thread_id: str) -> WorkspaceState | None:
        return self._workspaces.get(thread_id)

    async def set_workspace(self, thread_id: str, state: WorkspaceState) -> None:
        self._row(thread_id)
        self._workspaces[thread_id] = state

    async def pending(self, thread_id: str) -> ConfirmationRequest | None:
        return self._pending.get(thread_id)

    async def set_pending(self, thread_id: str, request: ConfirmationRequest | None) -> None:
        if request is None:
            self._pending.pop(thread_id, None)
            return
        self._row(thread_id)
        self._pending[thread_id] = request

    async def answers(self, thread_id: str) -> tuple[dict[str, float], frozenset[str]]:
        stored = self._answers.get(thread_id, {})
        supplied = {key: value for key, value in stored.items() if value is not None}
        return supplied, frozenset(key for key, value in stored.items() if value is None)

    async def record_answers(
        self,
        thread_id: str,
        supplied: Mapping[str, float],
        declined: Iterable[str],
    ) -> None:
        self._row(thread_id)
        stored = self._answers.setdefault(thread_id, {})
        for key in declined:
            stored.setdefault(key, None)
        for key, value in supplied.items():
            if stored.get(key) is None:
                stored[key] = value

    def _forget(self, thread_id: str) -> None:
        self.checkpointer.delete_thread(thread_id)
        self.turns.forget(thread_id)
        for table in (self._rows, self._usage, self._tool_messages, self._workspaces):
            table.pop(thread_id, None)
        self._pending.pop(thread_id, None)
        self._answers.pop(thread_id, None)

    async def reset(self, thread_id: str) -> bool:
        if self._busy(thread_id):
            return False
        self._forget(thread_id)
        return True

    async def purge_idle(self, older_than: timedelta) -> list[str]:
        cutoff = self._clock() - older_than
        stale = [
            t for t, row in self._rows.items() if row.last_used_at < cutoff and not self._busy(t)
        ]
        for thread_id in stale:
            self._forget(thread_id)
        return stale
