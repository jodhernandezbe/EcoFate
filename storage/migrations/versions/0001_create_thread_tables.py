"""create thread tables

Revision ID: 0001
Revises:
Create Date: 2026-11-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOW = sa.text("now()")
_THREAD_ID_REGEX = "^[A-Za-z0-9_-]{1,64}$"
# Child tables, in the order they are created (dropped in reverse).
_CHILDREN = (
    "thread_answers",
    "thread_pending",
    "thread_tool_messages",
    "thread_usage",
    "thread_workspaces",
)


def _timestamp(name: str) -> sa.Column[object]:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=_NOW, nullable=False)


def _thread_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["thread_id"],
        ["threads.id"],
        name=op.f(f"fk_{table}_thread_id_threads"),
        ondelete="CASCADE",
    )


def _index_user_id(table: str) -> None:
    op.create_index(op.f(f"ix_{table}_user_id"), table, ["user_id"], unique=False)


def _create_threads() -> None:
    op.create_table(
        "threads",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        _timestamp("created_at"),
        _timestamp("last_used_at"),
        sa.Column("busy_until", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(f"id ~ '{_THREAD_ID_REGEX}'", name=op.f("ck_threads_id_pattern")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_threads")),
    )
    op.create_index("ix_threads_last_used_at", "threads", ["last_used_at"], unique=False)
    _index_user_id("threads")


def _create_answers() -> None:
    op.create_table(
        "thread_answers",
        sa.Column("thread_id", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("value", sa.Double[float](), nullable=True),
        sa.Column("declined", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.CheckConstraint(
            "(declined AND value IS NULL) OR (NOT declined AND value IS NOT NULL)",
            name=op.f("ck_thread_answers_value_xor_declined"),
        ),
        _thread_fk("thread_answers"),
        sa.PrimaryKeyConstraint("thread_id", "key", name=op.f("pk_thread_answers")),
    )


def _create_pending_and_workspaces() -> None:
    for table, column in (("thread_pending", "request"), ("thread_workspaces", "state")):
        op.create_table(
            table,
            sa.Column("thread_id", sa.Text(), nullable=False),
            sa.Column("user_id", sa.Uuid(), nullable=True),
            sa.Column(column, postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            _timestamp("created_at" if table == "thread_pending" else "updated_at"),
            _thread_fk(table),
            sa.PrimaryKeyConstraint("thread_id", name=op.f(f"pk_{table}")),
        )


def _create_tool_messages() -> None:
    op.create_table(
        "thread_tool_messages",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("thread_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("message", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint("seq >= 0", name=op.f("ck_thread_tool_messages_seq_not_negative")),
        _thread_fk("thread_tool_messages"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_thread_tool_messages")),
        sa.UniqueConstraint(
            "thread_id",
            "seq",
            name=op.f("uq_thread_tool_messages_thread_id_seq"),
        ),
    )


def _create_usage() -> None:
    op.create_table(
        "thread_usage",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("thread_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("input_tokens", sa.BigInteger(), nullable=True),
        sa.Column("cached_input_tokens", sa.BigInteger(), nullable=False),
        sa.Column("output_tokens", sa.BigInteger(), nullable=True),
        _timestamp("created_at"),
        sa.CheckConstraint("seq >= 0", name=op.f("ck_thread_usage_seq_not_negative")),
        _thread_fk("thread_usage"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_thread_usage")),
        sa.UniqueConstraint("thread_id", "seq", name=op.f("uq_thread_usage_thread_id_seq")),
    )


def upgrade() -> None:
    _create_threads()
    _create_answers()
    _create_pending_and_workspaces()
    _create_tool_messages()
    _create_usage()
    for table in _CHILDREN:
        _index_user_id(table)


def downgrade() -> None:
    for table in reversed(_CHILDREN):
        op.drop_index(op.f(f"ix_{table}_user_id"), table_name=table)
        op.drop_table(table)
    op.drop_index(op.f("ix_threads_user_id"), table_name="threads")
    op.drop_index("ix_threads_last_used_at", table_name="threads")
    op.drop_table("threads")
