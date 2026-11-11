"""add the background worker's turn columns

Adds ``turns.heartbeat_at`` (when the worker running a turn last reported it alive),
``turns.cancel_requested`` (the user asked to stop it) and ``turns.planned_input`` (a new turn's
input, read by the worker so task messages carry ids only). Existing turns start without a
heartbeat, not cancelled and without an input. The downgrade drops the three columns.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("turns", sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "turns",
        sa.Column(
            "cancel_requested",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column("turns", sa.Column("planned_input", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("turns", "planned_input")
    op.drop_column("turns", "cancel_requested")
    op.drop_column("turns", "heartbeat_at")
