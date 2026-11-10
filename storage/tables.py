"""The program's tables (SQLAlchemy Core). Changed only through a new Alembic revision.

Accounts: ``users``, ``sessions``, ``auth_tokens`` and ``login_attempts``. Every conversation
table belongs to one user: ``threads`` is keyed by ``(owner_id, id)`` (two users may pick the
same thread id) and every other table refers to it through the composite foreign key
``(owner_id, thread_id)``, which cascades, so deleting a thread or its user deletes everything
stored for it. ``thread_id`` follows the same pattern the API accepts. ``turns`` names its owner
column ``user_id``.
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
    ForeignKeyConstraint,
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

from storage.account_model import Role, TokenPurpose
from storage.turn_model import OPEN_STATUSES, REASONED_STATUSES, TurnStatus

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


def _created_at(name: str = "created_at") -> Column[object]:
    return Column(name, DateTime(timezone=True), nullable=False, server_default=func.now())


def _timestamp(name: str) -> Column[object]:
    return Column(name, DateTime(timezone=True), nullable=False)


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _owned_thread(
    owner: str = "owner_id",
    *,
    primary_key: bool = False,
) -> tuple[Column[object], Column[str], ForeignKeyConstraint]:
    """The owner and thread columns of a table that belongs to one thread, and their key."""
    return (
        Column(owner, Uuid, nullable=False, primary_key=primary_key),
        Column("thread_id", Text, nullable=False, primary_key=primary_key),
        ForeignKeyConstraint(
            [owner, "thread_id"],
            ["threads.owner_id", "threads.id"],
            ondelete="CASCADE",
        ),
    )


users = Table(
    "users",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("email", Text, nullable=False),
    Column("password_hash", Text, nullable=False),
    Column("role", Text, nullable=False, server_default=Role.USER.value),
    Column("verified_at", DateTime(timezone=True), nullable=True),
    _created_at(),
    UniqueConstraint("email"),
    CheckConstraint(f"role IN ({_in(tuple(Role))})", name="role_known"),
)

# The session token itself is never stored: only its SHA-256 hash, so a leaked row is no cookie.
sessions = Table(
    "sessions",
    metadata,
    Column("token_hash", Text, primary_key=True),
    Column("user_id", Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
    _created_at(),
    _created_at("last_seen_at"),
    _timestamp("idle_expires_at"),
    _timestamp("absolute_expires_at"),
)

# Single-use emailed tokens (verification and recovery), stored as hashes like sessions.
auth_tokens = Table(
    "auth_tokens",
    metadata,
    Column("id", BigInteger, Identity(), primary_key=True),
    Column("purpose", Text, nullable=False),
    Column("user_id", Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("token_hash", Text, nullable=False),
    _timestamp("expires_at"),
    Column("used_at", DateTime(timezone=True), nullable=True),
    _created_at(),
    UniqueConstraint("token_hash"),
    CheckConstraint(f"purpose IN ({_in(tuple(TokenPurpose))})", name="purpose_known"),
    Index("ix_auth_tokens_user_id_purpose", "user_id", "purpose"),
)

# Failed sign-in and recovery attempts per key (``email:<address>`` or ``ip:<address>``).
login_attempts = Table(
    "login_attempts",
    metadata,
    Column("key", Text, primary_key=True),
    _timestamp("window_start"),
    Column("count", Integer, nullable=False),
    CheckConstraint("count >= 1", name="count_positive"),
)

threads = Table(
    "threads",
    metadata,
    Column("owner_id", Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("id", Text, primary_key=True),
    _created_at(),
    _created_at("last_used_at"),
    Column("busy_until", DateTime(timezone=True), nullable=True),
    CheckConstraint(f"id ~ '{THREAD_ID_REGEX}'", name="id_pattern"),
    Index("ix_threads_last_used_at", "last_used_at"),
)

_OPEN_VALUES = _in(tuple(str(status) for status in OPEN_STATUSES))

turns = Table(
    "turns",
    metadata,
    Column("id", Text, primary_key=True),
    *_owned_thread("user_id"),
    Column("status", Text, nullable=False),
    Column("reason", Text, nullable=True),
    Column("resume_count", Integer, nullable=False, server_default=text("0")),
    _created_at(),
    Column("started_at", DateTime(timezone=True), nullable=True),
    _created_at("updated_at"),
    Column("finished_at", DateTime(timezone=True), nullable=True),
    CheckConstraint(f"status IN ({_in(tuple(TurnStatus))})", name="status_known"),
    CheckConstraint("resume_count >= 0", name="resume_count_not_negative"),
    CheckConstraint(
        f"(status IN ({_in(tuple(str(s) for s in REASONED_STATUSES))})) = (reason IS NOT NULL)",
        name="reason_matches_status",
    ),
    # At most one turn per thread of a user holds the thread (queued or running), across every
    # process.
    Index(
        "uq_turns_open_thread",
        "user_id",
        "thread_id",
        unique=True,
        postgresql_where=text(f"status IN ({_OPEN_VALUES})"),
    ),
    Index("ix_turns_user_id_thread_id_created_at", "user_id", "thread_id", "created_at"),
)

thread_usage = Table(
    "thread_usage",
    metadata,
    Column("id", BigInteger, Identity(), primary_key=True),
    *_owned_thread(),
    # The turn whose model call this was (None for calls recorded before turns existed).
    Column("turn_id", Text, ForeignKey("turns.id", ondelete="CASCADE"), nullable=True, index=True),
    Column("seq", Integer, nullable=False),
    Column("model", Text, nullable=False),
    Column("input_tokens", BigInteger, nullable=True),
    Column("cached_input_tokens", BigInteger, nullable=False),
    Column("output_tokens", BigInteger, nullable=True),
    _created_at(),
    UniqueConstraint("owner_id", "thread_id", "seq"),
    CheckConstraint("seq >= 0", name="seq_not_negative"),
)

thread_tool_messages = Table(
    "thread_tool_messages",
    metadata,
    Column("id", BigInteger, Identity(), primary_key=True),
    *_owned_thread(),
    Column("seq", Integer, nullable=False),
    Column("message", JSONB, nullable=False),
    UniqueConstraint("owner_id", "thread_id", "seq"),
    CheckConstraint("seq >= 0", name="seq_not_negative"),
)

thread_workspaces = Table(
    "thread_workspaces",
    metadata,
    *_owned_thread(primary_key=True),
    Column("state", JSONB, nullable=False),
    _created_at("updated_at"),
)

thread_pending = Table(
    "thread_pending",
    metadata,
    *_owned_thread(primary_key=True),
    Column("request", JSONB, nullable=False),
    _created_at(),
)

thread_answers = Table(
    "thread_answers",
    metadata,
    *_owned_thread(primary_key=True),
    Column("key", Text, primary_key=True),
    Column("value", Double, nullable=True),
    Column("declined", Boolean, nullable=False, server_default=text("false")),
    CheckConstraint(
        "(declined AND value IS NULL) OR (NOT declined AND value IS NOT NULL)",
        name="value_xor_declined",
    ),
)

TABLES = (
    users,
    sessions,
    auth_tokens,
    login_attempts,
    threads,
    turns,
    thread_usage,
    thread_tool_messages,
    thread_workspaces,
    thread_pending,
    thread_answers,
)
