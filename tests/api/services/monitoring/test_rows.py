"""Tests for parsing Logfire rows: untrusted fields become absent, never a plausible number."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import pytest

from api.services.monitoring.rows import (
    amount,
    count,
    instant,
    outcome,
    parse_turn,
    text,
    token_usage,
)
from tests.api.services.monitoring.factories import turn_row


@pytest.mark.parametrize(("value", "expected"), [(5, 5), ("5", 5), (5.0, 5), ("0", 0)])
def test_a_count_accepts_whole_non_negative_numbers(value: object, expected: int) -> None:
    assert count({"n": value}, "n") == expected


@pytest.mark.parametrize(
    "value",
    [True, -1, "-1", 2.5, "2.5", "x", float("nan"), float("inf"), [], {}, "", None],
)
def test_a_count_rejects_everything_else(value: object) -> None:
    assert count({"n": value}, "n") is None


@pytest.mark.parametrize("value", [True, -0.1, "nan", "inf", float("inf"), "abc", [1], "1e999"])
def test_an_amount_rejects_non_finite_negative_and_non_numbers(value: object) -> None:
    assert amount({"a": value}, "a") is None


def test_an_amount_accepts_numeric_text_and_numbers() -> None:
    assert amount({"a": "0.030850000000000002"}, "a") == pytest.approx(0.03085)
    assert amount({"a": 2}, "a") == 2.0
    assert amount({}, "a") is None


def test_a_bad_field_is_warned_by_name_and_never_by_value(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="api.monitoring"):
        assert count({"input_tokens": "secret-looking-value"}, "input_tokens") is None
    assert "input_tokens" in caplog.text and "secret-looking-value" not in caplog.text


def test_text_must_be_a_non_blank_string() -> None:
    assert text({"t": "x"}, "t") == "x"
    assert text({"t": "  "}, "t") is None and text({"t": 3}, "t") is None


def test_an_instant_without_an_offset_is_taken_as_utc() -> None:
    assert instant({"t": "2026-01-02T03:04:05"}, "t") == datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    assert instant({"t": "2026-01-02T03:04:05.5Z"}, "t") is not None
    assert instant({"t": "yesterday"}, "t") is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [("ok", "ok"), ("error", "error"), ("x", "unknown"), (None, "unknown")],
)
def test_an_outcome_is_ok_error_or_unknown(value: object, expected: str) -> None:
    assert outcome({"o": value}, "o") == expected


def test_token_usage_reads_the_models_usage_json() -> None:
    raw = '{"input_tokens":11,"output_tokens":3,"total_tokens":14}'
    assert token_usage({"u": raw}, "u") == (11, 3)
    assert token_usage({"u": "not json"}, "u") == (None, None)
    assert token_usage({"u": "[1, 2]"}, "u") == (None, None)
    assert token_usage({}, "u") == (None, None)


def test_a_turn_row_becomes_a_record() -> None:
    turn = parse_turn(turn_row())
    assert turn is not None
    assert (turn.session_id, turn.model, turn.outcome) == ("s1", "m", "ok")
    assert (turn.usage.input_tokens, turn.usage.cached_input_tokens) == (100, 40)
    assert (turn.usage.cost_usd, turn.usage.cost_status) == (0.5, "estimate")
    assert (turn.model_calls, turn.tool_calls, turn.duration_s) == (2, 1, 2.0)


@pytest.mark.parametrize("missing", ["trace_id", "start_timestamp", "sid"])
def test_a_turn_without_identity_is_dropped(missing: str) -> None:
    assert parse_turn(turn_row(**{missing: None})) is None


def test_an_unknown_cost_status_is_absent() -> None:
    turn = parse_turn(turn_row(cost_status="free"))
    assert turn is not None and turn.usage.cost_status is None
