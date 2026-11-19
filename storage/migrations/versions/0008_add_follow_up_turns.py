"""add the follow-up turn of a background job

Adds ``turns.job_id`` (the background job an automatic follow-up turn explains) with a unique
index over the non-null values, so a job has at most one follow-up, and lets ``turns.status`` be
``waiting`` (a follow-up recorded while its thread was busy). Existing turns have no job. The
downgrade removes waiting turns, the index and the column.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = "'queued', 'running', 'interrupted', 'completed', 'failed'"
_NEW = "'waiting', 'queued', 'running', 'interrupted', 'completed', 'failed'"
_CHECK = "ck_turns_status_known"


def _replace_status_check(statuses: str) -> None:
    op.drop_constraint(op.f(_CHECK), "turns", type_="check")
    op.create_check_constraint(op.f(_CHECK), "turns", f"status IN ({statuses})")


def upgrade() -> None:
    op.add_column("turns", sa.Column("job_id", sa.Text(), nullable=True))
    op.create_index(
        "uq_turns_job_id",
        "turns",
        ["job_id"],
        unique=True,
        postgresql_where=sa.text("job_id IS NOT NULL"),
    )
    _replace_status_check(_NEW)


def downgrade() -> None:
    op.execute("DELETE FROM turns WHERE status = 'waiting'")
    _replace_status_check(_OLD)
    op.drop_index("uq_turns_job_id", table_name="turns")
    op.drop_column("turns", "job_id")
