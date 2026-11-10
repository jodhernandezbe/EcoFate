"""Random tokens, their keyed hash, and single-use emailed tokens."""

from __future__ import annotations

import hashlib

import pytest

from api.services.auth.tokens import (
    SecretSetupError,
    TokenHasher,
    TokenService,
    load_session_secret,
    new_token,
    plausible,
)
from storage.account_model import TokenPurpose
from tests.api.auth_support import SECRET, fast_settings, make_auth

pytestmark = pytest.mark.anyio


def test_tokens_are_long_random_and_url_safe() -> None:
    first, second = new_token(), new_token()
    assert first != second and len(first) >= 43  # 256 bits
    assert plausible(first)


@pytest.mark.parametrize(
    "text",
    [None, "", "short", "has space in it 0123456789", "x" * 129, "a/b" * 10],
)
def test_a_token_of_the_wrong_shape_is_implausible(text: str | None) -> None:
    assert not plausible(text)


def test_the_stored_value_is_a_keyed_hash_not_the_token() -> None:
    token = new_token()
    digest = TokenHasher(SECRET).digest(token)
    assert token not in digest and digest != hashlib.sha256(token.encode()).hexdigest()
    assert TokenHasher(SECRET).digest(token) == digest
    assert TokenHasher(SECRET + b"x").digest(token) != digest


def test_a_hash_is_not_accepted_in_place_of_its_token() -> None:
    hasher = TokenHasher(SECRET)
    token = new_token()
    assert hasher.digest(hasher.digest(token)) != hasher.digest(token)


def test_a_short_secret_is_refused() -> None:
    with pytest.raises(SecretSetupError):
        TokenHasher(b"too short")


def test_the_secret_comes_from_the_named_variable_and_its_value_is_never_in_the_error() -> None:
    settings = fast_settings()
    name = settings.session_secret_env_var
    assert load_session_secret({name: "x" * 40}, settings) == b"x" * 40
    for environ in ({}, {name: ""}, {name: "short-secret-value"}):
        with pytest.raises(SecretSetupError) as raised:
            load_session_secret(environ, settings)
        assert name in str(raised.value) and "short-secret-value" not in str(raised.value)


async def test_a_token_works_once() -> None:
    kit = make_auth()
    user = await kit.accounts.users.create("a@example.com", "h")
    assert user is not None
    token = await kit.tokens.issue(user.id, TokenPurpose.VERIFY_EMAIL)
    assert await kit.tokens.consume(TokenPurpose.VERIFY_EMAIL, token) == user.id
    assert await kit.tokens.consume(TokenPurpose.VERIFY_EMAIL, token) is None


async def test_a_token_expires_after_its_lifetime() -> None:
    kit = make_auth()
    user = await kit.accounts.users.create("a@example.com", "h")
    assert user is not None
    token = await kit.tokens.issue(user.id, TokenPurpose.RESET_PASSWORD)
    kit.clock.advance(kit.settings.reset_token_minutes * 60 + 1)
    assert await kit.tokens.consume(TokenPurpose.RESET_PASSWORD, token) is None


async def test_a_verification_token_outlives_a_reset_token() -> None:
    kit = make_auth()
    user = await kit.accounts.users.create("a@example.com", "h")
    assert user is not None
    verify = await kit.tokens.issue(user.id, TokenPurpose.VERIFY_EMAIL)
    reset = await kit.tokens.issue(user.id, TokenPurpose.RESET_PASSWORD)
    kit.clock.advance(kit.settings.reset_token_minutes * 60 + 1)
    assert await kit.tokens.consume(TokenPurpose.RESET_PASSWORD, reset) is None
    assert await kit.tokens.consume(TokenPurpose.VERIFY_EMAIL, verify) == user.id


async def test_a_newer_token_supersedes_an_older_one_of_the_same_purpose() -> None:
    kit = make_auth()
    user = await kit.accounts.users.create("a@example.com", "h")
    assert user is not None
    old = await kit.tokens.issue(user.id, TokenPurpose.RESET_PASSWORD)
    new = await kit.tokens.issue(user.id, TokenPurpose.RESET_PASSWORD)
    assert await kit.tokens.consume(TokenPurpose.RESET_PASSWORD, old) is None
    assert await kit.tokens.consume(TokenPurpose.RESET_PASSWORD, new) == user.id


async def test_a_token_of_another_purpose_or_an_unknown_one_is_refused() -> None:
    kit = make_auth()
    user = await kit.accounts.users.create("a@example.com", "h")
    assert user is not None
    token = await kit.tokens.issue(user.id, TokenPurpose.VERIFY_EMAIL)
    assert await kit.tokens.consume(TokenPurpose.RESET_PASSWORD, token) is None
    assert await kit.tokens.consume(TokenPurpose.VERIFY_EMAIL, new_token()) is None
    assert await kit.tokens.consume(TokenPurpose.VERIFY_EMAIL, "garbage") is None


def test_the_service_type_is_the_one_the_flows_use() -> None:
    assert TokenService.__name__ == "TokenService"
