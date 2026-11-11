"""Authenticated encryption of a short secret with AES-256-GCM.

Pure functions: the key-encryption key (KEK) and the associated data come in as arguments, and
nothing is read from the environment or stored. The associated data binds a ciphertext to its
owner and purpose, so a ciphertext copied to another row fails to open instead of decrypting
under the wrong account.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
from typing import Final

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEK_BYTES: Final = 32  # AES-256
NONCE_BYTES: Final = 12  # the 96-bit nonce GCM is specified for
KEK_ID_HEX_CHARS: Final = 16


class SealedSecretError(ValueError):
    """A key is malformed or a ciphertext does not open; the message never carries a secret."""


def parse_kek(text: str) -> bytes:
    """Decode a base64url key-encryption key and check that it is exactly 32 bytes.

    Args:
        text: The key as written in the environment (padding optional, surrounding blanks ignored).

    Returns:
        The 32 raw key bytes.

    Raises:
        SealedSecretError: If the text is not base64url or not 32 bytes; the message does not
            contain the text.
    """
    stripped = text.strip()
    padded = stripped + "=" * (-len(stripped) % 4)
    try:
        raw = base64.b64decode(padded.encode("ascii"), altchars=b"-_", validate=True)
    except (binascii.Error, UnicodeEncodeError) as error:
        raise SealedSecretError("The key is not valid base64url.") from error
    if len(raw) != KEK_BYTES:
        raise SealedSecretError(f"The key must decode to exactly {KEK_BYTES} bytes.")
    return raw


def kek_id(kek: bytes) -> str:
    """Return the identifier of a key: the first 16 hex characters of its SHA-256.

    It identifies which key sealed a ciphertext without revealing the key.
    """
    return hashlib.sha256(kek).hexdigest()[:KEK_ID_HEX_CHARS]


def seal(kek: bytes, plaintext: str, aad: bytes) -> tuple[bytes, bytes]:
    """Encrypt ``plaintext`` under ``kek`` with a fresh random nonce.

    Args:
        kek: 32-byte key-encryption key.
        plaintext: The secret to protect.
        aad: Associated data authenticated with the ciphertext (owner and purpose).

    Returns:
        ``(nonce, ciphertext)``; the ciphertext includes GCM's 16-byte tag.

    Raises:
        SealedSecretError: If ``kek`` is not 32 bytes.
    """
    cipher = _cipher(kek)
    nonce = os.urandom(NONCE_BYTES)
    return nonce, cipher.encrypt(nonce, plaintext.encode("utf-8"), aad)


def open_(kek: bytes, nonce: bytes, ciphertext: bytes, aad: bytes) -> str:
    """Decrypt a ciphertext made by ``seal``.

    Raises:
        SealedSecretError: If the key, nonce, ciphertext or associated data do not match (the
            message says nothing about which).
    """
    cipher = _cipher(kek)
    try:
        return cipher.decrypt(nonce, ciphertext, aad).decode("utf-8")
    except (InvalidTag, ValueError) as error:
        raise SealedSecretError("The sealed secret could not be opened.") from error


def _cipher(kek: bytes) -> AESGCM:
    if len(kek) != KEK_BYTES:
        raise SealedSecretError(f"The key must be exactly {KEK_BYTES} bytes.")
    return AESGCM(kek)
