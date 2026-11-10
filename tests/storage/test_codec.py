"""Tests for the row codec: round trips, and every malformed row reads as absent."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from pydantic import BaseModel, ConfigDict

from app.usage_meter import CallUsage
from storage import codec
from storage.keys import ThreadKey
from storage.turn_model import TurnStatus
from tools.schemas import ConfirmationRequest

OWNER = UUID(int=1)
THREAD = "thread-1"


class Board(BaseModel):
    """A stand-in workspace model; the real one is passed in by the caller."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int = 0
    names: list[str] = []


def _request() -> ConfirmationRequest:
    entry = {
        "entry_id": "rfc:x",
        "quantity": "rfc",
        "subject": "subject-a",
        "accepted_units": ["mg/kg-day", "ug/kg-day"],
        "minimum": 0.001,
        "maximum": 100.0,
        "purpose": "to compute a hazard quotient",
    }
    return cast(ConfirmationRequest, {"request_id": "req-1", "entries": [entry]})


def _entry(request: ConfirmationRequest) -> dict[str, object]:
    return cast(dict[str, object], request["entries"][0])


# --- messages -------------------------------------------------------------------------------


def test_messages_round_trip() -> None:
    call = {"name": "lookup", "args": {"q": "x"}, "id": "c1", "type": "tool_call"}
    messages = [
        HumanMessage("hi"),
        AIMessage("", tool_calls=[call]),
        ToolMessage("ok", tool_call_id="c1"),
    ]
    decoded = [codec.message_from_json(codec.message_to_json(m), THREAD) for m in messages]
    assert decoded == messages


@pytest.mark.parametrize(
    "raw",
    [None, "text", 3, [], {}, {"type": "no-such-message", "data": {}}, {"type": "human"}],
)
def test_unknown_or_malformed_message_is_absent_and_logged(
    raw: object,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="storage.codec"):
        assert codec.message_from_json(raw, THREAD) is None
    assert THREAD in caplog.text
    assert "no-such-message" not in caplog.text


# --- workspace ------------------------------------------------------------------------------


def test_workspace_round_trip() -> None:
    board = Board(version=2, names=["a"])
    assert codec.workspace_from_json(Board, codec.workspace_to_json(board), THREAD) == board


@pytest.mark.parametrize("raw", [None, [], "x", {"version": "two"}, {"version": 1, "extra": 1}])
def test_malformed_workspace_is_absent_and_logged(
    raw: object,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="storage.codec"):
        assert codec.workspace_from_json(Board, raw, THREAD) is None
    assert THREAD in caplog.text


# --- pending request ------------------------------------------------------------------------


def test_pending_round_trip_returns_a_copy() -> None:
    request = _request()
    stored = codec.pending_to_json(request)
    assert codec.pending_from_json(stored, THREAD) == request
    _entry(request)["subject"] = "changed"
    assert cast(list[dict[str, object]], stored["entries"])[0]["subject"] == "subject-a"


@pytest.mark.parametrize(
    "change",
    [
        {"minimum": float("nan")},
        {"maximum": float("inf")},
        {"minimum": True},
        {"maximum": "9"},
        {"accepted_units": []},
        {"accepted_units": ["ok", 3]},
        {"accepted_units": "mg"},
        {"entry_id": ""},
        {"purpose": None},
    ],
)
def test_entry_with_a_bad_field_makes_the_request_absent(change: dict[str, object]) -> None:
    stored = codec.pending_to_json(_request())
    cast(list[dict[str, object]], stored["entries"])[0].update(change)
    assert codec.pending_from_json(stored, THREAD) is None


@pytest.mark.parametrize("missing", ["entry_id", "quantity", "subject", "minimum", "purpose"])
def test_entry_missing_a_field_makes_the_request_absent(missing: str) -> None:
    stored = codec.pending_to_json(_request())
    del cast(list[dict[str, object]], stored["entries"])[0][missing]
    assert codec.pending_from_json(stored, THREAD) is None


@pytest.mark.parametrize(
    "raw",
    [
        None,
        [],
        {},
        {"request_id": "r"},
        {"request_id": "", "entries": []},
        {"request_id": 1, "entries": []},
    ],
)
def test_malformed_request_is_absent(raw: object) -> None:
    assert codec.pending_from_json(raw, THREAD) is None


# --- usage and answers ----------------------------------------------------------------------


def test_usage_row_decodes_including_unknown_tokens() -> None:
    assert codec.usage_from_row(THREAD, "m", 10, 4, 6) == CallUsage("m", 10, 4, 6)
    assert codec.usage_from_row(THREAD, "m", None, 0, None) == CallUsage("m", None, 0, None)


@pytest.mark.parametrize(
    "row",
    [
        ("", 1, 0, 1),
        (None, 1, 0, 1),
        ("m", True, 0, 1),
        ("m", 1, False, 1),
        ("m", 1, None, 1),
        ("m", -1, 0, 1),
        ("m", 1.5, 0, 1),
        ("m", 1, 0, float("nan")),
        ("m", "1", 0, 1),
    ],
)
def test_bad_usage_row_is_absent(row: tuple[object, object, object, object]) -> None:
    assert codec.usage_from_row(THREAD, *row) is None


def test_answers() -> None:
    assert codec.answer_from_row(THREAD, "rfc", 2.5, False) == ("rfc", 2.5)
    assert codec.answer_from_row(THREAD, "rfc", 3, False) == ("rfc", 3.0)
    assert codec.answer_from_row(THREAD, "rfc", None, True) == ("rfc", None)


@pytest.mark.parametrize(
    ("key", "value", "declined"),
    [
        ("rfc", float("nan"), False),
        ("rfc", float("inf"), False),
        ("rfc", True, False),
        ("rfc", "2", False),
        ("rfc", None, False),
        ("rfc", 1.0, True),
        ("rfc", None, None),
        ("", 1.0, False),
        (None, 1.0, False),
    ],
)
def test_bad_answer_is_absent(key: object, value: object, declined: object) -> None:
    assert codec.answer_from_row(THREAD, key, value, declined) is None


def _turn_row(**changes: object) -> dict[str, object]:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    row: dict[str, object] = {
        "id": "t1",
        "user_id": OWNER,
        "thread_id": "th",
        "status": "interrupted",
        "reason": "out_of_credits",
        "resume_count": 1,
        "created_at": now,
        "started_at": now,
        "updated_at": now,
        "finished_at": None,
    }
    return row | changes


def test_a_turn_row_decodes() -> None:
    turn = codec.turn_from_row(_turn_row())
    assert turn is not None
    assert (turn.status, turn.reason, turn.resume_count) == (
        TurnStatus.INTERRUPTED,
        "out_of_credits",
        1,
    )
    assert turn.key == ThreadKey(OWNER, "th")


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "paused"},
        {"status": 3},
        {"resume_count": -1},
        {"resume_count": True},
        {"reason": None},  # an interrupted turn needs a reason
        {"status": "completed"},  # a completed one has none
        {"reason": 7},
        {"user_id": None},  # every turn has an owner
        {"user_id": "not-a-uuid"},
    ],
)
def test_a_turn_row_that_does_not_fit_is_absent_with_a_warning(
    changes: dict[str, object],
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="storage.codec"):
        assert codec.turn_from_row(_turn_row(**changes)) is None
    assert "turn" in caplog.text and "th" in caplog.text
