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
    # `fk_attention_classification` (below, deferred past `message_classifications`' own
    # definition) stays NULL on every row this milestone — the model opens no question item
    # (data-model.md §5, the second clarification).
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

# --- TG-M4: Policy Incidents (data-model.md §1-§3, revision 0006) ---
#
# An incident stores only what was decided when it was flagged (research Finding 3): no `status`
# column and no `acknowledged_*` / `resolved_*` / `closed_*` columns. Its status, moments and
# actors are computed once by the two views declared below — `moderation_incident_evidence` and
# `moderation_incident_state` — the only definitions (lifecycle contract N6). Neither table is
# ever altered by an application `UPDATE`; `moderation_actions` is append-only (D-TG-113).

moderation_incidents = sa.Table(
    "moderation_incidents",
    metadata,
    sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
    sa.Column(
        "telegram_chat_id",
        sa.BigInteger(),
        sa.ForeignKey("telegram_chats.id"),
        nullable=False,
    ),
    # The offending message's platform id, per chat (I2).
    sa.Column("telegram_message_id", sa.BigInteger(), nullable=False),
    # The posting moment — that message's own `sent_at` (I3). Never the flagging time.
    sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
    # The flagging moment — the database's `now()` at insert (I3).
    sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("source", sa.String(length=20), nullable=False),
    # The panel account that flagged it. No FK, as attention_items.closed_by_user_id.
    sa.Column("opened_by_user_id", sa.BigInteger(), nullable=True),
    sa.Column("category", sa.String(length=30), nullable=False),
    sa.Column("severity", sa.String(length=10), nullable=False),
    # The prediction that opened this incident — set, and required (`ck_incident_ai_link`),
    # only when `source = 'ai'`; `fk_incident_classification` (below) is composite.
    sa.Column("message_classification_id", sa.BigInteger(), nullable=True),
    # Snapshotted from responsible_at(chat, detected_at) — the owner at the flag, not the anchor
    # message (I5). NULL is a real answer: nobody owned the group then.
    sa.Column(
        "responsible_moderator_id",
        sa.BigInteger(),
        sa.ForeignKey("moderators.id"),
        nullable=True,
    ),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    # The chat id is load-bearing here too — TG-M3's Finding 2 applies unchanged (D-TG-100).
    sa.UniqueConstraint(
        "telegram_chat_id", "telegram_message_id", name="uq_incident_anchor"
    ),
    sa.ForeignKeyConstraint(
        ["telegram_chat_id", "telegram_message_id"],
        ["telegram_messages.telegram_chat_id", "telegram_messages.message_id"],
        name="fk_incident_message",
    ),
    sa.CheckConstraint(
        "source IN ('operator', 'ai')", name="ck_incident_source"
    ),
    sa.CheckConstraint(
        "(source = 'operator') = (opened_by_user_id IS NOT NULL)",
        name="ck_incident_opener",
    ),
    sa.CheckConstraint(
        "category IN ('SPAM_OR_AD', 'ABUSE', 'OTHER')", name="ck_incident_category"
    ),
    sa.CheckConstraint(
        "severity IN ('low', 'medium', 'high')", name="ck_incident_severity"
    ),
    sa.CheckConstraint(
        "source <> 'operator' OR message_classification_id IS NULL",
        name="ck_incident_operator_labels",
    ),
)

# --- TG-M5: AI Classification (data-model.md §2-§5, revision 0007) -----------------------------
#
# `message_classifications` is added below, on the same metadata; `moderation_incidents` and
# `attention_items` gain their TG-M5 links here too, so this one Python module always reflects
# the schema alembic revision 0007 creates — Core `Table`/`Column` objects are declarative
# metadata, not migrations (data-model.md §0).

