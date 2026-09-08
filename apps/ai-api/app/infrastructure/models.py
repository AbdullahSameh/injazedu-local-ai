"""SQLAlchemy Core table metadata for `model_profiles` and `model_runs` (Alembic revision 0002).

Core `Table` objects, not ORM-mapped classes: `domain/model_profile.py` stays a plain frozen
dataclass with no ORM import, and callers build one from a row explicitly.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

metadata = sa.MetaData()

model_profiles = sa.Table(
    "model_profiles",
    metadata,
    sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
    sa.Column("name", sa.String(length=100), nullable=False, unique=True),
    sa.Column("provider", sa.String(length=30), nullable=False),
    sa.Column("base_url", sa.String(length=500), nullable=True),
    sa.Column("model", sa.String(length=200), nullable=False),
    sa.Column("role", sa.String(length=20), nullable=False),
    sa.Column("params", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column("dim", sa.Integer(), nullable=True),
    sa.Column("api_key_env", sa.String(length=100), nullable=True),
    sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
    sa.Column("notes", sa.Text(), nullable=True),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Column(
        "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
)

model_runs = sa.Table(
    "model_runs",
    metadata,
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
    sa.Column("attempts", sa.SmallInteger(), nullable=False, server_default=sa.text("1")),
    sa.Column("ok", sa.Boolean(), nullable=False),
    sa.Column("error_type", sa.String(length=60), nullable=True),
    sa.Column("error_detail", sa.Text(), nullable=True),
    sa.Column("request_digest", sa.CHAR(length=64), nullable=False),
    sa.Column("request_payload", JSONB(), nullable=True),
    sa.Column("response_payload", JSONB(), nullable=True),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
)
