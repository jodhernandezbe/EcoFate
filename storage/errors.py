"""The exceptions a failing or unreachable database raises (caught by name, never broadly)."""

from __future__ import annotations

import psycopg
from sqlalchemy.exc import SQLAlchemyError

# SQLAlchemy wraps driver errors; the checkpointer's own pool raises psycopg's directly.
DATABASE_ERRORS: tuple[type[Exception], ...] = (
    SQLAlchemyError,
    psycopg.Error,
    OSError,
    TimeoutError,
)
