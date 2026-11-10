"""add user accounts and per-user threads

Creates ``users``, ``sessions``, ``auth_tokens`` and ``login_attempts``, and makes every
conversation table belong to one user: ``threads`` is keyed by ``(owner_id, id)`` and the other
tables refer to it through the composite key ``(owner_id, thread_id)`` (``turns`` calls its
owner column ``user_id``).

Threads made before accounts have no owner, so the upgrade deletes them, with their turns, usage
and checkpoints (local scratch data). The downgrade drops the accounts and deletes every thread
too: two users may share a thread id, which the old key cannot hold.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOW = sa.text("now()")
_ROLES = "'user', 'admin'"
_PURPOSES = "'verify_email', 'reset_password'"
# Tables that belong to one thread through (owner column, thread_id), and their owner column.
_OWNED = {
    "turns": "user_id",
    "thread_usage": "owner_id",
    "thread_tool_messages": "owner_id",
    "thread_workspaces": "owner_id",
    "thread_pending": "owner_id",
    "thread_answers": "owner_id",
}
_USER_COLUMN_TABLES = ("threads", *(t for t in _OWNED if t != "turns"))
# Primary keys of the tables whose key includes the thread, before and after.
_KEYED = {
    "thread_workspaces": ["thread_id"],
    "thread_pending": ["thread_id"],
    "thread_answers": ["thread_id", "key"],
}
_SEQ_TABLES = ("thread_usage", "thread_tool_messages")
_OPEN = sa.text("status IN ('queued', 'running')")
_CHECKPOINT_TABLES = ("checkpoints", "checkpoint_blobs", "checkpoint_writes")


def _created_at() -> sa.Column[object]:
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False)


def _expiry(name: str) -> sa.Column[object]:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False)


def _user_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["user_id"],
        ["users.id"],
        name=op.f(f"fk_{table}_user_id_users"),
        ondelete="CASCADE",
    )


def _create_users() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), server_default="user", nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        sa.CheckConstraint(f"role IN ({_ROLES})", name=op.f("ck_users_role_known")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )


def _create_sessions() -> None:
    op.create_table(
        "sessions",
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        _created_at(),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        _expiry("idle_expires_at"),
        _expiry("absolute_expires_at"),
        _user_fk("sessions"),
        sa.PrimaryKeyConstraint("token_hash", name=op.f("pk_sessions")),
    )
    op.create_index(op.f("ix_sessions_user_id"), "sessions", ["user_id"])


def _create_auth_tokens() -> None:
    op.create_table(
        "auth_tokens",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        _expiry("expires_at"),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        sa.CheckConstraint(f"purpose IN ({_PURPOSES})", name=op.f("ck_auth_tokens_purpose_known")),
        _user_fk("auth_tokens"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_auth_tokens_token_hash")),
    )
    op.create_index("ix_auth_tokens_user_id_purpose", "auth_tokens", ["user_id", "purpose"])


def _create_login_attempts() -> None:
    op.create_table(
        "login_attempts",
        sa.Column("key", sa.Text(), nullable=False),
        _expiry("window_start"),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.CheckConstraint("count >= 1", name=op.f("ck_login_attempts_count_positive")),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_login_attempts")),
    )


def _delete_threads() -> None:
    """Delete every thread (the foreign keys cascade) and the checkpointer's rows, if any."""
    op.execute("DELETE FROM threads")
    names = ", ".join(f"'{name}'" for name in _CHECKPOINT_TABLES)
    op.execute(
        f"""
        DO $$
        DECLARE name text;
        BEGIN
            FOREACH name IN ARRAY ARRAY[{names}] LOOP
                IF to_regclass(name) IS NOT NULL THEN
                    EXECUTE format('TRUNCATE %I', name);
                END IF;
            END LOOP;
        END $$
        """,
    )


def _drop_old_keys() -> None:
    """Drop what depends on ``threads.id`` alone: the foreign keys, keys and indexes."""
    for table in _OWNED:
        op.drop_constraint(op.f(f"fk_{table}_thread_id_threads"), table, type_="foreignkey")
    op.drop_index("uq_turns_open_thread", table_name="turns", postgresql_where=_OPEN)
    op.drop_index("ix_turns_thread_id_created_at", table_name="turns")
    op.drop_index(op.f("ix_turns_user_id"), table_name="turns")
    for table in _KEYED:
        op.drop_constraint(op.f(f"pk_{table}"), table, type_="primary")
    for table in _SEQ_TABLES:
        op.drop_constraint(op.f(f"uq_{table}_thread_id_seq"), table, type_="unique")
    op.drop_constraint(op.f("pk_threads"), "threads", type_="primary")
    for table in _USER_COLUMN_TABLES:
        op.drop_index(op.f(f"ix_{table}_user_id"), table_name=table)


