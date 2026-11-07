"""Tests for the engine factory and the URL lookup (no database is contacted)."""

from __future__ import annotations

import pytest

from config.database import DatabaseSettings
from storage.engine import DatabaseSetupError, create_engine, database_url

SETTINGS = DatabaseSettings(
    url_env_var="TEST_DATABASE_URL",
    pool_size=3,
    pool_timeout_seconds=7.0,
    statement_timeout_seconds=12.5,
    health_timeout_seconds=1.0,
    turn_lease_seconds=300.0,
    thread_retention_days=30,
    purge_interval_minutes=60,
)
URL = "postgresql://ecofate:s3cr3t@db:5432/ecofate"  # pragma: allowlist secret
DRIVER_URL = "postgresql+psycopg://ecofate:s3cr3t@db:5432/ecofate"  # pragma: allowlist secret


def test_url_is_read_from_the_named_variable() -> None:
    assert database_url({"TEST_DATABASE_URL": f" {URL} "}, SETTINGS) == URL


@pytest.mark.parametrize("environ", [{}, {"TEST_DATABASE_URL": ""}, {"TEST_DATABASE_URL": "  "}])
def test_missing_or_blank_url_names_the_variable(environ: dict[str, str]) -> None:
    with pytest.raises(DatabaseSetupError, match="TEST_DATABASE_URL"):
        database_url(environ, SETTINGS)


def test_other_variables_are_not_consulted() -> None:
    with pytest.raises(DatabaseSetupError):
        database_url({"DATABASE_URL": URL}, SETTINGS)


def test_engine_uses_psycopg_and_the_pool_settings() -> None:
    engine = create_engine(URL, SETTINGS)
    assert engine.url.drivername == "postgresql+psycopg"
    assert engine.sync_engine.pool.size() == 3  # type: ignore[attr-defined]
    assert engine.sync_engine.pool.timeout() == 7.0  # type: ignore[attr-defined]


def test_engine_hides_parameters_and_sets_the_statement_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def capture(url: str, **kwargs: object) -> object:
        seen.update(kwargs, url=url)
        return object()

    monkeypatch.setattr("storage.engine.create_async_engine", capture)
    create_engine(URL, SETTINGS)
    assert seen["hide_parameters"] is True
    assert seen["connect_args"] == {"options": "-c statement_timeout=12500"}
    assert seen["url"] == DRIVER_URL


def test_engine_rejects_a_non_postgres_url_without_echoing_it() -> None:
    with pytest.raises(DatabaseSetupError) as error:
        create_engine("mysql://user:topsecret@h/db", SETTINGS)  # pragma: allowlist secret
    assert "topsecret" not in str(error.value)
