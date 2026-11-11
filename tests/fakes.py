"""Shared test doubles that honour the real contracts (Liskov)."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from keyring.errors import KeyringError, PasswordDeleteError
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, UsageMetadata
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.runnables import Runnable, RunnableLambda
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import PrivateAttr

from api.schemas.workspace import WorkspaceState
from api.services.key_setup import KeyServices
from app.operator_keys import OperatorKeys
from app.usage_meter import CallUsage
from app.user_key_vault import (
    OPENAI_PURPOSE,
    KeyEncryptionKeys,
    UserKeyVault,
)
from commons.sealed_secret import kek_id, seal
from storage.keys import ThreadKey
from storage.turn_model import (
    OPEN_STATUSES,
    REASONED_STATUSES,
    PlannedInput,
    Turn,
    TurnStatus,
    TurnTransitionError,
    check_transition,
)
from storage.user_credentials import StoredCredential
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

    def _open(self, key: ThreadKey) -> Turn | None:
        return next(
            (t for t in self._turns.values() if t.key == key and t.status in OPEN_STATUSES),
            None,
        )

    def _mine(self, owner_id: UUID, turn_id: str) -> Turn | None:
        turn = self._turns.get(turn_id)
        return turn if turn is not None and turn.owner_id == owner_id else None

    def _set(self, turn: Turn, status: TurnStatus, reason: str | None, **extra: Any) -> Turn:
        now = self._clock()
        changes: dict[str, Any] = {"status": status, "reason": reason, "updated_at": now}
        if status is TurnStatus.RUNNING:
            changes |= {"started_at": turn.started_at or now, "finished_at": None}
            changes["heartbeat_at"] = now
        if status is TurnStatus.QUEUED:
            changes |= {"finished_at": None, "heartbeat_at": None, "cancel_requested": False}
        if status in (TurnStatus.COMPLETED, TurnStatus.FAILED):
            changes["finished_at"] = now
        self._turns[turn.id] = replace(turn, **changes, **extra)
        return self._turns[turn.id]

    async def begin(self, key: ThreadKey, planned: PlannedInput | None = None) -> Turn | None:
        if self._open(key) is not None:
            return None
        self._count += 1
        now = self._clock()
        turn = Turn(
            f"{self._count:032x}",
            key.owner_id,
            key.thread_id,
            TurnStatus.QUEUED,
            None,
            0,
            now,
            None,
            now,
            None,
            planned=planned,
        )
        self._turns[turn.id] = turn
        return turn

    async def resume(self, owner_id: UUID, turn_id: str, max_resumes: int) -> Turn | None:
        turn = self._mine(owner_id, turn_id)
        if turn is None or turn.status is not TurnStatus.INTERRUPTED:
            return None
        if turn.resume_count >= max_resumes or self._open(turn.key) is not None:
            return None
        return self._set(turn, TurnStatus.QUEUED, None, resume_count=turn.resume_count + 1)

    async def move(
        self,
        owner_id: UUID,
        turn_id: str,
        target: TurnStatus,
        reason: str | None = None,
    ) -> Turn:
        if (reason is not None) != (target in REASONED_STATUSES):
            raise ValueError(f"reason does not fit {target}")
        turn = self._mine(owner_id, turn_id)
        if turn is None:
            raise TurnTransitionError(f"turn {turn_id} does not exist")
        check_transition(turn_id, turn.status, target)
        return self._set(turn, target, reason)

    async def abandon(self, owner_id: UUID, turn_id: str, reason: str) -> bool:
        turn = self._mine(owner_id, turn_id)
        if turn is None or turn.status not in OPEN_STATUSES:
            return False
        self._set(turn, TurnStatus.INTERRUPTED, reason)
        return True

    async def interrupt_open(self, key: ThreadKey, reason: str) -> None:
        open_turn = self._open(key)
        if open_turn is not None:
            self._set(open_turn, TurnStatus.INTERRUPTED, reason)

    async def interrupt_all_open(self, reason: str) -> list[ThreadKey]:
        stale = [t for t in self._turns.values() if t.status in OPEN_STATUSES]
        for turn in stale:
            self._set(turn, TurnStatus.INTERRUPTED, reason)
        return [turn.key for turn in stale]

    async def latest(self, key: ThreadKey) -> Turn | None:
        return next((t for t in reversed(self._turns.values()) if t.key == key), None)

    async def get(self, owner_id: UUID, turn_id: str) -> Turn | None:
        return self._mine(owner_id, turn_id)

    async def start(self, owner_id: UUID, turn_id: str) -> Turn | None:
        turn = self._mine(owner_id, turn_id)
        if turn is None or turn.status is not TurnStatus.QUEUED:
            return None
        return self._set(turn, TurnStatus.RUNNING, None)

    async def heartbeat(self, owner_id: UUID, turn_id: str) -> bool:
        turn = self._mine(owner_id, turn_id)
        if turn is None or turn.status is not TurnStatus.RUNNING:
            return False
        self._turns[turn_id] = replace(turn, heartbeat_at=self._clock())
        return True

    async def request_cancel(self, owner_id: UUID, turn_id: str) -> bool:
        turn = self._mine(owner_id, turn_id)
        if turn is None or turn.status not in OPEN_STATUSES:
            return False
        self._turns[turn_id] = replace(turn, cancel_requested=True)
        return True

    async def cancel_requested(self, owner_id: UUID, turn_id: str) -> bool:
        turn = self._mine(owner_id, turn_id)
        return turn is not None and turn.cancel_requested

    async def interrupt_stale(
        self,
        older_than: timedelta,
        reason: str,
        key: ThreadKey | None = None,
    ) -> list[ThreadKey]:
        cutoff = self._clock() - older_than
        stale = [
            t
            for t in self._turns.values()
            if t.status is TurnStatus.RUNNING
            and (t.heartbeat_at or t.updated_at) < cutoff
            and (key is None or t.key == key)
        ]
        for turn in stale:
            self._set(turn, TurnStatus.INTERRUPTED, reason)
        return [turn.key for turn in stale]

    async def queue_position(self, turn_id: str) -> int:
        ids = list(self._turns)
        before = ids[: ids.index(turn_id)] if turn_id in ids else []
        return sum(1 for i in before if self._turns[i].status is TurnStatus.QUEUED)

    def forget(self, key: ThreadKey) -> None:
        """Delete the thread's turns (its thread was deleted)."""
        self._turns = {k: t for k, t in self._turns.items() if t.key != key}


