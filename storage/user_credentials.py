"""``CredentialRepository``: a user's sealed secrets in PostgreSQL.

Stores only what ``commons.sealed_secret`` produced (nonce, ciphertext, the id of the key that
sealed it); it never sees a plaintext or a key-encryption key. Every per-user method takes the
``user_id`` and puts it in its ``WHERE``; none exists without one. The one call across users is
``unsealed_by_other_keys``, the batch the rotation command walks.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import Row, and_, delete, func, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql import Executable

from storage.tables import user_credentials as credentials

Sessions = async_sessionmaker[AsyncSession]
_COLUMNS = credentials.c


@dataclass(frozen=True)
class StoredCredential:
    """One stored sealed secret.

    Attributes:
        user_id: Owner of the secret.
        purpose: What it is for (``"openai"``).
        nonce: The 96-bit GCM nonce.
        ciphertext: The sealed secret with its tag.
        kek_id: Identifier of the key-encryption key that sealed it.
    """

    user_id: UUID
    purpose: str
    nonce: bytes
    ciphertext: bytes
    kek_id: str


def _stored(row: Row[UUID, str, bytes, bytes, str]) -> StoredCredential:
    user_id, purpose, nonce, ciphertext, kek_id = row
    return StoredCredential(user_id, purpose, bytes(nonce), bytes(ciphertext), kek_id)


_SELECT = (_COLUMNS.user_id, _COLUMNS.purpose, _COLUMNS.nonce, _COLUMNS.ciphertext, _COLUMNS.kek_id)


def _reseal(credential: StoredCredential, old_kek_id: str) -> Executable:
    """The guarded update of one row: it applies only while the row is sealed by the old key."""
    where = and_(
        _COLUMNS.user_id == credential.user_id,
        _COLUMNS.purpose == credential.purpose,
        _COLUMNS.kek_id == old_kek_id,
    )
    return (
        update(credentials)
        .where(where)
        .values(
            nonce=credential.nonce,
            ciphertext=credential.ciphertext,
            kek_id=credential.kek_id,
            updated_at=func.now(),
        )
        .returning(_COLUMNS.user_id)
    )


class CredentialRepository:
    """Reads, writes and deletes a user's sealed secrets.

    Args:
        sessions: Factory of async sessions (one transaction per call).
    """

    def __init__(self, sessions: Sessions) -> None:
        self._sessions = sessions

    async def get(self, user_id: UUID, purpose: str) -> StoredCredential | None:
        """The user's secret for ``purpose``, or None."""
        statement = select(*_SELECT).where(
            _COLUMNS.user_id == user_id,
            _COLUMNS.purpose == purpose,
        )
        async with self._sessions() as session:
            row = (await session.execute(statement)).one_or_none()
        return None if row is None else _stored(row)

    async def put(self, credential: StoredCredential) -> None:
        """Insert the user's secret, replacing any earlier one for the same purpose."""
        values = {
            "nonce": credential.nonce,
            "ciphertext": credential.ciphertext,
            "kek_id": credential.kek_id,
            "updated_at": func.now(),
        }
        statement = insert(credentials).values(
            user_id=credential.user_id,
            purpose=credential.purpose,
            **values,
        )
        upsert = statement.on_conflict_do_update(
            index_elements=[_COLUMNS.user_id, _COLUMNS.purpose],
            set_=values,
        )
        async with self._sessions.begin() as session:
            await session.execute(upsert)

    async def delete(self, user_id: UUID, purpose: str) -> None:
        """Delete the user's secret for ``purpose`` (deleting an absent one succeeds)."""
        statement = delete(credentials).where(
            _COLUMNS.user_id == user_id,
            _COLUMNS.purpose == purpose,
        )
        async with self._sessions.begin() as session:
            await session.execute(statement)

    async def replace_if_sealed_by(self, credential: StoredCredential, old_kek_id: str) -> bool:
        """Re-seal one row, only if it is still sealed by ``old_kek_id``.

        A user saving a new key at the same moment wins: the guard makes this a no-op then.

        Returns:
            True when the row was replaced.
        """
        statement = _reseal(credential, old_kek_id)
        async with self._sessions.begin() as session:
            return (await session.execute(statement)).first() is not None

    async def unsealed_by_other_keys(
        self,
        current_kek_id: str,
        limit: int,
        after: tuple[UUID, str] | None = None,
    ) -> list[StoredCredential]:
        """A batch of rows not sealed by ``current_kek_id``, ordered by ``(user_id, purpose)``.

        Across users, for the rotation command only. ``after`` is the last key of the previous
        batch.
        """
        statement = (
            select(*_SELECT)
            .where(_COLUMNS.kek_id != current_kek_id)
            .order_by(_COLUMNS.user_id, _COLUMNS.purpose)
            .limit(limit)
        )
        if after is not None:
            statement = statement.where(tuple_(_COLUMNS.user_id, _COLUMNS.purpose) > after)
        async with self._sessions() as session:
            rows = (await session.execute(statement)).all()
        return [_stored(row) for row in rows]

    async def count_sealed_by(self, kek_id: str) -> int:
        """How many rows are sealed by ``kek_id``."""
        statement = select(func.count()).select_from(credentials).where(_COLUMNS.kek_id == kek_id)
        async with self._sessions() as session:
            return (await session.execute(statement)).scalar_one()
