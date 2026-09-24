"""SQLAlchemy Core table metadata for the TG-M1 ingestion tables (data-model.md §1-§4,
Alembic revision 0003).

Core `Table` objects on the same `metadata` as `app/infrastructure/models.py` — the source
plan's §23 "new sibling on the same metadata". `app/infrastructure/` sits outside the boundary
gate's reverse-check scope and is one of the seven prefixes a moderation module may import, so
this file is shared infrastructure by both the gate's definition and the domain-boundary
contract's, the same status `models.py` already has (data-model.md §0).
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from app.infrastructure.models import metadata

telegram_updates = sa.Table(
    "telegram_updates",
    metadata,
    sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
    sa.Column("bot_id", sa.BigInteger(), nullable=False),
    sa.Column("update_id", sa.BigInteger(), nullable=False),
    sa.Column("update_type", sa.String(length=40), nullable=False),
    sa.Column("chat_id", sa.BigInteger(), nullable=True),
    sa.Column("payload", JSONB(), nullable=False),
    sa.Column(
        "received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
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

sa.Index(
    "ix_telegram_updates_pending",
    telegram_updates.c.received_at,
    postgresql_where=telegram_updates.c.processed_at.is_(None),
)
sa.Index(
    "ix_telegram_updates_chat_received",
    telegram_updates.c.chat_id,
    sa.desc(telegram_updates.c.received_at),
)

ingestion_state = sa.Table(
    "ingestion_state",
    metadata,
    sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
    sa.Column("bot_id", sa.BigInteger(), nullable=False, unique=True),
    sa.Column("bot_username", sa.String(length=100), nullable=True),
    sa.Column("last_update_id", sa.BigInteger(), nullable=True),
    sa.Column("last_poll_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default=sa.text("0")),
    sa.Column("consecutive_conflicts", sa.Integer(), nullable=False, server_default=sa.text("0")),
    sa.Column("stood_down_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("allowed_updates", JSONB(), nullable=False),
    sa.Column(
        "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
)

ingestion_gaps = sa.Table(
    "ingestion_gaps",
    metadata,
    sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
    sa.Column("bot_id", sa.BigInteger(), nullable=False),
    sa.Column("gap_start_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("gap_end_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("reason", sa.String(length=30), nullable=False),
    sa.Column("unrecoverable", sa.Boolean(), nullable=False, server_default=sa.false()),
    sa.Column(
        "detected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Column("note", sa.Text(), nullable=True),
    sa.CheckConstraint(
        "reason IN ('downtime', 'update_id_jump', 'conflict_409', 'unrecoverable_24h', "
        "'update_id_reset')",
        name="ck_ingestion_gaps_reason",
    ),
)

sa.Index(
    "ix_ingestion_gaps_window",
    ingestion_gaps.c.bot_id,
    sa.desc(ingestion_gaps.c.gap_start_at),
)

telegram_chats = sa.Table(
    "telegram_chats",
    metadata,
    sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
    sa.Column("chat_id", sa.BigInteger(), nullable=False),
    sa.Column("chat_type", sa.String(length=20), nullable=False),
    sa.Column("title", sa.String(length=300), nullable=True),
    sa.Column("username", sa.String(length=100), nullable=True),
    sa.Column("is_monitored", sa.Boolean(), nullable=False, server_default=sa.false()),
    sa.Column(
        "bot_status", sa.String(length=20), nullable=False, server_default=sa.text("'unknown'")
    ),
    sa.Column("bot_status_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("bot_can_delete", sa.Boolean(), nullable=True),
    sa.Column("migrated_to_chat_id", sa.BigInteger(), nullable=True),
    sa.Column("migrated_from_chat_id", sa.BigInteger(), nullable=True),
    sa.Column("injaz_course_id", sa.BigInteger(), nullable=True),
    sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("notes", sa.Text(), nullable=True),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Column(
        "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.UniqueConstraint("chat_id", name="uq_telegram_chats_chat_id"),
    sa.CheckConstraint(
        "bot_status IN ('member', 'administrator', 'left', 'kicked', 'restricted', 'unknown')",
        name="ck_telegram_chats_bot_status",
    ),
)

sa.Index(
    "ix_telegram_chats_monitored",
    telegram_chats.c.is_monitored,
    telegram_chats.c.last_event_at,
)

# --- TG-M2: Groups, Users, Messages, Moderator Ownership (data-model.md §1-§4, revision 0004) ---

telegram_users = sa.Table(
    "telegram_users",
    metadata,
    sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
    sa.Column("tg_user_id", sa.BigInteger(), nullable=False),
    sa.Column("username", sa.String(length=100), nullable=True),
    sa.Column("display_name", sa.String(length=300), nullable=True),
    sa.Column("is_bot", sa.Boolean(), nullable=False, server_default=sa.false()),
    # NULL means placeholder — mapped but never observed (D-TG-52). Deliberately nullable,
    # unlike telegram_chats: it is how a placeholder is distinguishable without a second flag.
    sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("identity_purged_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Column(
        "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.UniqueConstraint("tg_user_id", name="uq_telegram_users_tg_user_id"),
)

telegram_messages = sa.Table(
    "telegram_messages",
    metadata,
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
    # The platform's own identifier, deliberately not a FK — the target may predate
    # measurement or predate the bot joining (FR-004).
    sa.Column("reply_to_message_id", sa.BigInteger(), nullable=True),
    sa.Column("message_thread_id", sa.BigInteger(), nullable=True),
    sa.Column("is_service", sa.Boolean(), nullable=False, server_default=sa.false()),
    # Written once, at insert, never recomputed (FR-032, FR-033). §2(a)'s insert-only write
    # mode is the mechanism that keeps this true.
    sa.Column("is_from_moderator", sa.Boolean(), nullable=False, server_default=sa.false()),
    sa.Column("original_text", sa.Text(), nullable=True),
    sa.Column("normalized_text", sa.Text(), nullable=True),
    sa.Column("text_purged_at", sa.DateTime(timezone=True), nullable=True),
    # No CHECK: the platform adds media kinds it controls, not this domain (D-TG-46).
    sa.Column("media_kind", sa.String(length=20), nullable=True),
    sa.Column(
        "entity_flags", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
    ),
    sa.Column(
        "source_update_id",
        sa.BigInteger(),
        sa.ForeignKey("telegram_updates.id"),
        nullable=False,
    ),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    # TG-M3 (revision 0005, data-model.md §2). Two columns, not one: a NULL
    # `attention_item_id` cannot distinguish *not yet judged* from *judged and correctly
    # declined*, and most messages are the second (D-TG-72).
    sa.Column(
        "attention_item_id",
        sa.BigInteger(),
        sa.ForeignKey("attention_items.id"),
        nullable=True,
    ),
    sa.Column("attention_evaluated_at", sa.DateTime(timezone=True), nullable=True),
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

sa.Index(
    "ix_messages_chat_sent",
    telegram_messages.c.telegram_chat_id,
    sa.desc(telegram_messages.c.sent_at),
)
sa.Index(
    "ix_messages_chat_moderator_sent",
    telegram_messages.c.telegram_chat_id,
    telegram_messages.c.is_from_moderator,
    telegram_messages.c.sent_at,
)
sa.Index(
    "ix_messages_reply",
    telegram_messages.c.telegram_chat_id,
    telegram_messages.c.reply_to_message_id,
)
# TG-M3 (revision 0005). Partial and empty in steady state — the sweep's authoritative work
# list (D-TG-72, research Finding 3).
sa.Index(
    "ix_messages_unjudged",
    telegram_messages.c.sent_at,
    postgresql_where=telegram_messages.c.attention_evaluated_at.is_(None),
)
sa.Index(
    "ix_messages_attention_item",
    telegram_messages.c.attention_item_id,
    postgresql_where=telegram_messages.c.attention_item_id.is_not(None),
)

moderators = sa.Table(
    "moderators",
    metadata,
    sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
    sa.Column(
        "telegram_user_id",
        sa.BigInteger(),
        sa.ForeignKey("telegram_users.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("display_name", sa.String(length=200), nullable=False),
    # Free reference; no FK — that database is on another host (Principle III).
    sa.Column("injaz_user_id", sa.BigInteger(), nullable=True),
    sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    sa.Column("notes", sa.Text(), nullable=True),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Column(
        "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.UniqueConstraint("telegram_user_id", name="uq_moderators_telegram_user_id"),
)

moderator_group_assignments = sa.Table(
    "moderator_group_assignments",
    metadata,
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
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.CheckConstraint(
        "assignment_role IN ('primary', 'backup')", name="ck_assignment_role"
    ),
    # Strictly greater, not >=, so a zero-width interval is impossible (moderator-ownership.md §1).
    sa.CheckConstraint(
        "valid_to IS NULL OR valid_to > valid_from", name="ck_assignment_interval"
    ),
)

# Exactly one current primary per chat. Cannot be deferred (probe 2), which is what forces
# close-before-open in every handover (data-model.md §4.1).
sa.Index(
    "uq_assignment_one_current_primary",
    moderator_group_assignments.c.telegram_chat_id,
    unique=True,
    postgresql_where=sa.text("assignment_role = 'primary' AND valid_to IS NULL"),
)
sa.Index(
    "ix_assignment_chat_from",
    moderator_group_assignments.c.telegram_chat_id,
    sa.desc(moderator_group_assignments.c.valid_from),
)
sa.Index(
    "ix_assignment_moderator",
    moderator_group_assignments.c.moderator_id,
    sa.desc(moderator_group_assignments.c.valid_from),
)

# --- TG-M3: Deterministic Response Tracking (data-model.md §1-§2, revision 0005) ---

attention_items = sa.Table(
    "attention_items",
    metadata,
    sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
    sa.Column(
        "telegram_chat_id",
        sa.BigInteger(),
        sa.ForeignKey("telegram_chats.id"),
        nullable=False,
    ),
    # The burst's earliest message, not any later one (data-model.md §1).
    sa.Column("telegram_message_id", sa.BigInteger(), nullable=False),
    # Denormalised from the anchor message, deliberately (D-TG-83) — rule (b)'s "oldest open
    # item in this chat and thread" would otherwise join back to telegram_messages on every
    # moderator message, making the hot path a join (data-model.md §1 Indexes).
    sa.Column("message_thread_id", sa.BigInteger(), nullable=True),
    sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("source", sa.String(length=20), nullable=False),
    sa.Column("rule_version", sa.SmallInteger(), nullable=True),
    # Shaped for TG-M5, always NULL here. No FK until 0007 creates message_classifications.
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
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    # Finding 2 (D-TG-71): the chat id is load-bearing here, not decoration — Telegram numbers
    # messages per chat from 1, so `telegram_message_id` alone collides across groups.
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

sa.Index(
    "ix_attention_open",
    attention_items.c.opened_at,
    postgresql_where=attention_items.c.status == "open",
)
sa.Index(
    "ix_attention_chat_thread_open",
    attention_items.c.telegram_chat_id,
    attention_items.c.message_thread_id,
    attention_items.c.opened_at,
    postgresql_where=attention_items.c.status == "open",
)
sa.Index(
    "ix_attention_chat",
    attention_items.c.telegram_chat_id,
    sa.desc(attention_items.c.opened_at),
)
sa.Index(
    "ix_attention_moderator",
    attention_items.c.responsible_moderator_id,
    sa.desc(attention_items.c.opened_at),
)