moderation_incidents.append_column(
    sa.Column("prompted_by_classification_id", sa.BigInteger(), nullable=True)
)
# Composite, `MATCH SIMPLE`: a NULL link is unchecked; a non-NULL link must cite a prediction
# about this incident's own message (probe 9 E2, E3, D-TG-145) — the string-form refcolumns
# resolve against `message_classifications` lazily, so table definition order does not matter.
moderation_incidents.append_constraint(
    sa.ForeignKeyConstraint(
        ["message_classification_id", "telegram_chat_id", "telegram_message_id"],
        [
            "message_classifications.id",
            "message_classifications.telegram_chat_id",
            "message_classifications.telegram_message_id",
        ],
        name="fk_incident_classification",
    )
)
moderation_incidents.append_constraint(
    sa.ForeignKeyConstraint(
        ["prompted_by_classification_id", "telegram_chat_id", "telegram_message_id"],
        [
            "message_classifications.id",
            "message_classifications.telegram_chat_id",
            "message_classifications.telegram_message_id",
        ],
        name="fk_incident_prompted_by",
    )
)
moderation_incidents.append_constraint(
    sa.CheckConstraint(
        "source <> 'ai' OR message_classification_id IS NOT NULL",
        name="ck_incident_ai_link",
    )
)
moderation_incidents.append_constraint(
    sa.CheckConstraint(
        "prompted_by_classification_id IS NULL OR source = 'operator'",
        name="ck_incident_prompted_by",
    )
)

sa.Index(
    "ix_incidents_detected",
    moderation_incidents.c.detected_at,
)
sa.Index(
    "ix_incidents_chat",
    moderation_incidents.c.telegram_chat_id,
    sa.desc(moderation_incidents.c.detected_at),
)
sa.Index(
    "ix_incidents_moderator",
    moderation_incidents.c.responsible_moderator_id,
    sa.desc(moderation_incidents.c.detected_at),
)

