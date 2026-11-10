"""Two users, every thread route crosswise: a foreign thread id behaves like an unknown one."""

from __future__ import annotations

import ast
import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.dependencies import AgentRuntime, get_runtime
from storage.keys import ThreadKey
from tests.api.conftest import ORIGIN, make_user, signed_in
from tests.api.streams import parse_sse
from tests.fakes import OPENAI_ENTRY, FakeCredentialStore, scripted

OWN = {"Origin": ORIGIN}
CHAT = "/api/v1/chat"
KEY = "sk-proj-" + "i5S6o7L8a9" * 3  # pragma: allowlist secret


@pytest.fixture
def two(app: FastAPI, store: FakeCredentialStore) -> Iterator[tuple[TestClient, TestClient]]:
    store.entries[OPENAI_ENTRY] = KEY
    model = scripted(*["an answer"] * 8)
    app.dependency_overrides[get_runtime] = lambda: AgentRuntime(lambda key: model, 10)
    with (
        signed_in(app, email="ana@example.com", raise_server_exceptions=False) as ana,
        signed_in(app, email="bo@example.com", raise_server_exceptions=False) as bo,
    ):
        yield ana, bo


def _say(client: TestClient, thread: str, message: str) -> Any:
    body = {"thread_id": thread, "message": message}
    response = client.post(f"{CHAT}/stream", json=body, headers=OWN)
    assert response.status_code == 200
    return parse_sse(response.text)


def _same_answer(foreign: Any, unknown: Any) -> None:
    assert foreign.status_code == unknown.status_code
    assert foreign.json()["error"] == unknown.json()["error"]
    assert set(foreign.json()) == set(unknown.json()) == {"error", "correlation_id"}


def test_reading_another_users_thread_is_the_404_of_an_unknown_thread(
    two: tuple[TestClient, TestClient],
) -> None:
    ana, bo = two
    _say(ana, "t1", "hello from ana")
    _same_answer(bo.get(f"{CHAT}/threads/t1"), bo.get(f"{CHAT}/threads/never-seen"))
    assert bo.get(f"{CHAT}/threads/t1").status_code == 404


