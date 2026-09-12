"""moderation ingest: telegram_updates, ingestion_state, ingestion_gaps, telegram_chats

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telegram_updates",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("bot_id", sa.BigInteger(), nullable=False),
        sa.Column("update_id", sa.BigInteger(), nullable=False),
        sa.Column("update_type", sa.String(length=40), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("process_error", sa.Text(), nullable=True),
        sa.Column("payload_purged_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("bot_id", "update_id", name="uq_telegram_updates_bot_update"),
        sa.CheckConstraint(
            "update_type IN ('message', 'edited_message', 'my_chat_member', 'chat_member', "
            "'message_reaction', 'callback_query', 'unknown')",
            name="ck_telegram_updates_type",
        ),
    )
    op.create_index(
        "ix_telegram_updates_pending",
        "telegram_updates",
        ["received_at"],
        postgresql_where=sa.text("processed_at IS NULL"),
    )
    op.create_index(
        "ix_telegram_updates_chat_received",
        "telegram_updates",
        ["chat_id", sa.text("received_at DESC")],
    )

    op.create_table(
        "ingestion_state",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("bot_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("bot_username", sa.String(length=100), nullable=True),
        sa.Column("last_update_id", sa.BigInteger(), nullable=True),
        sa.Column("last_poll_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "consecutive_failures", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "consecutive_conflicts", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("stood_down_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("allowed_updates", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "ingestion_gaps",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("bot_id", sa.BigInteger(), nullable=False),
        sa.Column("gap_start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("gap_end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.String(length=30), nullable=False),
        sa.Column("unrecoverable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "reason IN ('downtime', 'update_id_jump', 'conflict_409', 'unrecoverable_24h', "
            "'update_id_reset')",
            name="ck_ingestion_gaps_reason",
        ),
    )
    op.create_index(
        "ix_ingestion_gaps_window",
        "ingestion_gaps",
        ["bot_id", sa.text("gap_start_at DESC")],
    )

    op.create_table(
        "telegram_chats",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_type", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=True),
        sa.Column("username", sa.String(length=100), nullable=True),
        sa.Column("is_monitored", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "bot_status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'unknown'"),
        ),
        sa.Column("bot_status_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("bot_can_delete", sa.Boolean(), nullable=True),
        sa.Column("migrated_to_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("migrated_from_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("injaz_course_id", sa.BigInteger(), nullable=True),
        sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint("chat_id", name="uq_telegram_chats_chat_id"),
        sa.CheckConstraint(
            "bot_status IN ('member', 'administrator', 'left', 'kicked', 'restricted', "
            "'unknown')",
            name="ck_telegram_chats_bot_status",
        ),
    )
    op.create_index(
        "ix_telegram_chats_monitored",
        "telegram_chats",
        ["is_monitored", "last_event_at"],
    )


def downgrade() -> None:
    op.drop_table("telegram_chats")
    op.drop_table("ingestion_gaps")
    op.drop_table("ingestion_state")
    op.drop_table("telegram_updates")