@dataclass
class _ThreadRow:
    last_used_at: datetime
    busy_until: datetime | None = None


class InMemoryThreadStore:
    """The ``ThreadStore`` contract in process memory, for unit tests.

    Honours the same rules as ``storage.threads.PostgresThreadStore``: every artefact is stored
    under its ``ThreadKey`` (owner and thread id), a claim takes a lease that expires, a supplied
    value is never replaced and beats a decline, ``reset`` and ``purge_idle`` skip a running
    thread. ``clock`` lets a test move time.
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
        self._rows: dict[ThreadKey, _ThreadRow] = {}
        self._usage: dict[ThreadKey, list[tuple[str | None, CallUsage]]] = {}
        self._tool_messages: dict[ThreadKey, list[BaseMessage]] = {}
        self._workspaces: dict[ThreadKey, WorkspaceState] = {}
        self._pending: dict[ThreadKey, ConfirmationRequest] = {}
        self._answers: dict[ThreadKey, dict[str, float | None]] = {}

    def _row(self, key: ThreadKey) -> _ThreadRow:
        return self._rows.setdefault(key, _ThreadRow(self._clock()))

    def _busy(self, key: ThreadKey) -> bool:
        row = self._rows.get(key)
        return row is not None and row.busy_until is not None and row.busy_until > self._clock()

    async def claim(self, key: ThreadKey) -> bool:
        if self._busy(key):
            return False
        row = self._row(key)
        row.busy_until = self._clock() + self._lease
        row.last_used_at = self._clock()
        return True

    async def extend(self, key: ThreadKey) -> None:
        """Renew a held lease (the worker's heartbeat); an idle thread stays idle."""
        if self._busy(key):
            self._rows[key].busy_until = self._clock() + self._lease

    async def release(self, key: ThreadKey) -> None:
        if key in self._rows:
            self._rows[key].busy_until = None

    async def touch(self, key: ThreadKey) -> None:
        self._row(key).last_used_at = self._clock()

    async def holds(self, key: ThreadKey) -> bool:
        return key in self._rows

    async def latest_thread(self, owner_id: UUID) -> str | None:
        mine = sorted(
            (key.thread_id, row.last_used_at)
            for key, row in self._rows.items()
            if key.owner_id == owner_id
        )
        # Newest first, then the smallest id (as the PostgreSQL store orders them).
        return max(mine, key=lambda item: item[1])[0] if mine else None

    async def running(self, key: ThreadKey) -> bool:
        return self._busy(key)

    async def messages(self, key: ThreadKey) -> list[BaseMessage]:
        found = self.checkpointer.get_tuple({"configurable": {"thread_id": key.checkpoint_id}})
        if found is None:
            return []
        return list(found.checkpoint["channel_values"].get("messages", []))

    async def add_usage(
        self,
        key: ThreadKey,
        calls: Sequence[CallUsage],
        turn_id: str | None = None,
    ) -> None:
        self._row(key)
        self._usage.setdefault(key, []).extend((turn_id, call) for call in calls)

    async def session_calls(self, key: ThreadKey) -> list[CallUsage]:
        return [call for _, call in self._usage.get(key, [])]

    async def turn_calls(self, key: ThreadKey, turn_id: str) -> list[CallUsage]:
        return [call for owner, call in self._usage.get(key, []) if owner == turn_id]

    async def add_tool_messages(self, key: ThreadKey, messages: Sequence[BaseMessage]) -> None:
        self._row(key)
        self._tool_messages.setdefault(key, []).extend(messages)

    async def tool_messages(self, key: ThreadKey) -> list[BaseMessage]:
        return list(self._tool_messages.get(key, []))

    async def workspace(self, key: ThreadKey) -> WorkspaceState | None:
        return self._workspaces.get(key)

    async def set_workspace(self, key: ThreadKey, state: WorkspaceState) -> None:
        self._row(key)
        self._workspaces[key] = state

    async def pending(self, key: ThreadKey) -> ConfirmationRequest | None:
        return self._pending.get(key)

    async def set_pending(self, key: ThreadKey, request: ConfirmationRequest | None) -> None:
        if request is None:
            self._pending.pop(key, None)
            return
        self._row(key)
        self._pending[key] = request

    async def answers(self, key: ThreadKey) -> tuple[dict[str, float], frozenset[str]]:
        stored = self._answers.get(key, {})
        supplied = {name: value for name, value in stored.items() if value is not None}
        return supplied, frozenset(name for name, value in stored.items() if value is None)

    async def record_answers(
        self,
        key: ThreadKey,
        supplied: Mapping[str, float],
        declined: Iterable[str],
    ) -> None:
        self._row(key)
        stored = self._answers.setdefault(key, {})
        for name in declined:
            stored.setdefault(name, None)
        for name, value in supplied.items():
            if stored.get(name) is None:
                stored[name] = value

    def _forget(self, key: ThreadKey) -> None:
        self.checkpointer.delete_thread(key.checkpoint_id)
        self.turns.forget(key)
        for table in (self._rows, self._usage, self._tool_messages, self._workspaces):
            table.pop(key, None)
        self._pending.pop(key, None)
        self._answers.pop(key, None)

    async def reset(self, key: ThreadKey) -> bool:
        if self._busy(key):
            return False
        self._forget(key)
        return True

    async def purge_idle(self, older_than: timedelta) -> list[ThreadKey]:
        cutoff = self._clock() - older_than
        stale = [
            k for k, row in self._rows.items() if row.last_used_at < cutoff and not self._busy(k)
        ]
        for key in stale:
            self._forget(key)
        return stale

    async def forget_owner(self, owner_id: UUID) -> int:
        owned = [key for key in self._rows if key.owner_id == owner_id]
        for key in owned:
            self._forget(key)
        return len(owned)


class InMemorySealedStore:
    """In-memory ``SealedCredentialStore``: the ``user_credentials`` table without PostgreSQL."""

    def __init__(self) -> None:
        self.rows: dict[tuple[UUID, str], StoredCredential] = {}

    async def get(self, user_id: UUID, purpose: str) -> StoredCredential | None:
        return self.rows.get((user_id, purpose))

    async def put(self, credential: StoredCredential) -> None:
        self.rows[(credential.user_id, credential.purpose)] = credential

    async def delete(self, user_id: UUID, purpose: str) -> None:
        self.rows.pop((user_id, purpose), None)

    async def replace_if_sealed_by(self, credential: StoredCredential, old_kek_id: str) -> bool:
        current = self.rows.get((credential.user_id, credential.purpose))
        if current is None or current.kek_id != old_kek_id:
            return False
        self.rows[(credential.user_id, credential.purpose)] = credential
        return True

    async def unsealed_by_other_keys(
        self,
        current_kek_id: str,
        limit: int,
        after: tuple[UUID, str] | None = None,
    ) -> list[StoredCredential]:
        rows = sorted(
            (row for row in self.rows.values() if row.kek_id != current_kek_id),
            key=lambda row: (row.user_id, row.purpose),
        )
        return [r for r in rows if after is None or (r.user_id, r.purpose) > after][:limit]

    async def count_sealed_by(self, kek_id: str) -> int:
        return sum(1 for row in self.rows.values() if row.kek_id == kek_id)


TEST_KEK = bytes(range(32))
OWNER_ID = UUID(int=1)  # the id the in-memory account store gives its first account


class KeyBench:
    """The key services over an in-memory sealed store: a real ``UserKeyVault`` with a test KEK.

    ``give`` seals a user's key straight into the store (the default signed-in test user is
    ``OWNER_ID``), so a test starts "with a key saved" without going through a route.
    """

    def __init__(self, operator: OperatorKeys | None = None) -> None:
        self.rows = InMemorySealedStore()
        self.vault = UserKeyVault(self.rows, KeyEncryptionKeys(TEST_KEK), max_length=200)
        self.operator = operator or OperatorKeys()
        self.services = KeyServices(self.vault, self.operator)

    def give(self, key: str, user_id: UUID = OWNER_ID) -> None:
        """Store ``key`` as ``user_id``'s sealed OpenAI key."""
        nonce, ciphertext = seal(TEST_KEK, key, f"ecofate:{OPENAI_PURPOSE}:{user_id}".encode())
        row = StoredCredential(user_id, OPENAI_PURPOSE, nonce, ciphertext, kek_id(TEST_KEK))
        self.rows.rows[(user_id, OPENAI_PURPOSE)] = row
