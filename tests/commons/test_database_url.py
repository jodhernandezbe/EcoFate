"""Tests for the PostgreSQL URL spellings."""

from __future__ import annotations

import pytest

from commons.database_url import libpq_url, sqlalchemy_url

_REST = "u:p@db:5432/ecofate"  # pragma: allowlist secret


@pytest.mark.parametrize("scheme", ["postgresql+psycopg", "postgresql", "postgres"])
def test_every_accepted_scheme_converts_both_ways(scheme: str) -> None:
    assert sqlalchemy_url(f"{scheme}://{_REST}") == f"postgresql+psycopg://{_REST}"
    assert libpq_url(f"{scheme}://{_REST}") == f"postgresql://{_REST}"


@pytest.mark.parametrize("url", ["", "mysql://u:p@h/db", "sqlite:///x.db", "db:5432/ecofate"])
def test_other_schemes_are_rejected(url: str) -> None:
    with pytest.raises(ValueError, match="postgresql"):
        sqlalchemy_url(url)
    with pytest.raises(ValueError, match="postgresql"):
        libpq_url(url)


def test_rejection_message_does_not_echo_the_url() -> None:
    with pytest.raises(ValueError) as error:
        sqlalchemy_url("mysql://user:topsecret@host/db")  # pragma: allowlist secret
    assert "topsecret" not in str(error.value)
