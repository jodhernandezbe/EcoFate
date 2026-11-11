"""Tests for the operator's service keys."""

from __future__ import annotations

import pytest

import app.redaction as redaction_module
from app.operator_keys import OperatorKeys, load_operator_keys
from app.redaction import redact

CENSUS = "census-operator-key-0123456789"  # pragma: allowlist secret
COMPTOX = "comptox-operator-key-9876543210"  # pragma: allowlist secret


@pytest.fixture(autouse=True)
def _isolated_process_literals(monkeypatch: pytest.MonkeyPatch) -> None:
    empty: set[str] = set()
    monkeypatch.setattr(redaction_module, "_PROCESS_LITERALS", empty)


def test_reads_both_keys_from_their_variables() -> None:
    keys = load_operator_keys({"C": f" {CENSUS} ", "T": COMPTOX}, "C", "T")
    assert keys.census is not None
    assert keys.comptox is not None
    assert keys.census.get_secret_value() == CENSUS
    assert keys.available() == {"census": True, "comptox": True}


def test_an_unset_or_blank_key_is_unavailable() -> None:
    keys = load_operator_keys({"C": "  "}, "C", "T")
    assert keys == OperatorKeys()
    assert keys.available() == {"census": False, "comptox": False}


def test_only_one_key_set() -> None:
    keys = load_operator_keys({"T": COMPTOX}, "C", "T")
    assert keys.available() == {"census": False, "comptox": True}


def test_the_keys_are_redacted_from_logs_for_the_process() -> None:
    load_operator_keys({"C": CENSUS, "T": COMPTOX}, "C", "T")
    assert CENSUS not in redact(f"url {CENSUS}")
    assert COMPTOX not in redact(f"header {COMPTOX}")


def test_the_repr_does_not_show_a_key() -> None:
    keys = load_operator_keys({"C": CENSUS}, "C", "T")
    assert CENSUS not in repr(keys)
