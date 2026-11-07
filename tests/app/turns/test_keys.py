"""The turn's keys: read once, required model key, provided for the block only."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from app.key_vault import default_service_keys
from app.redaction import LITERAL_REDACTED, redact
from app.turns.failures import FailureReason, KeysUnavailableError
from app.turns.keys import TurnKeys, load_turn_keys, provided
from tests.fakes import CENSUS_ENTRY, OPENAI_ENTRY, FakeCredentialStore
from tools.credentials import CENSUS_KEY, COMPTOX_KEY, PROVIDER_KEY

MODEL_KEY = "sk-proj-" + "q1W2e3R4t5" * 3  # pragma: allowlist secret
SERVICE_KEY = "census-key-" + "8b" * 12  # pragma: allowlist secret


def test_no_model_key_is_its_own_reason() -> None:
    with pytest.raises(KeysUnavailableError) as raised:
        load_turn_keys(default_service_keys(FakeCredentialStore()))
    assert raised.value.reason == FailureReason.NO_KEY


def test_an_unavailable_keychain_is_its_own_reason() -> None:
    with pytest.raises(KeysUnavailableError) as raised:
        load_turn_keys(default_service_keys(FakeCredentialStore(fail=True)))
    assert raised.value.reason == FailureReason.KEYCHAIN_UNAVAILABLE


def test_service_keys_are_optional() -> None:
    store = FakeCredentialStore()
    store.entries[OPENAI_ENTRY] = MODEL_KEY
    store.entries[CENSUS_ENTRY] = SERVICE_KEY
    keys = load_turn_keys(default_service_keys(store))
    assert keys.openai.get_secret_value() == MODEL_KEY
    assert keys.census is not None and keys.comptox is None


def test_keys_are_provided_and_protected_for_the_block_only() -> None:
    keys = TurnKeys(openai=SecretStr(MODEL_KEY), census=SecretStr(SERVICE_KEY))
    with provided(keys):
        assert PROVIDER_KEY.get() is not None and CENSUS_KEY.get() is not None
        assert COMPTOX_KEY.get() is None
        assert redact(f"x {SERVICE_KEY}") == f"x {LITERAL_REDACTED}"
    assert (PROVIDER_KEY.get(), CENSUS_KEY.get()) == (None, None)
    assert SERVICE_KEY in redact(f"x {SERVICE_KEY}")


def test_keys_are_released_when_the_block_raises() -> None:
    keys = TurnKeys(openai=SecretStr(MODEL_KEY), census=SecretStr(SERVICE_KEY))
    with pytest.raises(RuntimeError), provided(keys):
        raise RuntimeError("inside the turn")
    assert (PROVIDER_KEY.get(), CENSUS_KEY.get()) == (None, None)
    assert SERVICE_KEY in redact(f"x {SERVICE_KEY}")
