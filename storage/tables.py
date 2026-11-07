"""The program's tables (SQLAlchemy Core). Changed only through a new Alembic revision.

Every table has a ``user_id`` (nullable and indexed until accounts exist) and, except
``threads`` itself, a ``thread_id`` that cascades from ``threads`` so deleting a thread deletes
everything stored for it. ``thread_id`` follows the same pattern the API accepts.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Double,
    ForeignKey,
    Identity,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

# Stable constraint names, so migrations and the models agree on them.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
THREAD_ID_REGEX = "^[A-Za-z0-9_-]{1,64}$"
metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _user_id() -> Column[object]:
    return Column("user_id", Uuid, nullable=True, index=True)


def _thread_id(*, primary_key: bool = False) -> Column[str]:
    return Column(
        "thread_id",
        Text,
        ForeignKey("threads.id", ondelete="CASCADE"),
        nullable=False,
        primary_key=primary_key,
    )


def _created_at(name: str = "created_at") -> Column[object]:
    return Column(name, DateTime(timezone=True), nullable=False, server_default=func.now())


threads = Table(
    "threads",
    metadata,
    Column("id", Text, primary_key=True),
    _user_id(),
    _created_at(),
    _created_at("last_used_at"),
    Column("busy_until", DateTime(timezone=True), nullable=True),
    CheckConstraint(f"id ~ '{THREAD_ID_REGEX}'", name="id_pattern"),
    Index("ix_threads_last_used_at", "last_used_at"),
)

thread_usage = Table(
    "thread_usage",
    metadata,
    Column("id", BigInteger, Identity(), primary_key=True),
    _thread_id(),
    _user_id(),
    Column("seq", Integer, nullable=False),
    Column("model", Text, nullable=False),
    Column("input_tokens", BigInteger, nullable=True),
    Column("cached_input_tokens", BigInteger, nullable=False),
    Column("output_tokens", BigInteger, nullable=True),
    _created_at(),
    UniqueConstraint("thread_id", "seq"),
    CheckConstraint("seq >= 0", name="seq_not_negative"),
)

thread_tool_messages = Table(
    "thread_tool_messages",
    metadata,
    Column("id", BigInteger, Identity(), primary_key=True),
    _thread_id(),
    _user_id(),
    Column("seq", Integer, nullable=False),
    Column("message", JSONB, nullable=False),
    UniqueConstraint("thread_id", "seq"),
    CheckConstraint("seq >= 0", name="seq_not_negative"),
)

thread_workspaces = Table(
    "thread_workspaces",
    metadata,
    _thread_id(primary_key=True),
    _user_id(),
    Column("state", JSONB, nullable=False),
    _created_at("updated_at"),
)

thread_pending = Table(
    "thread_pending",
    metadata,
    _thread_id(primary_key=True),
    _user_id(),
    Column("request", JSONB, nullable=False),
    _created_at(),
)

thread_answers = Table(
    "thread_answers",
    metadata,
    _thread_id(primary_key=True),
    Column("key", Text, primary_key=True),
    _user_id(),
    Column("value", Double, nullable=True),
    Column("declined", Boolean, nullable=False, server_default=text("false")),
    CheckConstraint(
        "(declined AND value IS NULL) OR (NOT declined AND value IS NOT NULL)",
        name="value_xor_declined",
    ),
)

TABLES = (
    threads,
    thread_usage,
    thread_tool_messages,
    thread_workspaces,
    thread_pending,
    thread_answers,
)
