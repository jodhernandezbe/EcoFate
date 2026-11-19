"""add the background tool jobs table

Adds ``jobs``: one row per heavy tool call run by the tools worker (owner, thread, tool, input,
status, times, heartbeat, cancel flag, result and failure reason). It belongs to a thread through
the composite key ``(owner_id, thread_id)`` and goes with it. The downgrade drops the table.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUSES = "'queued', 'running', 'succeeded', 'failed', 'cancelled', 'interrupted'"
_REASONED = "'failed', 'cancelled', 'interrupted'"
_OPEN = "'queued', 'running'"


def _identity() -> list[sa.Column[object]]:
    return [
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.Text(), nullable=False),
        sa.Column("tool", sa.Text(), nullable=False),
        sa.Column("input", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
    ]


def _progress() -> list[sa.Column[object]]:
    stamp = sa.DateTime(timezone=True)
    return [
        sa.Column("queued_at", stamp, server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", stamp, nullable=True),
        sa.Column("ended_at", stamp, nullable=True),
        sa.Column("heartbeat_at", stamp, nullable=True),
        sa.Column(
            "cancel_requested",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    ]


def _result() -> list[sa.Column[object]]:
    return [
        sa.Column("result_content", postgresql.JSONB(), nullable=True),
        sa.Column("result_artifact", postgresql.JSONB(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
    ]


def _constraints() -> list[sa.schema.SchemaItem]:
    return [
        sa.CheckConstraint(f"status IN ({_STATUSES})", name=op.f("ck_jobs_status_known")),
        sa.CheckConstraint("tool <> ''", name=op.f("ck_jobs_tool_not_blank")),
        sa.CheckConstraint(
            f"(status IN ({_REASONED})) = (failure_reason IS NOT NULL)",
            name=op.f("ck_jobs_reason_matches_status"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id", "thread_id"],
            ["threads.owner_id", "threads.id"],
            name=op.f("fk_jobs_owner_id_threads"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
    ]


def upgrade() -> None:
    op.create_table("jobs", *_identity(), *_progress(), *_result(), *_constraints())
    op.create_index(
        "ix_jobs_owner_id_open",
        "jobs",
        ["owner_id"],
        postgresql_where=sa.text(f"status IN ({_OPEN})"),
    )
    op.create_index(
        "ix_jobs_owner_id_thread_id_queued_at",
        "jobs",
        ["owner_id", "thread_id", "queued_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_jobs_owner_id_thread_id_queued_at", table_name="jobs")
    op.drop_index("ix_jobs_owner_id_open", table_name="jobs")
    op.drop_table("jobs")
