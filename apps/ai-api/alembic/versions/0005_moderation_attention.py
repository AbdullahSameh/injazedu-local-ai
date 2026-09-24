"""deterministic response tracking: attention_items, telegram_messages attention columns

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-23

data-model.md §1-§2. **Finding 2** (D-TG-71): the anchor is `UNIQUE (telegram_chat_id,
telegram_message_id)`, not `telegram_message_id` alone as the source plan's §10.7 prints —
Telegram numbers messages per chat from 1, so that constraint collides across groups. No `GRANT`
(`ALTER DEFAULT PRIVILEGES FOR ROLE ai_migrator` already reaches `ai_control`, probe 10). No FK to
`message_classifications` — that table does not exist until `0007`.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "attention_items",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "telegram_chat_id",
            sa.BigInteger(),
            sa.ForeignKey("telegram_chats.id"),
            nullable=False,
        ),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=False),
        sa.Column("message_thread_id", sa.BigInteger(), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("rule_version", sa.SmallInteger(), nullable=True),
        sa.Column("message_classification_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "responsible_moderator_id",
            sa.BigInteger(),
            sa.ForeignKey("moderators.id"),
            nullable=True,
        ),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default=sa.text("'open'")
        ),
        sa.Column("first_response_message_id", sa.BigInteger(), nullable=True),
        sa.Column("first_response_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "first_response_moderator_id",
            sa.BigInteger(),
            sa.ForeignKey("moderators.id"),
            nullable=True,
        ),
        sa.Column("first_response_kind", sa.String(length=20), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("close_reason", sa.String(length=40), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "telegram_chat_id", "telegram_message_id", name="uq_attention_anchor"
        ),
        sa.ForeignKeyConstraint(
            ["telegram_chat_id", "telegram_message_id"],
            ["telegram_messages.telegram_chat_id", "telegram_messages.message_id"],
            name="fk_attention_message",
        ),
        sa.CheckConstraint(
            "source IN ('rule', 'operator', 'ai')", name="ck_attention_source"
        ),
        sa.CheckConstraint(
            "status IN ('open', 'answered', 'dismissed', 'expired')",
            name="ck_attention_status",
        ),
        sa.CheckConstraint(
            "first_response_kind IS NULL OR first_response_kind IN "
            "('direct_reply', 'group_message')",
            name="ck_attention_response_kind",
        ),
        sa.CheckConstraint(
            "status <> 'answered' OR (first_response_at IS NOT NULL "
            "AND first_response_message_id IS NOT NULL AND first_response_kind IS NOT NULL)",
            name="ck_attention_answered_complete",
        ),
        sa.CheckConstraint(
            "first_response_at IS NULL OR first_response_at > opened_at",
            name="ck_attention_response_order",
        ),
        sa.CheckConstraint(
            "(source = 'rule') = (rule_version IS NOT NULL)",
            name="ck_attention_rule_version",
        ),
    )

    op.add_column(
        "telegram_messages",
        sa.Column(
            "attention_item_id",
            sa.BigInteger(),
            sa.ForeignKey("attention_items.id"),
            nullable=True,
        ),
    )
    op.add_column(
        "telegram_messages",
        sa.Column("attention_evaluated_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index(
        "ix_attention_open",
        "attention_items",
        ["opened_at"],
        postgresql_where=sa.text("status = 'open'"),
    )
    op.create_index(
        "ix_attention_chat_thread_open",
        "attention_items",
        ["telegram_chat_id", "message_thread_id", "opened_at"],
        postgresql_where=sa.text("status = 'open'"),
    )
    op.create_index(
        "ix_attention_chat",
        "attention_items",
        ["telegram_chat_id", sa.text("opened_at DESC")],
    )
    op.create_index(
        "ix_attention_moderator",
        "attention_items",
        ["responsible_moderator_id", sa.text("opened_at DESC")],
    )
    op.create_index(
        "ix_messages_unjudged",
        "telegram_messages",
        ["sent_at"],
        postgresql_where=sa.text("attention_evaluated_at IS NULL"),
    )
    op.create_index(
        "ix_messages_attention_item",
        "telegram_messages",
        ["attention_item_id"],
        postgresql_where=sa.text("attention_item_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_messages_attention_item", table_name="telegram_messages")
    op.drop_index("ix_messages_unjudged", table_name="telegram_messages")
    op.drop_index("ix_attention_moderator", table_name="attention_items")
    op.drop_index("ix_attention_chat", table_name="attention_items")
    op.drop_index("ix_attention_chat_thread_open", table_name="attention_items")
    op.drop_index("ix_attention_open", table_name="attention_items")
    op.drop_column("telegram_messages", "attention_evaluated_at")
    op.drop_column("telegram_messages", "attention_item_id")
    op.drop_table("attention_items")