def test_the_report_of_another_users_thread_is_404_and_builds_nothing(
    two: tuple[TestClient, TestClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ana, bo = two
    _say(ana, "t1", "hello from ana")
    built: list[int] = []

    def refuse(*_args: object, **_kwargs: object) -> bytes:
        built.append(1)
        return b""

    monkeypatch.setattr("api.services.report.service.build_report", refuse)
    foreign = bo.get(f"{CHAT}/threads/t1/report")
    _same_answer(foreign, bo.get(f"{CHAT}/threads/never-seen/report"))
    assert foreign.status_code == 404 and built == []


def test_resetting_another_users_thread_is_404_and_leaves_it_alone(
    two: tuple[TestClient, TestClient],
) -> None:
    ana, bo = two
    _say(ana, "t1", "hello from ana")
    foreign = bo.delete(f"{CHAT}/threads/t1", headers=OWN)
    _same_answer(foreign, bo.delete(f"{CHAT}/threads/never-seen", headers=OWN))
    assert foreign.status_code == 404
    assert ana.get(f"{CHAT}/threads/t1").json()["messages"][0]["text"] == "hello from ana"


def test_resuming_another_users_thread_is_404(two: tuple[TestClient, TestClient]) -> None:
    ana, bo = two
    _say(ana, "t1", "hello from ana")
    foreign = bo.post(f"{CHAT}/threads/t1/resume", headers=OWN)
    _same_answer(foreign, bo.post(f"{CHAT}/threads/never-seen/resume", headers=OWN))
    assert foreign.status_code == 404


def test_answering_a_confirmation_of_another_users_thread_is_the_409_of_an_unknown_one(
    two: tuple[TestClient, TestClient],
) -> None:
    ana, bo = two
    _say(ana, "t1", "hello from ana")
    answers = {"request_id": "r1", "entries": [{"entry_id": "rfc:x", "decision": "decline"}]}

    def reply(thread: str) -> Any:
        body = {"thread_id": thread, "answers": answers}
        return bo.post(f"{CHAT}/stream", json=body, headers=OWN)

    _same_answer(reply("t1"), reply("never-seen"))
    assert reply("t1").status_code == 409


def test_a_facility_of_another_users_thread_is_404(two: tuple[TestClient, TestClient]) -> None:
    ana, bo = two
    _say(ana, "t1", "hello from ana")
    foreign = bo.get("/api/v1/facilities/A?thread_id=t1")
    _same_answer(foreign, bo.get("/api/v1/facilities/A?thread_id=never-seen"))
    assert foreign.status_code == 404


def test_the_same_thread_id_of_two_users_stays_separate(two: tuple[TestClient, TestClient]) -> None:
    ana, bo = two
    _say(ana, "t1", "hello from ana")
    _say(bo, "t1", "hello from bo")
    ana_says = [m["text"] for m in ana.get(f"{CHAT}/threads/t1").json()["messages"]]
    bo_says = [m["text"] for m in bo.get(f"{CHAT}/threads/t1").json()["messages"]]
    assert ana_says[0] == "hello from ana" and bo_says[0] == "hello from bo"
    assert "hello from bo" not in ana_says and "hello from ana" not in bo_says


def test_a_user_cannot_pick_another_owner_through_the_request(
    app: FastAPI,
    two: tuple[TestClient, TestClient],
) -> None:
    ana, bo = two
    me = ana.get("/api/v1/auth/me").json()
    body = {"thread_id": "t1", "message": "hi", "owner_id": me["id"]}
    assert bo.post(f"{CHAT}/stream", json=body, headers=OWN).status_code == 422  # unknown field
    assert not asyncio.run(app.state.threads.holds(ThreadKey(UUID(me["id"]), "t1")))


def test_both_users_can_run_a_turn_on_the_same_thread_id_at_the_same_time(
    app: FastAPI,
    two: tuple[TestClient, TestClient],
) -> None:
    ana, bo = two
    ana_id = UUID(ana.get("/api/v1/auth/me").json()["id"])
    asyncio.run(app.state.threads.claim(ThreadKey(ana_id, "t1")))  # ana's turn is running
    events = _say(bo, "t1", "hello from bo")  # not answered 409
    assert [e["type"] for e in events][-1] == "turn_finished"
    assert all(e.get("thread_id", "t1") == "t1" for e in events)


def test_a_request_ending_for_one_user_does_not_free_anothers_running_thread(
    app: FastAPI,
    two: tuple[TestClient, TestClient],
) -> None:
    ana, bo = two
    ana_id = UUID(ana.get("/api/v1/auth/me").json()["id"])
    ana_key = ThreadKey(ana_id, "t1")
    asyncio.run(app.state.threads.claim(ana_key))
    _say(bo, "t1", "hello from bo")  # bo's turn releases bo's thread at its end
    assert asyncio.run(app.state.threads.running(ana_key))
    assert (
        ana.post(
            f"{CHAT}/stream",
            json={"thread_id": "t1", "message": "x"},
            headers=OWN,
        ).status_code
        == 409
    )


def test_deleting_one_account_leaves_the_other_users_threads(
    app: FastAPI,
    two: tuple[TestClient, TestClient],
) -> None:
    ana, bo = two
    _say(ana, "t1", "hello from ana")
    _say(bo, "t1", "hello from bo")
    ana_id = UUID(ana.get("/api/v1/auth/me").json()["id"])
    assert asyncio.run(app.state.threads.forget_owner(ana_id)) == 1
    assert bo.get(f"{CHAT}/threads/t1").status_code == 200
    assert ana.get(f"{CHAT}/threads/t1").status_code == 404


def test_a_third_account_made_later_sees_none_of_it(
    app: FastAPI,
    two: tuple[TestClient, TestClient],
) -> None:
    ana, _ = two
    _say(ana, "t1", "hello from ana")
    make_user(app, "cy@example.com")
    with signed_in(app, email="cy@example.com", raise_server_exceptions=False) as cy:
        assert cy.get(f"{CHAT}/threads/t1").status_code == 404


# --- no module-level mutable state in the web backend ---------------------------------------

API = Path(__file__).resolve().parents[2] / "api"
MUTABLE_CALLS = {"dict", "list", "set", "defaultdict", "deque", "OrderedDict", "Counter"}
# Reviewed constants: filled once at import and never written to afterwards.
ALLOWED = {
    ("api/routers/v1_chat.py", "SSE_HEADERS"),
    ("api/routers/v1_chat.py", "REPORT_RESPONSES"),
    ("api/routers/v1_settings.py", "KEY_PATHS"),
    # Read-only lookup tables (label and status maps), reviewed: nothing ever writes to them.
    ("api/services/exposure_graph/worker.py", "TIER_STATUS"),
    ("api/services/projectors/stacks.py", "TIERS"),
    ("api/services/report/chemical.py", "PROPERTY_LABELS"),
    ("api/services/report/chemical.py", "_KIND_LABELS"),
    ("api/services/report/document.py", "_PAGE_FIELDS"),
    ("api/services/report/risk.py", "_OUTCOMES"),
    ("api/services/report/summary.py", "STATUS_LABELS"),
}
EXPORT_LIST = "__all__"


def _is_mutable(value: ast.expr) -> bool:
    if isinstance(value, ast.Dict | ast.List | ast.Set | ast.DictComp | ast.ListComp | ast.SetComp):
        return True
    return (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and value.func.id in MUTABLE_CALLS
    )


def _module_level_mutables(path: Path) -> list[tuple[str, str]]:
    tree = ast.parse(path.read_text())
    found: list[tuple[str, str]] = []
    for node in tree.body:
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign) and _is_mutable(node.value):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign) and node.value is not None and _is_mutable(node.value):
            targets = [node.target]
        relative = str(path.relative_to(API.parent))
        found.extend((relative, t.id) for t in targets if isinstance(t, ast.Name))
    return found


def test_no_module_of_the_web_backend_holds_mutable_state() -> None:
    found = [
        item
        for path in sorted(API.rglob("*.py"))
        for item in _module_level_mutables(path)
        if item not in ALLOWED and item[1] != EXPORT_LIST
    ]
    assert found == []


def test_the_scan_really_finds_mutable_module_state(tmp_path: Path) -> None:
    sample = API / "__scan_sample__.py"
    sample.write_text("USERS: dict[str, str] = {}\nNAMES = set()\nFINE = ('a', 'b')\n")
    try:
        names = {name for _, name in _module_level_mutables(sample)}
    finally:
        sample.unlink()
    assert names == {"USERS", "NAMES"}
