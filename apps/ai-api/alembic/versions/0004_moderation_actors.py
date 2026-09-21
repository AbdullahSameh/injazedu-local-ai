"""moderation actors: telegram_users, moderators, telegram_messages, moderator_group_assignments

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telegram_users",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tg_user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=100), nullable=True),
        sa.Column("display_name", sa.String(length=300), nullable=True),
        sa.Column("is_bot", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("identity_purged_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint("tg_user_id", name="uq_telegram_users_tg_user_id"),
    )

    op.create_table(
        "moderators",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "telegram_user_id",
            sa.BigInteger(),
            sa.ForeignKey("telegram_users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("injaz_user_id", sa.BigInteger(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
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
        sa.UniqueConstraint("telegram_user_id", name="uq_moderators_telegram_user_id"),
    )

    op.create_table(
        "telegram_messages",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "telegram_chat_id",
            sa.BigInteger(),
            sa.ForeignKey("telegram_chats.id"),
            nullable=False,
        ),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "telegram_user_id",
            sa.BigInteger(),
            sa.ForeignKey("telegram_users.id"),
            nullable=True,
        ),
        sa.Column("sender_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reply_to_message_id", sa.BigInteger(), nullable=True),
        sa.Column("message_thread_id", sa.BigInteger(), nullable=True),
        sa.Column("is_service", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "is_from_moderator", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("original_text", sa.Text(), nullable=True),
        sa.Column("normalized_text", sa.Text(), nullable=True),
        sa.Column("text_purged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("media_kind", sa.String(length=20), nullable=True),
        sa.Column(
            "entity_flags",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "source_update_id",
            sa.BigInteger(),
            sa.ForeignKey("telegram_updates.id"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "telegram_chat_id", "message_id", name="uq_telegram_messages_chat_msg"
        ),
        sa.CheckConstraint(
            "NOT (telegram_user_id IS NOT NULL AND sender_chat_id IS NOT NULL)",
            name="ck_telegram_messages_sender",
        ),
        sa.CheckConstraint(
            "is_from_moderator = false OR telegram_user_id IS NOT NULL",
            name="ck_telegram_messages_moderator_needs_user",
        ),
        sa.CheckConstraint(
            "edited_at IS NULL OR edited_at >= sent_at",
            name="ck_telegram_messages_edit_order",
        ),
    )

    op.create_table(
        "moderator_group_assignments",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "telegram_chat_id",
            sa.BigInteger(),
            sa.ForeignKey("telegram_chats.id"),
            nullable=False,
        ),
        sa.Column(
            "moderator_id",
            sa.BigInteger(),
            sa.ForeignKey("moderators.id"),
            nullable=False,
        ),
        sa.Column("assignment_role", sa.String(length=20), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "assignment_role IN ('primary', 'backup')", name="ck_assignment_role"
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from", name="ck_assignment_interval"
        ),
    )

    op.create_index(
        "ix_messages_chat_sent",
        "telegram_messages",
        ["telegram_chat_id", sa.text("sent_at DESC")],
    )
    op.create_index(
        "ix_messages_chat_moderator_sent",
        "telegram_messages",
        ["telegram_chat_id", "is_from_moderator", "sent_at"],
    )
    op.create_index(
        "ix_messages_reply",
        "telegram_messages",
        ["telegram_chat_id", "reply_to_message_id"],
    )
    op.create_index(
        "ix_assignment_chat_from",
        "moderator_group_assignments",
        ["telegram_chat_id", sa.text("valid_from DESC")],
    )
    op.create_index(
        "ix_assignment_moderator",
        "moderator_group_assignments",
        ["moderator_id", sa.text("valid_from DESC")],
    )
    op.create_index(
        "uq_assignment_one_current_primary",
        "moderator_group_assignments",
        ["telegram_chat_id"],
        unique=True,
        postgresql_where=sa.text("assignment_role = 'primary' AND valid_to IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_assignment_one_current_primary", table_name="moderator_group_assignments"
    )
    op.drop_table("moderator_group_assignments")
    op.drop_table("telegram_messages")
    op.drop_table("moderators")
    op.drop_table("telegram_users")
