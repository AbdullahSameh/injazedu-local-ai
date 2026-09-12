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
