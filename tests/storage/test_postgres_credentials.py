"""PostgreSQL behaviour of the sealed-credential repository and the 0005 migration
(``postgres`` marker). Each test works in its own migrated schema (``tests/postgres.py``)."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker

from storage.user_credentials import CredentialRepository, StoredCredential
from tests.postgres import Database, add_user, database

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@dataclass
class Credentials:
    db: Database
    repo: CredentialRepository
    alice: UUID
    bob: UUID


def _row(user: UUID, kek: str = "kek-a", byte: int = 1) -> StoredCredential:
    return StoredCredential(user, "openai", bytes([byte]) * 12, bytes([byte]) * 40, kek)


@pytest.fixture
async def creds() -> AsyncGenerator[Credentials]:
    async with database() as db:
        alice = await add_user(db.engine, uuid4())
        bob = await add_user(db.engine, uuid4())
        yield Credentials(db, CredentialRepository(async_sessionmaker(db.engine)), alice, bob)


async def test_put_then_get_returns_only_that_users_row(creds: Credentials) -> None:
    await creds.repo.put(_row(creds.alice, byte=1))
    assert await creds.repo.get(creds.alice, "openai") == _row(creds.alice, byte=1)
    assert await creds.repo.get(creds.bob, "openai") is None


async def test_put_replaces_the_same_users_row(creds: Credentials) -> None:
    await creds.repo.put(_row(creds.alice, byte=1))
    await creds.repo.put(_row(creds.alice, kek="kek-b", byte=2))
    assert await creds.repo.get(creds.alice, "openai") == _row(creds.alice, kek="kek-b", byte=2)


async def test_saving_for_one_user_leaves_another_untouched(creds: Credentials) -> None:
    await creds.repo.put(_row(creds.bob, byte=9))
    await creds.repo.put(_row(creds.alice, byte=1))
    assert await creds.repo.get(creds.bob, "openai") == _row(creds.bob, byte=9)


async def test_delete_removes_only_that_users_row(creds: Credentials) -> None:
    await creds.repo.put(_row(creds.alice))
    await creds.repo.put(_row(creds.bob))
    await creds.repo.delete(creds.alice, "openai")
    assert await creds.repo.get(creds.alice, "openai") is None
    assert await creds.repo.get(creds.bob, "openai") is not None
    await creds.repo.delete(creds.alice, "openai")  # absent: still fine


async def test_deleting_the_user_deletes_the_row(creds: Credentials) -> None:
    await creds.repo.put(_row(creds.alice))
    async with creds.db.engine.begin() as connection:
        await connection.execute(text("DELETE FROM users WHERE id = :id"), {"id": creds.alice})
    assert await creds.repo.get(creds.alice, "openai") is None


async def test_a_row_for_an_unknown_user_is_refused(creds: Credentials) -> None:
    with pytest.raises(DBAPIError):
        await creds.repo.put(_row(uuid4()))


async def test_a_nonce_of_the_wrong_length_is_refused(creds: Credentials) -> None:
    bad = StoredCredential(creds.alice, "openai", b"short", b"x" * 40, "kek-a")
    with pytest.raises(DBAPIError):
        await creds.repo.put(bad)


async def test_replace_if_sealed_by_requires_the_old_key_id(creds: Credentials) -> None:
    await creds.repo.put(_row(creds.alice, kek="kek-a"))
    newer = _row(creds.alice, kek="kek-b", byte=2)
    assert await creds.repo.replace_if_sealed_by(newer, "kek-zzz") is False
    assert await creds.repo.get(creds.alice, "openai") == _row(creds.alice, kek="kek-a")
    assert await creds.repo.replace_if_sealed_by(newer, "kek-a") is True
    assert await creds.repo.get(creds.alice, "openai") == newer


async def test_batches_list_rows_of_other_keys_in_order(creds: Credentials) -> None:
    await creds.repo.put(_row(creds.alice, kek="kek-a"))
    await creds.repo.put(_row(creds.bob, kek="kek-b"))
    first = await creds.repo.unsealed_by_other_keys("kek-b", limit=5)
    assert [row.user_id for row in first] == [creds.alice]
    both = await creds.repo.unsealed_by_other_keys("kek-zzz", limit=1)
    assert len(both) == 1
    rest = await creds.repo.unsealed_by_other_keys(
        "kek-zzz",
        limit=5,
        after=(both[0].user_id, both[0].purpose),
    )
    assert {both[0].user_id, rest[0].user_id} == {creds.alice, creds.bob}


async def test_count_sealed_by(creds: Credentials) -> None:
    await creds.repo.put(_row(creds.alice, kek="kek-a"))
    await creds.repo.put(_row(creds.bob, kek="kek-b"))
    assert await creds.repo.count_sealed_by("kek-a") == 1
    assert await creds.repo.count_sealed_by("kek-none") == 0
