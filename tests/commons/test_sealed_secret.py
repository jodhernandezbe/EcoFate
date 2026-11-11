"""Tests for AES-256-GCM sealing of short secrets."""

from __future__ import annotations

import base64

import pytest

from commons.sealed_secret import (
    SealedSecretError,
    kek_id,
    open_,
    parse_kek,
    seal,
)

KEK = bytes(range(32))
OTHER_KEK = bytes(range(1, 33))
AAD = b"ecofate:openai:user-a"
PLAINTEXT = "test-plaintext-value"


def test_round_trip() -> None:
    nonce, ciphertext = seal(KEK, PLAINTEXT, AAD)
    assert open_(KEK, nonce, ciphertext, AAD) == PLAINTEXT


def test_ciphertext_does_not_contain_the_plaintext() -> None:
    _, ciphertext = seal(KEK, PLAINTEXT, AAD)
    assert PLAINTEXT.encode() not in ciphertext


def test_two_seals_differ() -> None:
    first = seal(KEK, PLAINTEXT, AAD)
    second = seal(KEK, PLAINTEXT, AAD)
    assert first[0] != second[0]
    assert first[1] != second[1]


def test_nonce_is_96_bits() -> None:
    nonce, _ = seal(KEK, PLAINTEXT, AAD)
    assert len(nonce) == 12


def test_wrong_aad_fails() -> None:
    nonce, ciphertext = seal(KEK, PLAINTEXT, AAD)
    with pytest.raises(SealedSecretError):
        open_(KEK, nonce, ciphertext, b"ecofate:openai:user-b")


def test_wrong_kek_fails() -> None:
    nonce, ciphertext = seal(KEK, PLAINTEXT, AAD)
    with pytest.raises(SealedSecretError):
        open_(OTHER_KEK, nonce, ciphertext, AAD)


def test_flipped_ciphertext_bit_fails() -> None:
    nonce, ciphertext = seal(KEK, PLAINTEXT, AAD)
    tampered = bytes([ciphertext[0] ^ 1]) + ciphertext[1:]
    with pytest.raises(SealedSecretError):
        open_(KEK, nonce, tampered, AAD)


def test_wrong_nonce_fails() -> None:
    nonce, ciphertext = seal(KEK, PLAINTEXT, AAD)
    with pytest.raises(SealedSecretError):
        open_(KEK, bytes(len(nonce)), ciphertext, AAD)


def test_truncated_ciphertext_fails() -> None:
    nonce, _ = seal(KEK, PLAINTEXT, AAD)
    with pytest.raises(SealedSecretError):
        open_(KEK, nonce, b"short", AAD)


def test_seal_refuses_a_short_key() -> None:
    with pytest.raises(SealedSecretError):
        seal(b"short", PLAINTEXT, AAD)


def test_parse_kek_accepts_base64url_with_or_without_padding() -> None:
    text = base64.urlsafe_b64encode(KEK).decode()
    assert parse_kek(text) == KEK
    assert parse_kek(text.rstrip("=")) == KEK
    assert parse_kek(f"  {text}\n") == KEK


@pytest.mark.parametrize(
    "text",
    [
        "",
        "not base64 !!",
        base64.urlsafe_b64encode(bytes(16)).decode(),
        base64.urlsafe_b64encode(bytes(33)).decode(),
        "é" * 43,
    ],
)
def test_parse_kek_rejects_malformed_values(text: str) -> None:
    with pytest.raises(SealedSecretError) as error:
        parse_kek(text)
    assert text.strip() == "" or text not in str(error.value)


def test_parse_kek_message_does_not_contain_the_value() -> None:
    secret = base64.urlsafe_b64encode(bytes(20)).decode()
    with pytest.raises(SealedSecretError) as error:
        parse_kek(secret)
    assert secret not in str(error.value)


def test_kek_id_is_stable_short_and_distinct() -> None:
    assert kek_id(KEK) == kek_id(KEK)
    assert kek_id(KEK) != kek_id(OTHER_KEK)
    assert len(kek_id(KEK)) == 16
    assert KEK.hex() not in kek_id(KEK)
