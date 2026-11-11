"""add the daily turn quota

Creates ``daily_turn_usage`` (a user's counted agent turns per UTC day) and the flag
``turns.quota_refunded`` that keeps a turn from being given back twice. Existing turns start
unflagged. The downgrade drops both.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "daily_turn_usage",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("turns", sa.Integer(), nullable=False),
        sa.CheckConstraint("turns >= 0", name=op.f("ck_daily_turn_usage_turns_not_negative")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_daily_turn_usage_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "day", name=op.f("pk_daily_turn_usage")),
    )
    op.add_column(
        "turns",
        sa.Column("quota_refunded", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("turns", "quota_refunded")
    op.drop_table("daily_turn_usage")
