"""Tests for the key-shaped string patterns."""

from __future__ import annotations

import pytest

from commons.key_patterns import (
    COOKIE_PATTERN,
    DATABASE_URL_PATTERN,
    FRAGMENT_TOKEN_PATTERN,
    KEY_PATTERNS,
)

SECRETS = [
    "sk-abcdefghijklmnop",
    "sk-proj-****p8UA",
    "Authorization: Bearer abcdefgh12345678",
    "https://api.example.test/data?get=x&key=abcdef123456",
    "api_key=abcdefgh12345678",
    "'x-api-key': 'abcdefgh12345678'",
    "postgresql+psycopg://ecofate:s3cr3t@db:5432/ecofate",  # pragma: allowlist secret
    "postgresql://ecofate:s3cr3t@db/ecofate",  # pragma: allowlist secret
    "Cookie: ecofate_session=Zx81kLmq0PaT3vYb",
    "Set-Cookie: ecofate_session=Zx81kLmq0PaT3vYb; HttpOnly; Path=/",
    "{'cookie': 'ecofate_session=Zx81kLmq0PaT3vYb'}",  # pragma: allowlist secret
    "https://ecofate.example/reset#token=Zx81kLmq0PaT3vYb",
]
HARMLESS = [
    "Benzene 71-43-2",
    "sk-short",
    "the key to the map",
    "input_tokens=1200",
    "https://example.org/docs#usage",
    "https://example.org/docs#section&page=2",
    "the session cookie expires after a day",
    "cookie: it expires tomorrow",
]


@pytest.mark.parametrize("text", SECRETS)
def test_secret_shapes_are_matched(text: str) -> None:
    assert any(pattern.search(text) for pattern in KEY_PATTERNS)


@pytest.mark.parametrize("text", HARMLESS)
def test_ordinary_text_is_not_matched(text: str) -> None:
    assert not any(pattern.search(text) for pattern in KEY_PATTERNS)


def _mask(text: str) -> str:
    return DATABASE_URL_PATTERN.sub(r"\1***\3", text)


@pytest.mark.parametrize(
    "scheme",
    ["postgresql+psycopg", "postgresql", "postgres", "postgresql+asyncpg"],
)
def test_database_password_is_masked_and_the_rest_kept(scheme: str) -> None:
    url = f"{scheme}://ecofate:s3cr3t@db:5432/ecofate"  # pragma: allowlist secret
    assert (
        _mask(f"cannot connect to {url} now")
        == f"cannot connect to {scheme}://ecofate:***@db:5432/ecofate now"
    )


@pytest.mark.parametrize("password", ["p@ss", "a:b", "x@y:z@w"])
def test_a_password_with_at_or_colon_is_masked_whole(password: str) -> None:
    masked = _mask(f"postgresql://ecofate:{password}@db:5432/ecofate")  # pragma: allowlist secret
    assert masked == "postgresql://ecofate:***@db:5432/ecofate"


@pytest.mark.parametrize(
    "text",
    [
        "postgresql://ecofate@db:5432/ecofate",
        "postgresql://db:5432/ecofate",
        "postgresql:///ecofate",
    ],
)
def test_a_url_without_a_password_is_unchanged(text: str) -> None:
    assert _mask(text) == text


def test_cookie_value_goes_and_the_header_name_stays() -> None:
    text = "Set-Cookie: ecofate_session=Zx81kLmq0PaT3vYb; HttpOnly"
    assert COOKIE_PATTERN.sub(r"\1***", text) == "Set-Cookie: ***"


def test_cookie_header_inside_a_dict_keeps_its_quotes() -> None:
    text = "{'cookie': 'ecofate_session=Zx81kLmq0PaT3vYb'}"  # pragma: allowlist secret
    assert COOKIE_PATTERN.sub(r"\1***", text) == "{'cookie': '***'}"


def test_fragment_token_goes_and_the_address_stays() -> None:
    text = "see https://ecofate.example/verify#token=Zx81kLmq0PaT3vYb now"
    assert (
        FRAGMENT_TOKEN_PATTERN.sub(r"\1***", text)
        == "see https://ecofate.example/verify#token=*** now"
    )


def test_fragment_token_after_another_fragment_parameter() -> None:
    text = "https://ecofate.example/reset#email=a&token=Zx81kLmq0PaT3vYb"
    assert "Zx81kLmq0PaT3vYb" not in FRAGMENT_TOKEN_PATTERN.sub(r"\1***", text)
