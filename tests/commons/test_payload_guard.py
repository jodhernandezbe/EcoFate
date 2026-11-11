"""Tests for the queued-payload guard."""

from __future__ import annotations

import pytest

from commons.payload_guard import PayloadRefusedError, assert_ids_only

KEY = "sk-proj-" + "a1B2c3D4e5" * 3  # pragma: allowlist secret
PROTECTED = "c3n5u5k3y7f7f7f7f7f7f7f7f7f7f7f7f7f"  # pragma: allowlist secret
IDS = {"user_id": "7b0c2f9e-1d34-4c7a-9a55-0c7f3d1b2a10", "thread_id": "t-1", "turn_id": 12}


def test_an_ids_only_payload_passes() -> None:
    assert_ids_only(IDS, [KEY, PROTECTED])


def test_nested_ids_pass() -> None:
    assert_ids_only({"turns": [{"id": "a"}, {"id": "b"}], "ok": True, "none": None}, [KEY])


def test_a_key_is_refused() -> None:
    with pytest.raises(PayloadRefusedError, match="key-shaped"):
        assert_ids_only({**IDS, "note": KEY})


def test_a_protected_literal_is_refused() -> None:
    with pytest.raises(PayloadRefusedError, match="protected"):
        assert_ids_only({**IDS, "note": f"x {PROTECTED} y"}, [PROTECTED])


def test_a_password_field_is_refused_even_with_an_innocent_value() -> None:
    with pytest.raises(PayloadRefusedError, match="credential"):
        assert_ids_only({**IDS, "password": "1"})


@pytest.mark.parametrize("name", ["api_key", "Token", "client_secret", "Cookie", "apiKey"])
def test_credential_named_fields_are_refused(name: str) -> None:
    with pytest.raises(PayloadRefusedError):
        assert_ids_only({name: 1})


def test_nested_values_are_refused() -> None:
    with pytest.raises(PayloadRefusedError, match=r"payload\.items\[1\]\.note"):
        assert_ids_only({"items": [{"id": 1}, {"note": KEY}]})


def test_a_key_in_a_tuple_or_set_is_refused() -> None:
    with pytest.raises(PayloadRefusedError):
        assert_ids_only({"ids": (1, KEY)})
    with pytest.raises(PayloadRefusedError):
        assert_ids_only({"ids": {KEY}})


def test_a_protected_literal_in_a_field_name_is_refused() -> None:
    with pytest.raises(PayloadRefusedError):
        assert_ids_only({PROTECTED: 1}, [PROTECTED])


def test_the_message_never_contains_the_value() -> None:
    with pytest.raises(PayloadRefusedError) as error:
        assert_ids_only({"note": KEY})
    assert KEY not in str(error.value)


def test_short_protected_values_do_not_refuse_ordinary_ids() -> None:
    assert_ids_only({"id": "abc"}, ["abc", ""])


def test_a_reset_link_token_is_refused() -> None:
    with pytest.raises(PayloadRefusedError):
        assert_ids_only({"link": "https://ecofate.example/reset#token=Zx81kLmq0PaT3vYb"})
