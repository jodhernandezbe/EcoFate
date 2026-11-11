"""Tests for the per-user key vault: sealing, isolation, rotation and start-up checks."""

from __future__ import annotations

import base64
import logging
from dataclasses import replace
from uuid import UUID, uuid4

import pytest

from app.key_vault import InvalidKeyError
from app.user_key_vault import (
    OPENAI_PURPOSE,
    KekConfigurationError,
    KeyEncryptionKeys,
    UserKeyVault,
    load_keks,
)
from commons.sealed_secret import kek_id
from config.byok import ByokSettings
from tests.fakes import InMemorySealedStore

KEK_A = bytes(range(32))
KEK_B = bytes(range(1, 33))
KEY_ONE = "sk-test-" + "A1b2C3d4" * 4  # pragma: allowlist secret
KEY_TWO = "sk-test-" + "Z9y8X7w6" * 4  # pragma: allowlist secret
pytestmark = pytest.mark.anyio
SETTINGS = ByokSettings("TEST_KEK", "TEST_KEK_PREVIOUS", 2)  # pragma: allowlist secret


def _text(kek: bytes) -> str:
    return base64.urlsafe_b64encode(kek).decode()


def _vault(
    store: InMemorySealedStore,
    current: bytes = KEK_A,
    previous: bytes | None = None,
) -> UserKeyVault:
    return UserKeyVault(store, KeyEncryptionKeys(current, previous), max_length=200)


@pytest.fixture
def store() -> InMemorySealedStore:
    return InMemorySealedStore()


async def test_save_then_read_round_trips(store: InMemorySealedStore) -> None:
    user = uuid4()
    vault = _vault(store)
    assert (await vault.save(user, KEY_ONE)).configured is True
    key = await vault.read(user)
    assert key is not None
    assert key.get_secret_value() == KEY_ONE


async def test_the_database_holds_no_plaintext(store: InMemorySealedStore) -> None:
    user = uuid4()
    await _vault(store).save(user, KEY_ONE)
    row = store.rows[(user, OPENAI_PURPOSE)]
    assert KEY_ONE.encode() not in row.ciphertext
    assert row.kek_id == kek_id(KEK_A)


async def test_two_saves_of_the_same_key_differ(store: InMemorySealedStore) -> None:
    user = uuid4()
    vault = _vault(store)
    await vault.save(user, KEY_ONE)
    first = store.rows[(user, OPENAI_PURPOSE)]
    await vault.save(user, KEY_ONE)
    second = store.rows[(user, OPENAI_PURPOSE)]
    assert (first.nonce, first.ciphertext) != (second.nonce, second.ciphertext)


async def test_another_users_status_is_not_configured(store: InMemorySealedStore) -> None:
    alice, bob = uuid4(), uuid4()
    vault = _vault(store)
    await vault.save(alice, KEY_ONE)
    assert (await vault.status(alice)).configured is True
    assert (await vault.status(bob)).configured is False
    assert await vault.read(bob) is None


async def test_a_ciphertext_copied_to_another_user_does_not_open(
    store: InMemorySealedStore,
    caplog: pytest.LogCaptureFixture,
) -> None:
    alice, bob = uuid4(), uuid4()
    vault = _vault(store)
    await vault.save(alice, KEY_ONE)
    stolen = store.rows[(alice, OPENAI_PURPOSE)]
    store.rows[(bob, OPENAI_PURPOSE)] = replace(stolen, user_id=bob)
    with caplog.at_level(logging.WARNING):
        assert await vault.read(bob) is None
    assert (await vault.status(bob)).configured is False
    assert str(bob) in caplog.text
    assert KEY_ONE not in caplog.text
    assert str(alice) not in caplog.text


async def test_clear_deletes_the_row(store: InMemorySealedStore) -> None:
    user = uuid4()
    vault = _vault(store)
    await vault.save(user, KEY_ONE)
    assert (await vault.clear(user)).configured is False
    assert store.rows == {}
    assert (await vault.clear(user)).configured is False


async def test_replacing_a_key_uses_the_new_one(store: InMemorySealedStore) -> None:
    user = uuid4()
    vault = _vault(store)
    await vault.save(user, KEY_ONE)
    await vault.save(user, KEY_TWO)
    key = await vault.read(user)
    assert key is not None
    assert key.get_secret_value() == KEY_TWO


