"""create turns table

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOW = sa.text("now()")
_OPEN = sa.text("status IN ('queued', 'running')")


def _timestamp(name: str, *, required: bool) -> sa.Column[object]:
    default = _NOW if required else None
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=default,
        nullable=not required,
    )


def _checks() -> tuple[sa.CheckConstraint, ...]:
    return (
        sa.CheckConstraint(
            "(status IN ('interrupted', 'failed')) = (reason IS NOT NULL)",
            name=op.f("ck_turns_reason_matches_status"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'interrupted', 'completed', 'failed')",
            name=op.f("ck_turns_status_known"),
        ),
        sa.CheckConstraint("resume_count >= 0", name=op.f("ck_turns_resume_count_not_negative")),
    )


def _columns() -> tuple[sa.Column[object], ...]:
    return (
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("thread_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("resume_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        _timestamp("created_at", required=True),
        _timestamp("started_at", required=False),
        _timestamp("updated_at", required=True),
        _timestamp("finished_at", required=False),
    )


def _create_turns() -> None:
    op.create_table(
        "turns",
        *_columns(),
        *_checks(),
        sa.ForeignKeyConstraint(
            ["thread_id"],
            ["threads.id"],
            name=op.f("fk_turns_thread_id_threads"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_turns")),
    )


def _index_turns() -> None:
    op.create_index("ix_turns_thread_id_created_at", "turns", ["thread_id", "created_at"])
    op.create_index(op.f("ix_turns_user_id"), "turns", ["user_id"])
    op.create_index(
        "uq_turns_open_thread",
        "turns",
        ["thread_id"],
        unique=True,
        postgresql_where=_OPEN,
    )


def _add_usage_turn() -> None:
    op.add_column("thread_usage", sa.Column("turn_id", sa.Text(), nullable=True))
    op.create_index(op.f("ix_thread_usage_turn_id"), "thread_usage", ["turn_id"])
    op.create_foreign_key(
        op.f("fk_thread_usage_turn_id_turns"),
        "thread_usage",
        "turns",
        ["turn_id"],
        ["id"],
        ondelete="CASCADE",
    )


def upgrade() -> None:
    _create_turns()
    _index_turns()
    _add_usage_turn()


def downgrade() -> None:
    op.drop_constraint(op.f("fk_thread_usage_turn_id_turns"), "thread_usage", type_="foreignkey")
    op.drop_index(op.f("ix_thread_usage_turn_id"), table_name="thread_usage")
    op.drop_column("thread_usage", "turn_id")
    op.drop_index("uq_turns_open_thread", table_name="turns", postgresql_where=_OPEN)
    op.drop_index(op.f("ix_turns_user_id"), table_name="turns")
    op.drop_index("ix_turns_thread_id_created_at", table_name="turns")
    op.drop_table("turns")
