"""Password policy and Argon2id hashing."""

from __future__ import annotations

import pytest

from api.services.auth.passwords import PasswordPolicyError, Passwords
from tests.api.auth_support import fast_settings

pytestmark = pytest.mark.anyio
EMAIL = "ana@example.com"


@pytest.fixture
def passwords() -> Passwords:
    return Passwords(fast_settings())


def test_a_password_of_the_minimum_length_is_accepted(passwords: Passwords) -> None:
    passwords.check_policy("a" * 12, EMAIL)
    passwords.check_policy("a" * 128, EMAIL)


@pytest.mark.parametrize("password", ["", "short", "a" * 11])
def test_a_short_password_is_refused(passwords: Passwords, password: str) -> None:
    with pytest.raises(PasswordPolicyError, match="at least 12"):
        passwords.check_policy(password, EMAIL)


def test_a_password_over_the_maximum_is_refused(passwords: Passwords) -> None:
    with pytest.raises(PasswordPolicyError, match="at most 128"):
        passwords.check_policy("a" * 129, EMAIL)


def test_a_password_equal_to_the_email_is_refused_whatever_its_case(passwords: Passwords) -> None:
    with pytest.raises(PasswordPolicyError, match="email"):
        passwords.check_policy("ANA@example.COM", EMAIL)


def test_no_composition_rule_is_imposed(passwords: Passwords) -> None:
    passwords.check_policy("aaaaaaaaaaaa", EMAIL)
    passwords.check_policy("            ", EMAIL)


async def test_a_hash_is_argon2id_salted_and_verifies(passwords: Passwords) -> None:
    first = await passwords.hash("correct horse battery")
    second = await passwords.hash("correct horse battery")
    assert first.startswith("$argon2id$") and first != second
    assert "correct horse" not in first
    assert await passwords.verify(first, "correct horse battery")


async def test_a_wrong_password_or_a_malformed_hash_never_matches(passwords: Passwords) -> None:
    stored = await passwords.hash("correct horse battery")
    assert not await passwords.verify(stored, "wrong horse battery")
    assert not await passwords.verify("not-a-hash", "correct horse battery")
    assert not await passwords.verify("", "")


async def test_an_over_long_password_is_refused_without_hashing(passwords: Passwords) -> None:
    stored = await passwords.hash("a" * 128)
    assert not await passwords.verify(stored, "a" * 10_000)


async def test_an_unknown_account_still_pays_for_one_verification(
    passwords: Passwords,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    original = passwords.verify

    async def spy(stored: str, password: str) -> bool:
        calls.append(stored)
        return await original(stored, password)

    monkeypatch.setattr(passwords, "verify", spy)
    await passwords.verify_unknown("whatever password")
    assert len(calls) == 1 and calls[0].startswith("$argon2id$")


async def test_a_hash_made_with_other_parameters_needs_a_rehash(passwords: Passwords) -> None:
    from dataclasses import replace

    from config.auth import Argon2Settings

    other = Passwords(replace(fast_settings(), argon2=Argon2Settings(2, 16, 1)))
    stored = await other.hash("correct horse battery")
    assert passwords.needs_rehash(stored)
    assert not passwords.needs_rehash(await passwords.hash("correct horse battery"))
