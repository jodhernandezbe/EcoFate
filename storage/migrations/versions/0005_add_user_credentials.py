"""add per-user sealed credentials

Creates ``user_credentials``: one AES-256-GCM sealed secret per ``(user, purpose)`` (the user's
OpenAI key), with the id of the key-encryption key that sealed it. Rows cascade with the user.
The downgrade drops the table (users re-enter their key).

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns() -> list[sa.Column[object]]:
    return [
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("kek_id", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "user_credentials",
        *_columns(),
        sa.CheckConstraint("length(nonce) = 12", name=op.f("ck_user_credentials_nonce_96_bits")),
        sa.CheckConstraint("purpose <> ''", name=op.f("ck_user_credentials_purpose_not_blank")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_credentials_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "purpose", name=op.f("pk_user_credentials")),
    )
    op.create_index("ix_user_credentials_kek_id", "user_credentials", ["kek_id"])


def downgrade() -> None:
    op.drop_index("ix_user_credentials_kek_id", table_name="user_credentials")
    op.drop_table("user_credentials")
