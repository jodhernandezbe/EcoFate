"""The turn's keys: read once, required model key, provided for the block only."""

from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import SecretStr

from app.operator_keys import OperatorKeys
from app.redaction import LITERAL_REDACTED, redact
from app.turns.failures import FailureReason, KeysUnavailableError
from app.turns.keys import TurnKeys, load_turn_keys, provided
from tools.credentials import CENSUS_KEY, COMPTOX_KEY, PROVIDER_KEY

pytestmark = pytest.mark.anyio
MODEL_KEY = "sk-proj-" + "q1W2e3R4t5" * 3  # pragma: allowlist secret
SERVICE_KEY = "census-key-" + "8b" * 12  # pragma: allowlist secret


class _Reader:
    """A ``UserKeyReader`` with a fixed answer per user that counts its reads."""

    def __init__(self, keys: dict[UUID, str]) -> None:
        self.keys = keys
        self.reads: list[UUID] = []

    async def read(self, user_id: UUID) -> SecretStr | None:
        self.reads.append(user_id)
        key = self.keys.get(user_id)
        return SecretStr(key) if key else None


ALICE, BOB = UUID(int=1), UUID(int=2)
OPERATOR = OperatorKeys(census=SecretStr(SERVICE_KEY))


async def test_no_model_key_is_its_own_reason() -> None:
    with pytest.raises(KeysUnavailableError) as raised:
        await load_turn_keys(_Reader({}), OPERATOR, ALICE)
    assert raised.value.reason == FailureReason.NO_KEY


async def test_the_users_key_is_read_once_with_the_operators_service_keys() -> None:
    reader = _Reader({ALICE: MODEL_KEY})
    keys = await load_turn_keys(reader, OPERATOR, ALICE)
    assert reader.reads == [ALICE]
    assert keys.openai.get_secret_value() == MODEL_KEY
    assert keys.census is not None and keys.comptox is None


async def test_each_user_gets_only_their_own_model_key() -> None:
    reader = _Reader({ALICE: MODEL_KEY, BOB: "sk-proj-" + "b" * 24})
    assert (await load_turn_keys(reader, OPERATOR, BOB)).openai.get_secret_value() != MODEL_KEY


async def test_operator_keys_alone_do_not_let_a_user_without_a_key_chat() -> None:
    with pytest.raises(KeysUnavailableError):
        await load_turn_keys(_Reader({BOB: MODEL_KEY}), OPERATOR, ALICE)


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
