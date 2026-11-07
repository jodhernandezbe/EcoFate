"""The asynchronous SQLAlchemy engine and the connection URL, read only from the environment."""

from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from commons.database_url import sqlalchemy_url
from config.database import DatabaseSettings

_MS_PER_SECOND = 1000


class DatabaseSetupError(RuntimeError):
    """The database cannot be used as configured; the message is safe to show (no URL)."""


def database_url(environ: Mapping[str, str], settings: DatabaseSettings) -> str:
    """Read the connection URL from the environment variable named in the settings.

    Args:
        environ: The environment (``os.environ``, or a fake in tests).
        settings: Database settings naming the variable.

    Returns:
        The URL exactly as set (it carries the password: never log it).

    Raises:
        DatabaseSetupError: If the variable is missing or blank; the message names it.
    """
    value = environ.get(settings.url_env_var, "").strip()
    if not value:
        raise DatabaseSetupError(
            f"Set {settings.url_env_var} to the PostgreSQL connection URL "
            "(see .env.example) before starting the web program.",
        )
    return value


def create_engine(
    url: str,
    settings: DatabaseSettings,
    *,
    search_path: str | None = None,
) -> AsyncEngine:
    """Build the process's engine; nothing connects until the first statement.

    Bound parameters are hidden from error messages and logs, so a user's answers and messages
    never reach them. Every statement is cancelled by PostgreSQL after the statement timeout.

    Args:
        url: The connection URL (``postgresql://`` or ``postgresql+psycopg://``).
        settings: Pool size, pool timeout (seconds) and statement timeout (seconds).
        search_path: Schema every connection works in (tests isolate themselves with it);
            None keeps the database's default.

    Raises:
        DatabaseSetupError: If the URL is not a PostgreSQL URL (the URL is not echoed).
    """
    try:
        driver_url = sqlalchemy_url(url)
    except ValueError as error:
        raise DatabaseSetupError(str(error)) from None
    options = f"-c statement_timeout={round(settings.statement_timeout_seconds * _MS_PER_SECOND)}"
    if search_path is not None:
        options += f" -c search_path={search_path}"
    return create_async_engine(
        driver_url,
        pool_size=settings.pool_size,
        pool_timeout=settings.pool_timeout_seconds,
        pool_pre_ping=True,
        hide_parameters=True,
        connect_args={"options": options},
    )