moderation_actions = sa.Table(
    "moderation_actions",
    metadata,
    sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
    sa.Column(
        "telegram_chat_id",
        sa.BigInteger(),
        sa.ForeignKey("telegram_chats.id"),
        nullable=False,
    ),
    sa.Column("action_type", sa.String(length=30), nullable=False),
    # NULL for a reversal or a false-positive closure — neither can ever be an incident's
    # earliest enforcement or confirmation (data-model.md §2).
    sa.Column("action_strength", sa.String(length=20), nullable=True),
    # The platform's `date` for a captured act; the database's `now()` for a panel act.
    sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column(
        "actor_telegram_user_id",
        sa.BigInteger(),
        sa.ForeignKey("telegram_users.id"),
        nullable=True,
    ),
    # Set when the actor was a declared moderator when recorded; never recomputed (V5).
    sa.Column(
        "actor_moderator_id",
        sa.BigInteger(),
        sa.ForeignKey("moderators.id"),
        nullable=True,
    ),
    sa.Column(
        "actor_is_anonymous", sa.Boolean(), nullable=False, server_default=sa.false()
    ),
    # The panel account, for panel acts. No FK, as moderation_incidents.opened_by_user_id.
    sa.Column("panel_user_id", sa.BigInteger(), nullable=True),
    sa.Column(
        "subject_telegram_user_id",
        sa.BigInteger(),
        sa.ForeignKey("telegram_users.id"),
        nullable=True,
    ),
    # The reacted-to message's platform id, in telegram_chat_id. Deliberately not a FK, like
    # attention_items.telegram_message_id.
    sa.Column("target_message_id", sa.BigInteger(), nullable=True),
    sa.Column(
        "moderation_incident_id",
        sa.BigInteger(),
        sa.ForeignKey("moderation_incidents.id"),
        nullable=True,
    ),
    sa.Column(
        "source_update_id",
        sa.BigInteger(),
        sa.ForeignKey("telegram_updates.id"),
        nullable=True,
    ),
    # Emoji added; old/new status; until_date. Never message text (N8).
    sa.Column(
        "detail", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
    ),
    # The operator's own words — a resolve note or a false-positive reason. Nothing parses it.
    sa.Column("note", sa.Text(), nullable=True),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    # One captured event, at most one row, however often it is re-interpreted (V13). NULLs
    # (panel acts) are distinct, so panel acts never collide here.
    sa.UniqueConstraint(
        "source_update_id", name="uq_moderation_actions_source_update"
    ),
    sa.CheckConstraint(
        "action_type IN ('reaction', 'ban', 'expulsion', 'restriction', 'reversal', "
        "'panel_acknowledge', 'panel_resolve', 'panel_false_positive')",
        name="ck_actions_type",
    ),
    # The kind table of data-model.md §2, as one boolean expression: a reversal or a closure can
    # never be given a strength.
    sa.CheckConstraint(
        "(action_type = 'reaction' AND action_strength = 'acknowledgement') OR "
        "(action_type IN ('ban', 'expulsion', 'restriction') "
        "AND action_strength = 'enforcement') OR "
        "(action_type = 'reversal' AND action_strength IS NULL) OR "
        "(action_type = 'panel_acknowledge' AND action_strength = 'acknowledgement') OR "
        "(action_type = 'panel_resolve' AND action_strength = 'confirmation') OR "
        "(action_type = 'panel_false_positive' AND action_strength IS NULL)",
        name="ck_actions_strength",
    ),
    # Panel acts name their incident; captured acts never do.
    sa.CheckConstraint(
        r"(action_type LIKE 'panel\_%') = (moderation_incident_id IS NOT NULL)",
        name="ck_actions_panel_link",
    ),
    # Every row says where it came from.
    sa.CheckConstraint(
        r"(action_type LIKE 'panel\_%' AND panel_user_id IS NOT NULL AND source_update_id IS NULL) "
        r"OR (action_type NOT LIKE 'panel\_%' AND source_update_id IS NOT NULL)",
        name="ck_actions_provenance",
    ),
    sa.CheckConstraint(
        "action_type NOT IN ('panel_resolve', 'panel_false_positive') OR "
        "(note IS NOT NULL AND btrim(note) <> '')",
        name="ck_actions_note",
    ),
    # A ban with no subject cannot link to anything.
    sa.CheckConstraint(
        "action_type NOT IN ('ban', 'expulsion', 'restriction', 'reversal') OR "
        "subject_telegram_user_id IS NOT NULL",
        name="ck_actions_membership_subject",
    ),
    # Only a moderator's reaction is ever recorded.
    sa.CheckConstraint(
        "action_type <> 'reaction' OR "
        "(target_message_id IS NOT NULL AND actor_moderator_id IS NOT NULL)",
        name="ck_actions_reaction_shape",
    ),
)

sa.Index(
    "ix_actions_reaction_target",
    moderation_actions.c.telegram_chat_id,
    moderation_actions.c.target_message_id,
    postgresql_where=moderation_actions.c.action_type == "reaction",
)
sa.Index(
    "ix_actions_subject",
    moderation_actions.c.subject_telegram_user_id,
    moderation_actions.c.occurred_at,
    postgresql_where=moderation_actions.c.subject_telegram_user_id.is_not(None),
)
sa.Index(
    "ix_actions_incident",
    moderation_actions.c.moderation_incident_id,
    postgresql_where=moderation_actions.c.moderation_incident_id.is_not(None),
)

# TG-M5's own link, deferred here since `attention_items` (revision 0005) predates
# `message_classifications`. Stays NULL on every row this milestone — the model opens no
# question item (data-model.md §5, the second clarification).
attention_items.append_constraint(
    sa.ForeignKeyConstraint(
        ["message_classification_id"],
        ["message_classifications.id"],
        name="fk_attention_classification",
    )
)

# message_classifications and message_classification_attempts — immutable predictions and the
# messages that produced none (data-model.md §2-§3, revision 0007). A prediction is a claim,
# recorded once with its provenance and never changed: no application code issues an `UPDATE`
# or `DELETE` against either table (D-TG-147); the panel's Eloquent models throw on both.

