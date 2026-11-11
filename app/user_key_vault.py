"""Each user's OpenAI key, sealed in the application database.

``UserKeyVault`` is the only module that decrypts a user's key. ``read(user_id)`` is the single
per-turn entry point: the web runner calls it at the start of a turn, and a background worker
calls the same function from the ids it receives. A key is sealed with AES-256-GCM under the
current key-encryption key (KEK) with the owner and purpose as associated data, so a ciphertext
copied to another user's row does not open. A previous KEK, supplied during a rotation, still
opens its rows, which are re-sealed under the current one when read.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from pydantic import SecretStr

from app.key_vault import KeyStatus, validate_key
from app.redaction import protect_for_process
from commons.sealed_secret import SealedSecretError, kek_id, open_, parse_kek, seal
from config.byok import ByokSettings
from storage.user_credentials import StoredCredential

logger = logging.getLogger(__name__)
OPENAI_PURPOSE = "openai"


class KekConfigurationError(RuntimeError):
    """A key-encryption key is missing or malformed; the message names the variable, not a value."""


class SealedCredentialStore(Protocol):
    """The part of ``storage.user_credentials.CredentialRepository`` the vault uses."""

    async def get(self, user_id: UUID, purpose: str) -> StoredCredential | None: ...

    async def put(self, credential: StoredCredential) -> None: ...

    async def delete(self, user_id: UUID, purpose: str) -> None: ...

    async def replace_if_sealed_by(
        self,
        credential: StoredCredential,
        old_kek_id: str,
    ) -> bool: ...

    async def unsealed_by_other_keys(
        self,
        current_kek_id: str,
        limit: int,
        after: tuple[UUID, str] | None = None,
    ) -> list[StoredCredential]: ...

    async def count_sealed_by(self, kek_id: str) -> int: ...


@dataclass(frozen=True)
class RotationReport:
    """What ``rotate`` did, as counts only.

    Attributes:
        resealed: Rows re-sealed under the current key.
        already_current: Rows that were already sealed under it.
        unreadable: Rows whose key is neither current nor previous (or that do not open).
    """

    resealed: int
    already_current: int
    unreadable: int


@dataclass(frozen=True)
class KeyEncryptionKeys:
    """The raw key-encryption keys in force: the current one and, in a rotation, the previous.

    Attributes:
        current: The 32-byte key every new seal uses.
        previous: The 32-byte key that still opens older rows, or None.
    """

    current: bytes
    previous: bytes | None = None

    def by_id(self) -> dict[str, bytes]:
        """Each key under its identifier."""
        keys = {kek_id(self.current): self.current}
        if self.previous is not None:
            keys[kek_id(self.previous)] = self.previous
        return keys


def _read_kek(environ: Mapping[str, str], variable: str) -> bytes | None:
    text = environ.get(variable, "").strip()
    if not text:
        return None
    protect_for_process([text])
    try:
        return parse_kek(text)
    except SealedSecretError as error:
        raise KekConfigurationError(f"{variable} is malformed: {error}") from None


def load_keks(environ: Mapping[str, str], settings: ByokSettings) -> KeyEncryptionKeys:
    """Read the key-encryption keys from the variables named in ``[byok]`` and protect them.

    Raises:
        KekConfigurationError: If the current key is missing, or either is not base64url of
            exactly 32 bytes; the message names the variable and never its value.
    """
    current = _read_kek(environ, settings.kek_env_var)
    if current is None:
        raise KekConfigurationError(
            f"{settings.kek_env_var} is not set; it must hold a 32-byte key.",
        )
    return KeyEncryptionKeys(current, _read_kek(environ, settings.previous_kek_env_var))


class UserKeyVault:
    """Save, read and clear each user's OpenAI key, sealed in the database.

    Args:
        store: The sealed-credential table (PostgreSQL in production, a fake in tests).
        keks: The key-encryption keys in force.
        max_length: Longest key accepted, in characters.
    """

    def __init__(
        self,
        store: SealedCredentialStore,
        keks: KeyEncryptionKeys,
        max_length: int,
    ) -> None:
        self._store = store
        self._keks = keks
        self._by_id = keks.by_id()
        self._current_id = kek_id(keks.current)
        self._max_length = max_length

    @staticmethod
    def _aad(user_id: UUID, purpose: str) -> bytes:
        return f"ecofate:{purpose}:{user_id}".encode()

    def _sealed(self, user_id: UUID, key: str) -> StoredCredential:
        nonce, ciphertext = seal(self._keks.current, key, self._aad(user_id, OPENAI_PURPOSE))
        return StoredCredential(user_id, OPENAI_PURPOSE, nonce, ciphertext, self._current_id)

    async def save(self, user_id: UUID, key: str) -> KeyStatus:
        """Validate and store the user's key, replacing any earlier one.

        Raises:
            InvalidKeyError: If the key is rejected (nothing is stored).
        """
        valid = validate_key(key, self._max_length)
        await self._store.put(self._sealed(user_id, valid))
        return KeyStatus(configured=True)

    async def clear(self, user_id: UUID) -> KeyStatus:
        """Delete the user's key; clearing an absent key succeeds."""
        await self._store.delete(user_id, OPENAI_PURPOSE)
        return KeyStatus(configured=False)

    async def status(self, user_id: UUID) -> KeyStatus:
        """Whether the user has a usable key (never any part of it)."""
        return KeyStatus(configured=await self.read(user_id) is not None)

    async def read(self, user_id: UUID) -> SecretStr | None:
        """Decrypt the user's key, or None when there is none or it cannot be opened.

        An unreadable row (its key withdrawn, or it does not authenticate for this user) is
        treated as absent and logged by user id only; a row opened with the previous key is
        re-sealed under the current one.
        """
        row = await self._store.get(user_id, OPENAI_PURPOSE)
        if row is None:
            return None
        plaintext = self._open(row)
        if plaintext is None:
            logger.warning("Stored OpenAI key of user %s cannot be opened", user_id)
            return None
        if row.kek_id != self._current_id:
            await self._store.replace_if_sealed_by(self._sealed(user_id, plaintext), row.kek_id)
        return SecretStr(plaintext)

    def _open(self, row: StoredCredential) -> str | None:
        kek = self._by_id.get(row.kek_id)
        if kek is None:
            return None
        try:
            return open_(kek, row.nonce, row.ciphertext, self._aad(row.user_id, row.purpose))
        except SealedSecretError:
            return None

    async def rotate(self, batch_size: int) -> RotationReport:
        """Re-seal every stored key under the current key, batch by batch.

        Rows nobody can open are counted, left in place and skipped.
        """
        already = await self._store.count_sealed_by(self._current_id)
        resealed = unreadable = 0
        after: tuple[UUID, str] | None = None
        while batch := await self._store.unsealed_by_other_keys(
            self._current_id,
            batch_size,
            after,
        ):
            for row in batch:
                if await self._reseal(row):
                    resealed += 1
                else:
                    unreadable += 1
            after = (batch[-1].user_id, batch[-1].purpose)
        return RotationReport(resealed, already, unreadable)

    async def _reseal(self, row: StoredCredential) -> bool:
        plaintext = self._open(row)
        if plaintext is None:
            return False
        await self._store.replace_if_sealed_by(self._sealed(row.user_id, plaintext), row.kek_id)
        return True


def load_user_key_vault(
    environ: Mapping[str, str],
    store: SealedCredentialStore,
    settings: ByokSettings,
    max_length: int,
) -> UserKeyVault:
    """Build the vault from the environment (the outer edge; raises ``KekConfigurationError``)."""
    return UserKeyVault(store, load_keks(environ, settings), max_length)