@pytest.mark.parametrize("bad", ["", "   ", "has space", "tab\tkey", "x" * 201])
async def test_invalid_keys_are_refused_and_nothing_is_stored(
    store: InMemorySealedStore,
    bad: str,
) -> None:
    with pytest.raises(InvalidKeyError):
        await _vault(store).save(uuid4(), bad)
    assert store.rows == {}


async def test_a_row_under_the_previous_key_opens_and_is_resealed(
    store: InMemorySealedStore,
) -> None:
    user = uuid4()
    await _vault(store, KEK_A).save(user, KEY_ONE)
    rotating = _vault(store, KEK_B, previous=KEK_A)
    key = await rotating.read(user)
    assert key is not None
    assert key.get_secret_value() == KEY_ONE
    assert store.rows[(user, OPENAI_PURPOSE)].kek_id == kek_id(KEK_B)
    after = await _vault(store, KEK_B).read(user)  # previous key withdrawn
    assert after is not None
    assert after.get_secret_value() == KEY_ONE


async def test_a_row_under_an_unknown_key_is_unreadable_not_deleted(
    store: InMemorySealedStore,
) -> None:
    user = uuid4()
    await _vault(store, KEK_A).save(user, KEY_ONE)
    late = _vault(store, KEK_B)  # the old key was withdrawn too early
    assert (await late.status(user)).configured is False
    assert (user, OPENAI_PURPOSE) in store.rows


async def test_rotate_reseals_every_row_and_counts(store: InMemorySealedStore) -> None:
    users: list[UUID] = [uuid4() for _ in range(5)]
    for user in users:
        await _vault(store, KEK_A).save(user, KEY_ONE)
    lost = uuid4()
    await _vault(store, bytes(range(2, 34))).save(lost, KEY_TWO)
    already = uuid4()
    await _vault(store, KEK_B).save(already, KEY_TWO)
    report = await _vault(store, KEK_B, previous=KEK_A).rotate(batch_size=2)
    assert (report.resealed, report.already_current, report.unreadable) == (5, 1, 1)
    assert all(store.rows[(u, OPENAI_PURPOSE)].kek_id == kek_id(KEK_B) for u in users)
    for user in users:
        key = await _vault(store, KEK_B).read(user)
        assert key is not None
        assert key.get_secret_value() == KEY_ONE


async def test_rotate_twice_is_harmless(store: InMemorySealedStore) -> None:
    await _vault(store, KEK_A).save(uuid4(), KEY_ONE)
    rotating = _vault(store, KEK_B, previous=KEK_A)
    await rotating.rotate(batch_size=10)
    again = await rotating.rotate(batch_size=10)
    assert (again.resealed, again.already_current, again.unreadable) == (0, 1, 0)


# --- start-up ---------------------------------------------------------------------------------


def test_load_keks_reads_current_and_previous() -> None:
    environ = {"TEST_KEK": _text(KEK_B), "TEST_KEK_PREVIOUS": _text(KEK_A)}
    keks = load_keks(environ, SETTINGS)
    assert (keks.current, keks.previous) == (KEK_B, KEK_A)


def test_load_keks_without_a_previous_key() -> None:
    keks = load_keks({"TEST_KEK": _text(KEK_A)}, SETTINGS)
    assert keks.previous is None


def test_a_missing_kek_names_the_variable() -> None:
    with pytest.raises(KekConfigurationError, match="TEST_KEK"):
        load_keks({}, SETTINGS)
    with pytest.raises(KekConfigurationError, match="TEST_KEK"):
        load_keks({"TEST_KEK": "  "}, SETTINGS)


@pytest.mark.parametrize("bad", ["not base64 !!", _text(bytes(16)), _text(bytes(40))])
def test_a_malformed_kek_names_the_variable_not_the_value(bad: str) -> None:
    with pytest.raises(KekConfigurationError) as error:
        load_keks({"TEST_KEK": bad}, SETTINGS)
    assert "TEST_KEK" in str(error.value)
    assert bad not in str(error.value)


def test_a_malformed_previous_kek_is_refused_too() -> None:
    environ = {"TEST_KEK": _text(KEK_A), "TEST_KEK_PREVIOUS": "short"}
    with pytest.raises(KekConfigurationError, match="TEST_KEK_PREVIOUS"):
        load_keks(environ, SETTINGS)
