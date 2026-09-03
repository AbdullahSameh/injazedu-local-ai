"""baseline: assert the vector extension, create users

Revision ID: 0001
Revises:
Create Date: 2026-09-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    ext_version = conn.execute(
        sa.text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
    ).scalar_one_or_none()
    if ext_version is None:
        raise RuntimeError(
            "The 'vector' extension is not installed. It is created by the database image's "
            "init SQL (infra/postgres/initdb/00-extensions.sql) as the superuser on first boot — "
            "this migration asserts it, it never creates it (research D-03)."
        )

    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False, unique=True),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("password", sa.String(length=255), nullable=False),
        sa.Column(
            "is_panel_operator", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column("remember_token", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("users")
