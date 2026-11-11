"""The presenter's own store failures end the turn like any failure: error, usage, finished."""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from langchain_core.messages import AIMessage, BaseMessage, ToolCall
from langchain_core.tools import tool

from api.schemas.chat import ChatRequest, ErrorEvent
from api.services.agent_runner import AgentRuntime
from api.services.key_setup import turn_key_loader
from storage.keys import ThreadKey
from tests.api.keys import OWNER
from tests.api.services.projectors.factories import RULES
from tests.api.streams import begun_turn
from tests.fakes import InMemoryThreadStore, KeyBench, ScriptedChatModel

pytestmark = pytest.mark.anyio
KEY = "sk-proj-" + "p1R2e3S4n5" * 3  # pragma: allowlist secret


@tool
def lookup(cas_number: str) -> str:
    """Look up a CAS number."""
    return "found"


class _ToolStoreDown(InMemoryThreadStore):
    """A store whose database stops answering when the turn keeps its tool messages."""

    async def add_tool_messages(self, key: ThreadKey, messages: Sequence[BaseMessage]) -> None:
        raise OSError("connection to the database refused")


async def test_a_store_failure_while_presenting_is_the_turns_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("agent.graph.get_all_tools", lambda: [lookup])
    call = AIMessage(
        content="",
        tool_calls=[ToolCall(name="lookup", args={"cas_number": "1"}, id="c")],
    )
    model = ScriptedChatModel([call, AIMessage(content="never")])
    bench = KeyBench()
    bench.give(KEY)
    run = begun_turn(
        ChatRequest(thread_id="p1", message="go"),
        keys=turn_key_loader(bench.services, OWNER),
        threads=_ToolStoreDown(),
        runtime=AgentRuntime(lambda key: model, 10, workspace_rules=RULES),
    )
    events = [event async for event in run]
    assert [e.type for e in events][-3:] == ["error", "usage", "turn_finished"]
    error = events[-3]
    assert isinstance(error, ErrorEvent) and "refused" not in error.message
    assert [e.seq for e in events] == list(range(len(events)))
