"""The migration scripts and the revision a database is at (read-only helpers)."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Connection

ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"


def alembic_config() -> Config:
    """Alembic's configuration, from ``alembic.ini`` at the project root."""
    return Config(str(ALEMBIC_INI))


def head_revision(config: Config | None = None) -> str | None:
    """The newest revision the migration scripts define (None when there are none)."""
    return ScriptDirectory.from_config(config or alembic_config()).get_current_head()


def current_revision(connection: Connection) -> str | None:
    """The revision the connected database is at (None when nothing was applied)."""
    return MigrationContext.configure(connection).get_current_revision()


def is_at_head(connection: Connection, config: Config | None = None) -> bool:
    """Whether the connected database is at the newest revision."""
    return current_revision(connection) == head_revision(config)
