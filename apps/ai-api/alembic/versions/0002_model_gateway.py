"""model gateway: model_profiles, model_runs

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_profiles",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=True),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column(
            "params",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("dim", sa.Integer(), nullable=True),
        sa.Column("api_key_env", sa.String(length=100), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("notes", sa.Text(), nullable=True),
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
        sa.UniqueConstraint("name", name="uq_model_profiles_name"),
        sa.CheckConstraint(
            "role IN ('llm', 'embedding')", name="ck_model_profiles_role"
        ),
        sa.CheckConstraint(
            "provider IN ('ollama', 'vllm', 'fake')", name="ck_model_profiles_provider"
        ),
        sa.CheckConstraint(
            "(role = 'embedding') = (dim IS NOT NULL) AND (dim IS NULL OR dim > 0)",
            name="ck_model_profiles_dim",
        ),
    )
    op.create_index(
        "uq_model_profiles_one_active_per_role",
        "model_profiles",
        ["role"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )

    op.create_table(
        "model_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "model_profile_id",
            sa.BigInteger(),
            sa.ForeignKey("model_profiles.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("job_id", sa.BigInteger(), nullable=True),
        sa.Column("prompt_version_id", sa.BigInteger(), nullable=True),
        sa.Column("operation", sa.String(length=30), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column(
            "attempts", sa.SmallInteger(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("error_type", sa.String(length=60), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("request_digest", sa.CHAR(length=64), nullable=False),
        sa.Column("request_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("response_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "operation IN ('generate_text', 'generate_structured', 'embed', 'embed_many')",
            name="ck_model_runs_operation",
        ),
    )
    op.create_index(
        "ix_model_runs_profile_created_at",
        "model_runs",
        ["model_profile_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_model_runs_created_at", "model_runs", [sa.text("created_at DESC")]
    )
    op.create_index(
        "ix_model_runs_request_digest", "model_runs", ["request_digest"]
    )


def downgrade() -> None:
    op.drop_table("model_runs")
    op.drop_index("uq_model_profiles_one_active_per_role", table_name="model_profiles")
    op.drop_table("model_profiles")