def _own_columns() -> None:
    """``user_id`` becomes the required ``owner_id`` (``turns`` keeps its name)."""
    for table in _USER_COLUMN_TABLES:
        op.alter_column(table, "user_id", new_column_name="owner_id", nullable=False)
    op.alter_column("turns", "user_id", nullable=False)


def _thread_foreign_keys() -> None:
    for table, owner in _OWNED.items():
        op.create_foreign_key(
            op.f(f"fk_{table}_{owner}_threads"),
            table,
            "threads",
            [owner, "thread_id"],
            ["owner_id", "id"],
            ondelete="CASCADE",
        )


def _add_new_keys() -> None:
    """Key every table by its owner and thread, with the composite foreign keys and indexes."""
    op.create_primary_key(op.f("pk_threads"), "threads", ["owner_id", "id"])
    op.create_foreign_key(
        op.f("fk_threads_owner_id_users"),
        "threads",
        "users",
        ["owner_id"],
        ["id"],
        ondelete="CASCADE",
    )
    _thread_foreign_keys()
    for table, columns in _KEYED.items():
        op.create_primary_key(op.f(f"pk_{table}"), table, ["owner_id", *columns])
    for table in _SEQ_TABLES:
        name = op.f(f"uq_{table}_owner_id_thread_id_seq")
        op.create_unique_constraint(name, table, ["owner_id", "thread_id", "seq"])
    _index_turns()


def _index_turns() -> None:
    op.create_index(
        "uq_turns_open_thread",
        "turns",
        ["user_id", "thread_id"],
        unique=True,
        postgresql_where=_OPEN,
    )
    op.create_index(
        "ix_turns_user_id_thread_id_created_at",
        "turns",
        ["user_id", "thread_id", "created_at"],
    )


def upgrade() -> None:
    _create_users()
    _create_sessions()
    _create_auth_tokens()
    _create_login_attempts()
    _delete_threads()
    _drop_old_keys()
    _own_columns()
    _add_new_keys()


def _drop_new_keys() -> None:
    op.drop_index("ix_turns_user_id_thread_id_created_at", table_name="turns")
    op.drop_index("uq_turns_open_thread", table_name="turns", postgresql_where=_OPEN)
    for table in _SEQ_TABLES:
        name = op.f(f"uq_{table}_owner_id_thread_id_seq")
        op.drop_constraint(name, table, type_="unique")
    for table in _KEYED:
        op.drop_constraint(op.f(f"pk_{table}"), table, type_="primary")
    for table, owner in _OWNED.items():
        op.drop_constraint(op.f(f"fk_{table}_{owner}_threads"), table, type_="foreignkey")
    op.drop_constraint(op.f("fk_threads_owner_id_users"), "threads", type_="foreignkey")
    op.drop_constraint(op.f("pk_threads"), "threads", type_="primary")


def _restore_user_columns() -> None:
    for table in _USER_COLUMN_TABLES:
        op.alter_column(table, "owner_id", new_column_name="user_id", nullable=True)
    op.alter_column("turns", "user_id", nullable=True)


def _restore_old_keys() -> None:
    op.create_primary_key(op.f("pk_threads"), "threads", ["id"])
    for table in _OWNED:
        op.create_foreign_key(
            op.f(f"fk_{table}_thread_id_threads"),
            table,
            "threads",
            ["thread_id"],
            ["id"],
            ondelete="CASCADE",
        )
    for table, columns in _KEYED.items():
        op.create_primary_key(op.f(f"pk_{table}"), table, columns)
    for table in _SEQ_TABLES:
        op.create_unique_constraint(op.f(f"uq_{table}_thread_id_seq"), table, ["thread_id", "seq"])
    _restore_indexes()


def _restore_indexes() -> None:
    for table in ("turns", *_USER_COLUMN_TABLES):
        op.create_index(op.f(f"ix_{table}_user_id"), table, ["user_id"])
    op.create_index("ix_turns_thread_id_created_at", "turns", ["thread_id", "created_at"])
    op.create_index(
        "uq_turns_open_thread",
        "turns",
        ["thread_id"],
        unique=True,
        postgresql_where=_OPEN,
    )


def downgrade() -> None:
    _delete_threads()
    _drop_new_keys()
    _restore_user_columns()
    _restore_old_keys()
    op.drop_table("login_attempts")
    op.drop_index("ix_auth_tokens_user_id_purpose", table_name="auth_tokens")
    op.drop_table("auth_tokens")
    op.drop_index(op.f("ix_sessions_user_id"), table_name="sessions")
    op.drop_table("sessions")
    op.drop_table("users")
