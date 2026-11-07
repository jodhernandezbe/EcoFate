"""Tests for the key-shaped string patterns."""

from __future__ import annotations

import pytest

from commons.key_patterns import DATABASE_URL_PATTERN, KEY_PATTERNS

SECRETS = [
    "sk-abcdefghijklmnop",
    "sk-proj-****p8UA",
    "Authorization: Bearer abcdefgh12345678",
    "https://api.example.test/data?get=x&key=abcdef123456",
    "api_key=abcdefgh12345678",
    "'x-api-key': 'abcdefgh12345678'",
    "postgresql+psycopg://ecofate:s3cr3t@db:5432/ecofate",  # pragma: allowlist secret
    "postgresql://ecofate:s3cr3t@db/ecofate",  # pragma: allowlist secret
]
HARMLESS = ["Benzene 71-43-2", "sk-short", "the key to the map", "input_tokens=1200"]


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
