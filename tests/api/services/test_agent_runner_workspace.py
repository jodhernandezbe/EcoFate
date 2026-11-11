"""The workspace is rebuilt and streamed after each batch of tool results."""

from __future__ import annotations

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolCall
from langchain_core.tools import StructuredTool, ToolException

from api.schemas.chat import ChatRequest, StreamEvent, WorkspaceUpdate
from api.services.agent_runner import AgentRuntime
from api.services.key_setup import turn_key_loader
from api.services.threads import ThreadStore
from tests.api.keys import OWNER, owned
from tests.api.services.projectors.factories import RULES, record
from tests.api.streams import begun_turn
from tests.fakes import InMemoryThreadStore, KeyBench, ScriptedChatModel

pytestmark = pytest.mark.anyio


def _inventory(cas_number: str) -> tuple[dict[str, object], list[dict[str, object]]]:
    """The model is shown one facility; the workspace gets both."""
    every = [record("A"), record("B", lat=30.0)]
    shown: dict[str, object] = {
        "total_found": 2,
        "matching": 2,
        "shown": 1,
        "facilities": every[:1],
        "note": "partial",
    }
    return shown, every


def _broken(cas_number: str) -> str:
    raise ToolException("the service said no")


INVENTORY = StructuredTool.from_function(
    _inventory,
    name="query_emissions_inventory",
    description="Synthetic inventory.",
    response_format="content_and_artifact",
)
BROKEN = StructuredTool.from_function(
    _broken,
    name="get_population_receptors",
    description="Fails.",
    handle_tool_error=True,
)


def _model(*names: str) -> BaseChatModel:
    calls = [
        ToolCall(name=n, args={"cas_number": "1-1-1"}, id=f"c{i}") for i, n in enumerate(names)
    ]
    return ScriptedChatModel([AIMessage(content="", tool_calls=calls), AIMessage(content="done")])


async def _turn(
    monkeypatch: pytest.MonkeyPatch,
    model: BaseChatModel,
    threads: ThreadStore,
    *,
    with_rules: bool = True,
) -> list[StreamEvent]:
    monkeypatch.setattr("agent.graph.get_all_tools", lambda: [INVENTORY, BROKEN])
    bench = KeyBench()
    bench.give("sk-proj-" + "w1X2y3Z4a5" * 3)  # pragma: allowlist secret
    runtime = AgentRuntime(lambda key: model, 10, workspace_rules=RULES if with_rules else None)
    run = begun_turn(
        ChatRequest(thread_id="t1", message="go"),
        keys=turn_key_loader(bench.services, OWNER),
        threads=threads,
        runtime=runtime,
    )
    return [event async for event in run]


def _updates(events: list[StreamEvent]) -> list[WorkspaceUpdate]:
    return [e for e in events if isinstance(e, WorkspaceUpdate)]


async def test_a_workspace_update_follows_the_tool_results(monkeypatch: pytest.MonkeyPatch) -> None:
    events = await _turn(monkeypatch, _model("query_emissions_inventory"), InMemoryThreadStore())
    (update,) = _updates(events)
    assert [f.frs_id for f in update.state.facilities] == ["A", "B"]
    assert update.state.framing_version == 1
    kinds = [e.type for e in events]
    assert (
        kinds.index("tool_status")
        < kinds.index("workspace_update")
        < kinds.index("assistant_message")
    )
    seqs = [e.seq for e in events]
    assert seqs == sorted(set(seqs))  # strictly increasing


async def test_the_workspace_is_kept_for_the_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    threads = InMemoryThreadStore()
    await _turn(monkeypatch, _model("query_emissions_inventory"), threads)
    kept = await threads.workspace(owned("t1"))
    assert kept is not None and len(kept.facilities) == 2
    assert len(await threads.tool_messages(owned("t1"))) == 2
    assert await threads.reset(owned("t1"))
    assert (
        await threads.workspace(owned("t1")) is None
        and await threads.tool_messages(owned("t1")) == []
    )


async def test_a_failed_tool_changes_nothing_and_sends_no_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = await _turn(monkeypatch, _model("get_population_receptors"), InMemoryThreadStore())
    assert all(e.state.facilities == [] for e in _updates(events))
    assert len(_updates(events)) <= 1


async def test_without_workspace_rules_no_update_is_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    events = await _turn(
        monkeypatch,
        _model("query_emissions_inventory"),
        InMemoryThreadStore(),
        with_rules=False,
    )
    assert _updates(events) == []


async def test_a_batch_of_parallel_tools_sends_one_update(monkeypatch: pytest.MonkeyPatch) -> None:
    events = await _turn(
        monkeypatch,
        _model("query_emissions_inventory", "get_population_receptors"),
        InMemoryThreadStore(),
    )
    assert len(_updates(events)) == 1