message_classifications = sa.Table(
    "message_classifications",
    metadata,
    sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
    sa.Column(
        "telegram_chat_id",
        sa.BigInteger(),
        sa.ForeignKey("telegram_chats.id"),
        nullable=False,
    ),
    sa.Column("telegram_message_id", sa.BigInteger(), nullable=False),
    sa.Column(
        "model_profile_id",
        sa.BigInteger(),
        sa.ForeignKey("model_profiles.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column(
        "model_run_id",
        sa.BigInteger(),
        sa.ForeignKey("model_runs.id", ondelete="SET NULL"),
        nullable=True,
    ),
    sa.Column("prompt_version", sa.String(length=40), nullable=False),
    sa.Column("taxonomy_version", sa.SmallInteger(), nullable=False),
    sa.Column("category", sa.String(length=30), nullable=False),
    sa.Column("needs_response", sa.Boolean(), nullable=False),
    sa.Column("needs_moderation", sa.Boolean(), nullable=False),
    sa.Column("severity", sa.String(length=10), nullable=False),
    sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
    sa.Column("path", sa.String(length=20), nullable=False),
    sa.Column("route", sa.String(length=20), nullable=False),
    sa.Column("route_reason", sa.String(length=20), nullable=True),
    sa.Column("confidence_floor", sa.Numeric(4, 3), nullable=True),
    sa.Column("incident_threshold", sa.Numeric(4, 3), nullable=True),
    sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.ForeignKeyConstraint(
        ["telegram_chat_id", "telegram_message_id"],
        ["telegram_messages.telegram_chat_id", "telegram_messages.message_id"],
        name="fk_classification_message",
    ),
    sa.UniqueConstraint(
        "id", "telegram_chat_id", "telegram_message_id", name="uq_classification_identity"
    ),
    sa.CheckConstraint(
        "category IN ('QUESTION_COURSE', 'QUESTION_ACCESS', 'COMPLAINT', 'CHITCHAT', "
        "'SPAM_OR_AD', 'ABUSE', 'OTHER')",
        name="ck_classification_category",
    ),
    sa.CheckConstraint(
        "severity IN ('none', 'low', 'medium', 'high')", name="ck_classification_severity"
    ),
    sa.CheckConstraint(
        "confidence >= 0 AND confidence <= 1", name="ck_classification_confidence"
    ),
    sa.CheckConstraint("path IN ('live', 'catch_up')", name="ck_classification_path"),
    sa.CheckConstraint(
        "route IN ('incident', 'possible_violation', 'review', 'none', 'measurement_only')",
        name="ck_classification_route",
    ),
    sa.CheckConstraint(
        "(path = 'catch_up') = (route = 'measurement_only')",
        name="ck_classification_route_path",
    ),
    sa.CheckConstraint(
        "(route = 'possible_violation') = (route_reason IS NOT NULL) "
        "AND (route_reason IS NULL OR route_reason IN ('uncertain', 'inconsistent'))",
        name="ck_classification_route_reason",
    ),
    sa.CheckConstraint(
        "(path = 'live') = (confidence_floor IS NOT NULL AND incident_threshold IS NOT NULL) "
        "AND (confidence_floor IS NULL OR confidence_floor <= incident_threshold)",
        name="ck_classification_thresholds",
    ),
)

sa.Index(
    "uq_classification_current",
    message_classifications.c.telegram_chat_id,
    message_classifications.c.telegram_message_id,
    unique=True,
    postgresql_where=message_classifications.c.is_current,
)
sa.Index(
    "ix_classifications_possible",
    message_classifications.c.created_at,
    postgresql_where=message_classifications.c.route == "possible_violation",
)
sa.Index(
    "ix_classifications_profile",
    message_classifications.c.model_profile_id,
    message_classifications.c.prompt_version,
    message_classifications.c.taxonomy_version,
)

message_classification_attempts = sa.Table(
    "message_classification_attempts",
    metadata,
    sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
    sa.Column(
        "telegram_chat_id",
        sa.BigInteger(),
        sa.ForeignKey("telegram_chats.id"),
        nullable=False,
    ),
    sa.Column("telegram_message_id", sa.BigInteger(), nullable=False),
    sa.Column("path", sa.String(length=20), nullable=False),
    sa.Column("outcome", sa.String(length=20), nullable=False),
    sa.Column("reason", sa.String(length=40), nullable=False),
    sa.Column(
        "model_profile_id",
        sa.BigInteger(),
        sa.ForeignKey("model_profiles.id"),
        nullable=True,
    ),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.ForeignKeyConstraint(
        ["telegram_chat_id", "telegram_message_id"],
        ["telegram_messages.telegram_chat_id", "telegram_messages.message_id"],
        name="fk_attempt_message",
    ),
    sa.CheckConstraint("path IN ('live', 'catch_up')", name="ck_attempt_path"),
    sa.CheckConstraint("outcome IN ('excluded', 'failed')", name="ck_attempt_outcome"),
    sa.CheckConstraint(
        "(outcome = 'excluded' AND reason IN "
        "('no_text', 'media', 'service', 'moderator', 'group_itself', 'linked_channel', "
        "'acknowledgement', 'text_removed')) "
        "OR (outcome = 'failed' AND reason IN "
        "('provider_unreachable', 'model_timeout', 'circuit_open', 'model_truncated', "
        "'structured_output_invalid', 'confidence_out_of_range', 'model_not_available', "
        "'provider_rejected', 'provider_auth'))",
        name="ck_attempt_reason",
    ),
    sa.CheckConstraint(
        "(outcome = 'failed') = (model_profile_id IS NOT NULL)", name="ck_attempt_profile"
    ),
)

sa.Index(
    "uq_attempt_exclusion",
    message_classification_attempts.c.telegram_chat_id,
    message_classification_attempts.c.telegram_message_id,
    unique=True,
    postgresql_where=message_classification_attempts.c.outcome == "excluded",
)
sa.Index(
    "ix_attempts_message",
    message_classification_attempts.c.telegram_chat_id,
    message_classification_attempts.c.telegram_message_id,
    message_classification_attempts.c.created_at,
)

# The two views (data-model.md §3) — the only definitions of linkage and derived state (lifecycle
# contract N6). Declared as lightweight `sa.table()` clauses, **not** `sa.Table(..., metadata)`, so
# `metadata.create_all()` can never create a table named like a view; only alembic revision
# `0006`'s `CREATE VIEW` statements do. Column lists mirror the `SELECT`s in `data-model.md`
# §3.1-§3.2 exactly — both are read-only from Python and PHP alike.

moderation_incident_evidence = sa.table(
    "moderation_incident_evidence",
    sa.column("incident_id"),
    sa.column("source_rank"),
    sa.column("evidence_id"),
    sa.column("kind"),
    sa.column("strength"),
    sa.column("occurred_at"),
    sa.column("actor_telegram_user_id"),
    sa.column("actor_moderator_id"),
    sa.column("actor_is_anonymous"),
    sa.column("panel_user_id"),
    sa.column("subject_telegram_user_id"),
    sa.column("source_update_id"),
    sa.column("note"),
    sa.column("detail"),
)

moderation_incident_state = sa.table(
    "moderation_incident_state",
    sa.column("incident_id"),
    sa.column("status"),
    sa.column("first_acknowledgement_at"),
    sa.column("acknowledgement_kind"),
    sa.column("acknowledged_by_moderator_id"),
    sa.column("acknowledged_by_user_id"),
    sa.column("first_enforcement_at"),
    sa.column("first_confirmation_at"),
    sa.column("resolved_at"),
    sa.column("resolution_kind"),
    sa.column("resolution_strength"),
    sa.column("resolved_by_moderator_id"),
    sa.column("resolved_by_telegram_user_id"),
    sa.column("resolved_by_anonymous"),
    sa.column("resolved_by_user_id"),
    sa.column("closed_at"),
    sa.column("closed_by_user_id"),
    sa.column("close_reason"),
)
