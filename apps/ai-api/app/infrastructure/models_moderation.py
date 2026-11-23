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
    # TG-M6 (revision 0013, D-TG-211): the one chat alerts are posted to. Set and cleared only by
    # the panel; never monitored, in either order (`ck_chat_destination_not_monitored`).
    sa.Column(
        "is_alert_destination", sa.Boolean(), nullable=False, server_default=sa.false()
    ),
    sa.UniqueConstraint("chat_id", name="uq_telegram_chats_chat_id"),
    sa.CheckConstraint(
        "bot_status IN ('member', 'administrator', 'left', 'kicked', 'restricted', 'unknown')",
        name="ck_telegram_chats_bot_status",
    ),
    sa.CheckConstraint(
        "NOT (is_alert_destination AND is_monitored)",
        name="ck_chat_destination_not_monitored",
    ),
    # At most one destination (FR-501).
    sa.Index(
        "uq_chat_one_alert_destination",
        sa.text("(true)"),
        unique=True,
        postgresql_where=sa.text("is_alert_destination"),
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
    # Revision 0009: the panel account this moderator signs in with, set only from the panel.
    # No FK to `users`, as `closed_by_user_id` (D-TG-102); never read on this side.
    sa.Column("user_id", sa.BigInteger(), nullable=True),
    sa.UniqueConstraint("telegram_user_id", name="uq_moderators_telegram_user_id"),
    sa.UniqueConstraint("user_id", name="uq_moderators_user_id"),
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

# TG-M2.1 (revision 0011, `specs/012-tg-m2-1-group-teams/contracts/group-teams.md` T2): a group
# has a team, so several current primaries may coexist; one moderator holds at most one current
# row per group, whatever the role. Replaced `uq_assignment_one_current_primary` (one current
# primary per chat). Not deferrable (probe 2), so a replace still closes before it opens (T5).
sa.Index(
    "uq_assignment_one_current_membership",
    moderator_group_assignments.c.telegram_chat_id,
    moderator_group_assignments.c.moderator_id,
    unique=True,
    postgresql_where=sa.text("valid_to IS NULL"),
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
    # definition). NULL on every rule- and operator-opened row. TG-M5 kept it NULL everywhere
    # (data-model.md §5, the second clarification); since TG-M5.1 a `source='ai'` row carries the
    # prediction that opened it, written once at insert and never updated
    # (specs/009-tg-m5-1-ai-attention/contracts/attention-opening.md O3).
    sa.Column("message_classification_id", sa.BigInteger(), nullable=True),
    # TG-M2.1 G1 (`specs/012-tg-m2-1-group-teams/contracts/group-teams.md`): frozen. Rows opened
    # before TG-M2.1 keep TG-M2's owner snapshot; new rows leave it NULL, and no figure reads it
    # (N6) — the assigned moderator is `attention_item_assignee`'s.
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
    # TG-M2.1 C1 (revision 0011): the moderator linked to the dismissing panel account, set at
    # write time and never recomputed (as V5) — NULL for every other close.
    sa.Column(
        "closed_by_moderator_id",
        sa.BigInteger(),
        sa.ForeignKey("moderators.id", name="fk_attention_closed_by_moderator"),
        nullable=True,
    ),
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
    # Before TG-M2.1, snapshotted from responsible_at(chat, detected_at) (I5). Frozen since
    # (group-teams.md G1): new rows leave it NULL and no figure reads it (N6) — the assigned
    # moderator is `moderation_incident_assignee`'s.
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
        "source IN ('operator', 'ai', 'rule')", name="ck_incident_source"
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

# --- The link rule (revision 0010, `docs/plan/telegram/tg-day-one-investigation-and-link-rule-
# plan.md` Step 1): a regular member's link opens an incident with `source = 'rule'`, carrying the
# rule's version exactly then, as `attention_items.rule_version` does for a rule item.

moderation_incidents.append_column(
    sa.Column("rule_version", sa.SmallInteger(), nullable=True)
)
moderation_incidents.append_constraint(
    sa.CheckConstraint(
        "(source = 'rule') = (rule_version IS NOT NULL)",
        name="ck_incident_rule_version",
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
    # TG-M6 (revision 0013, D-TG-217): the alert a button act was pressed on. Set on `alert_*`
    # kinds only (`ck_actions_alert_link`).
    sa.Column(
        "alert_id",
        sa.BigInteger(),
        sa.ForeignKey("alerts.id", name="fk_actions_alert", ondelete="RESTRICT"),
        nullable=True,
    ),
    # One captured event, at most one row, however often it is re-interpreted (V13). NULLs
    # (panel acts) are distinct, so panel acts never collide here.
    sa.UniqueConstraint(
        "source_update_id", name="uq_moderation_actions_source_update"
    ),
    sa.CheckConstraint(
        "action_type IN ('reaction', 'ban', 'expulsion', 'restriction', 'reversal', "
        "'panel_acknowledge', 'panel_resolve', 'panel_false_positive', "
        "'alert_handled', 'alert_false_positive', 'alert_take')",
        name="ck_actions_type",
    ),
    # The kind table of data-model.md §2, as one boolean expression: a reversal or a closure can
    # never be given a strength. TG-M4.1 (revision 0012): a reaction is an acknowledgement, or a
    # confirmation when it is a moderator's 👀.
    sa.CheckConstraint(
        "(action_type = 'reaction' AND action_strength IN ('acknowledgement', 'confirmation')) OR "
        "(action_type IN ('ban', 'expulsion', 'restriction') "
        "AND action_strength = 'enforcement') OR "
        "(action_type = 'reversal' AND action_strength IS NULL) OR "
        "(action_type = 'panel_acknowledge' AND action_strength = 'acknowledgement') OR "
        "(action_type = 'panel_resolve' AND action_strength = 'confirmation') OR "
        "(action_type = 'panel_false_positive' AND action_strength IS NULL) OR "
        "(action_type = 'alert_handled' AND action_strength = 'confirmation') OR "
        "(action_type IN ('alert_false_positive', 'alert_take') AND action_strength IS NULL)",
        name="ck_actions_strength",
    ),
    # Panel acts and the two incident button acts name their incident; captured acts and a take
    # never do (TG-M6: a take reaches its item through its alert).
    sa.CheckConstraint(
        r"(action_type LIKE 'panel\_%' "
        r"OR action_type IN ('alert_handled', 'alert_false_positive')) "
        r"= (moderation_incident_id IS NOT NULL)",
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
    # TG-M4.1: a confirming reaction carries the standard 👀 among its added reactions.
    sa.CheckConstraint(
        "action_type <> 'reaction' OR action_strength <> 'confirmation' OR "
        "detail -> 'added' @> '[{\"type\": \"emoji\", \"emoji\": \"👀\"}]'::jsonb",
        name="ck_actions_reaction_confirmation",
    ),
    # TG-M6: a button act names its alert, and only a button act does.
    sa.CheckConstraint(
        r"(action_type LIKE 'alert\_%') = (alert_id IS NOT NULL)",
        name="ck_actions_alert_link",
    ),
    # TG-M6: a button act is always a declared moderator's, through their Telegram identity.
    sa.CheckConstraint(
        r"action_type NOT LIKE 'alert\_%' OR "
        r"(actor_moderator_id IS NOT NULL AND actor_telegram_user_id IS NOT NULL "
        r"AND panel_user_id IS NULL)",
        name="ck_actions_alert_actor",
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
sa.Index(
    "ix_actions_alert",
    moderation_actions.c.alert_id,
    postgresql_where=moderation_actions.c.alert_id.is_not(None),
)

# TG-M5's own link, deferred here since `attention_items` (revision 0005) predates
# `message_classifications`. TG-M5 kept it NULL on every row (data-model.md §5, the second
# clarification); TG-M5.1 sets it on `source='ai'` rows only — no schema change.
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
        "AND (route_reason IS NULL OR route_reason IN "
        "('uncertain', 'inconsistent', 'no_contact_signal'))",
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

# --- TG-M5.3: A Separate Attention Judgement (specs/011-…/data-model.md §1-§3, revision 0008) ---
#
# message_attention_judgements and message_attention_attempts mirror revision 0007's
# classification tables (D-TG-184): one immutable intent per message, and the messages that
# produced none. A judgement is recorded once and never updated or deleted. There is no text
# column, no confidence and no route, and no CHECK relates `needs_response` to `intent`: the
# mapping has one definition, `app.domain.moderation.attention_judgement.needs_response_for`.

message_attention_judgements = sa.Table(
    "message_attention_judgements",
    metadata,
    sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
    sa.Column(
        "telegram_chat_id",
        sa.BigInteger(),
        sa.ForeignKey("telegram_chats.id"),
        nullable=False,
    ),
    # The judged message, not the burst's anchor.
    sa.Column("telegram_message_id", sa.BigInteger(), nullable=False),
    sa.Column(
        "model_profile_id",
        sa.BigInteger(),
        sa.ForeignKey("model_profiles.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    # Nullable, as in 0007 (Finding 6): a `model_runs` write can fail without failing the
    # judgement it was made for.
    sa.Column(
        "model_run_id",
        sa.BigInteger(),
        sa.ForeignKey("model_runs.id", ondelete="SET NULL"),
        nullable=True,
    ),
    sa.Column("prompt_version", sa.String(length=40), nullable=False),
    sa.Column("intent", sa.String(length=20), nullable=False),
    # `needs_response_for(intent)`, computed once at insert (D-TG-185) and never recomputed.
    sa.Column("needs_response", sa.Boolean(), nullable=False),
    # `live` only in this milestone; `catch_up` is allowed so a later milestone needs no DDL.
    sa.Column("path", sa.String(length=20), nullable=False),
    sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.ForeignKeyConstraint(
        ["telegram_chat_id", "telegram_message_id"],
        ["telegram_messages.telegram_chat_id", "telegram_messages.message_id"],
        name="fk_attention_judgement_message",
    ),
    sa.UniqueConstraint(
        "id", "telegram_chat_id", "telegram_message_id", name="uq_attention_judgement_identity"
    ),
    sa.CheckConstraint(
        "intent IN ('asking', 'discussion', 'informing', 'social', 'offering', 'other')",
        name="ck_attention_judgement_intent",
    ),
    sa.CheckConstraint("path IN ('live', 'catch_up')", name="ck_attention_judgement_path"),
)

# One current judgement per message: the idempotent insert's `ON CONFLICT` target (I1).
sa.Index(
    "uq_attention_judgement_current",
    message_attention_judgements.c.telegram_chat_id,
    message_attention_judgements.c.telegram_message_id,
    unique=True,
    postgresql_where=message_attention_judgements.c.is_current,
)
sa.Index(
    "ix_attention_judgements_profile",
    message_attention_judgements.c.model_profile_id,
    message_attention_judgements.c.prompt_version,
)

message_attention_attempts = sa.Table(
    "message_attention_attempts",
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
        name="fk_attention_attempt_message",
    ),
    sa.CheckConstraint("path IN ('live', 'catch_up')", name="ck_attention_attempt_path"),
    sa.CheckConstraint(
        "outcome IN ('excluded', 'failed')", name="ck_attention_attempt_outcome"
    ),
    # The exclusions are E1-E8 plus `rule_opens` (AE2); the failures are 0007's, minus
    # `confidence_out_of_range` — there is no confidence.
    sa.CheckConstraint(
        "(outcome = 'excluded' AND reason IN "
        "('no_text', 'media', 'service', 'moderator', 'group_itself', 'linked_channel', "
        "'acknowledgement', 'text_removed', 'rule_opens')) "
        "OR (outcome = 'failed' AND reason IN "
        "('provider_unreachable', 'model_timeout', 'circuit_open', 'model_truncated', "
        "'structured_output_invalid', 'model_not_available', 'provider_rejected', "
        "'provider_auth'))",
        name="ck_attention_attempt_reason",
    ),
    sa.CheckConstraint(
        "(outcome = 'failed') = (model_profile_id IS NOT NULL)",
        name="ck_attention_attempt_profile",
    ),
)

# An exclusion is recorded once (AE3); failures are appended.
sa.Index(
    "uq_attention_attempt_exclusion",
    message_attention_attempts.c.telegram_chat_id,
    message_attention_attempts.c.telegram_message_id,
    unique=True,
    postgresql_where=message_attention_attempts.c.outcome == "excluded",
)
sa.Index(
    "ix_attention_attempts_message",
    message_attention_attempts.c.telegram_chat_id,
    message_attention_attempts.c.telegram_message_id,
    message_attention_attempts.c.created_at,
)

# attention_items: which judgement opened it (data-model.md §3). Set at insert on a TG-M5.3 model
# item, never updated. The FK is to `id` alone, like `fk_attention_classification`: the opening
# judgement may belong to a later burst member than the anchor. Historical TG-M5.1 items keep
# `message_classification_id`; `ck_attention_ai_link` makes a model item carry exactly one of the
# two links, and a rule or operator item neither.
attention_items.append_column(sa.Column("attention_judgement_id", sa.BigInteger(), nullable=True))
attention_items.append_constraint(
    sa.ForeignKeyConstraint(
        ["attention_judgement_id"],
        ["message_attention_judgements.id"],
        name="fk_attention_judgement",
    )
)
attention_items.append_constraint(
    sa.CheckConstraint(
        "CASE WHEN source = 'ai' "
        "THEN num_nonnulls(message_classification_id, attention_judgement_id) = 1 "
        "ELSE num_nonnulls(message_classification_id, attention_judgement_id) = 0 END",
        name="ck_attention_ai_link",
    )
)

# --- TG-M6: Alerts (`specs/013-tg-m6-alerts/data-model.md` §2-§3, revision 0013) ---

# Operator data (D-TG-212): nothing is seeded and no threshold exists in code. The rule in force for
# (chat, trigger) is the chat's row, enabled or not, else the global row (R5).
alert_rules = sa.Table(
    "alert_rules",
    metadata,
    sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
    sa.Column("trigger", sa.String(length=30), nullable=False),
    sa.Column(
        "telegram_chat_id",
        sa.BigInteger(),
        sa.ForeignKey("telegram_chats.id", name="fk_alert_rules_chat"),
        nullable=True,
    ),
    sa.Column("threshold_s", sa.Integer(), nullable=True),
    sa.Column("min_severity", sa.String(length=10), nullable=True),
    sa.Column("categories", JSONB(), nullable=True),
    sa.Column("openers", JSONB(), nullable=True),
    sa.Column("repeat_every_s", sa.Integer(), nullable=True),
    sa.Column("max_repeats", sa.SmallInteger(), nullable=True),
    sa.Column("quiet_hours", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    sa.Column("enabled_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("updated_by_user_id", sa.BigInteger(), nullable=True),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Column(
        "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.CheckConstraint(
        "trigger IN ('question_waiting', 'incident_flagged', 'incident_unhandled', "
        "'group_silent', 'bot_not_admin')",
        name="ck_alert_rule_trigger",
    ),
    sa.CheckConstraint(
        "(trigger IN ('question_waiting', 'incident_unhandled', 'group_silent')) "
        "= (threshold_s IS NOT NULL) AND (threshold_s IS NULL OR threshold_s > 0)",
        name="ck_alert_rule_threshold",
    ),
    sa.CheckConstraint(
        "trigger IN ('incident_flagged', 'incident_unhandled') OR "
        "(min_severity IS NULL AND categories IS NULL AND openers IS NULL)",
        name="ck_alert_rule_filters",
    ),
    sa.CheckConstraint(
        "min_severity IS NULL OR min_severity IN ('low', 'medium', 'high')",
        name="ck_alert_rule_severity",
    ),
    sa.CheckConstraint(
        "(repeat_every_s IS NULL) = (max_repeats IS NULL) AND "
        "(repeat_every_s IS NULL OR (repeat_every_s > 0 AND max_repeats > 0))",
        name="ck_alert_rule_repeats",
    ),
    sa.CheckConstraint("jsonb_typeof(quiet_hours) = 'array'", name="ck_alert_rule_quiet_hours"),
    sa.CheckConstraint(
        "NOT is_enabled OR enabled_at IS NOT NULL", name="ck_alert_rule_enabled_at"
    ),
)

sa.Index(
    "uq_alert_rule_global",
    alert_rules.c.trigger,
    unique=True,
    postgresql_where=alert_rules.c.telegram_chat_id.is_(None),
)
sa.Index(
    "uq_alert_rule_chat",
    alert_rules.c.trigger,
    alert_rules.c.telegram_chat_id,
    unique=True,
    postgresql_where=alert_rules.c.telegram_chat_id.is_not(None),
)

# One row per rule, subject, episode and repeat (`uq_alerts_dedupe`, FR-522). Never a message text:
# `rendered_state` holds the inputs of the last rendered text (D-TG-216), and the excerpt is built
# at render time only (D-TG-221).
alerts = sa.Table(
    "alerts",
    metadata,
    sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
    sa.Column(
        "alert_rule_id",
        sa.BigInteger(),
        sa.ForeignKey("alert_rules.id", name="fk_alerts_rule", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("trigger", sa.String(length=30), nullable=False),
    # The source group: where the subject lives, never the alert group.
    sa.Column(
        "telegram_chat_id",
        sa.BigInteger(),
        sa.ForeignKey("telegram_chats.id", name="fk_alerts_chat"),
        nullable=False,
    ),
    sa.Column("subject_type", sa.String(length=20), nullable=False),
    sa.Column("subject_id", sa.BigInteger(), nullable=False),
    sa.Column("episode_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("repeat_index", sa.SmallInteger(), nullable=False),
    sa.Column("dedupe_key", sa.String(length=160), nullable=False),
    sa.Column("rule_values", JSONB(), nullable=False),
    sa.Column("qualified_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column(
        "fired_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Column(
        "delivery_status",
        sa.String(length=12),
        nullable=False,
        server_default=sa.text("'pending'"),
    ),
    sa.Column("not_sent_reason", sa.String(length=20), nullable=True),
    sa.Column("attempts", sa.SmallInteger(), nullable=False, server_default=sa.text("0")),
    sa.Column("last_error_category", sa.String(length=40), nullable=True),
    sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("sent_chat_id", sa.BigInteger(), nullable=True),
    sa.Column("sent_message_id", sa.BigInteger(), nullable=True),
    sa.Column("rendered_state", JSONB(), nullable=True),
    sa.Column("excerpt_shown", sa.Boolean(), nullable=False, server_default=sa.false()),
    sa.Column("final_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("last_edit_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("edit_attempts", sa.SmallInteger(), nullable=False, server_default=sa.text("0")),
    sa.Column("last_edit_error_category", sa.String(length=40), nullable=True),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.UniqueConstraint("dedupe_key", name="uq_alerts_dedupe"),
    sa.CheckConstraint(
        "subject_type IN ('attention_item', 'incident', 'chat')", name="ck_alerts_subject_type"
    ),
    sa.CheckConstraint(
        "(subject_type = 'chat') = (episode_at IS NOT NULL)", name="ck_alerts_episode"
    ),
    sa.CheckConstraint("repeat_index >= 0", name="ck_alerts_repeat"),
    sa.CheckConstraint(
        "delivery_status IN ('pending', 'sending', 'sent', 'failed', 'suppressed', "
        "'not_sent')",
        name="ck_alerts_status",
    ),
    sa.CheckConstraint(
        "(delivery_status = 'not_sent') = (not_sent_reason IS NOT NULL)",
        name="ck_alerts_not_sent",
    ),
    sa.CheckConstraint(
        "(delivery_status = 'sent') = "
        "(sent_message_id IS NOT NULL AND sent_chat_id IS NOT NULL)",
        name="ck_alerts_posted",
    ),
)

# A press finds its alert by where it was posted (D-TG-219).
sa.Index(
    "uq_alerts_posted",
    alerts.c.sent_chat_id,
    alerts.c.sent_message_id,
    unique=True,
    postgresql_where=alerts.c.sent_message_id.is_not(None),
)
sa.Index(
    "ix_alerts_subject",
    alerts.c.alert_rule_id,
    alerts.c.subject_type,
    alerts.c.subject_id,
    alerts.c.episode_at,
)
sa.Index(
    "ix_alerts_live",
    alerts.c.id,
    postgresql_where=sa.and_(alerts.c.delivery_status == "sent", alerts.c.final_at.is_(None)),
)
sa.Index("ix_alerts_excerpt", alerts.c.id, postgresql_where=alerts.c.excerpt_shown)
sa.Index("ix_alerts_fired", alerts.c.fired_at.desc())

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
    # TG-M6 (revision 0013, D-TG-218): appended, so every column above keeps its position.
    sa.column("close_kind"),
    sa.column("closed_by_moderator_id"),
)

# TG-M2.1's three views (revision 0011, `specs/012-tg-m2-1-group-teams/data-model.md` §3-§5) —
# declared the same lightweight way, for the same reason. `moderation_team_intervals` is the one
# definition of "on the team" (T3); the two assignee views derive each assigned moderator from
# recorded acts (G6) and are never written.

moderation_team_intervals = sa.table(
    "moderation_team_intervals",
    sa.column("assignment_id"),
    sa.column("telegram_chat_id"),
    sa.column("moderator_id"),
    sa.column("valid_from"),
    sa.column("valid_to"),
)

attention_item_assignee = sa.table(
    "attention_item_assignee",
    sa.column("attention_item_id"),
    sa.column("assigned_moderator_id"),
    sa.column("assigned_at"),
    sa.column("assigned_via"),
)

moderation_incident_assignee = sa.table(
    "moderation_incident_assignee",
    sa.column("incident_id"),
    sa.column("assigned_moderator_id"),
    sa.column("assigned_at"),
    sa.column("assigned_via"),
)
