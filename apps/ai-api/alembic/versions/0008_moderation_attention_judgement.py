"""Attention judgement: message_attention_judgements, message_attention_attempts, the
attention_items judgement link and its one-link check, and the attention model_profiles role.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-07

`specs/011-tg-m5-3-attention-judgement/data-model.md` §1-§4 and §6. **D-TG-184**: the attention
judgement has its own record, typed and insert-only, mirroring 0007's classification tables — one
intent per message (`asking`, `discussion`, `informing`, `social`, `offering`, `other`), no text
column, no confidence and no route; there is deliberately no CHECK relating `needs_response` to
`intent`, whose mapping has one definition, in the pure domain (D-TG-185). **D-TG-190**: the
judgement runs on its own model role, `attention`, so `uq_model_profiles_one_active_per_role` gives
exactly one active attention profile, independent of `moderation`'s. **D-TG-192**: this revision
takes the next free number, `0008`; the roadmap's reservation of `0008`-`0009` moves on to the next
free numbers. **Finding 19**: every existing `attention_items` row already satisfies
`ck_attention_ai_link` (on the development database, the one `ai` item carries
`message_classification_id` and no `rule` or `operator` item carries a link), so the check is added
without touching a row. Historical TG-M5.1 items keep their classification link; from this
revision on `open_item` writes only `attention_judgement_id`. The downgrade fails, correctly, once
an `attention` profile, a judgement or an attention-linked item exists: from then on the revision
is forward-only. No `GRANT` — the migrator's default ACL already reaches `ai_control` and `ai_app`
for new tables, as 0007 measured. No view: every derived value has one definition, in Python.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # §4 — model_profiles gains the attention role.
    op.drop_constraint("ck_model_profiles_role", "model_profiles", type_="check")
    op.create_check_constraint(
        "ck_model_profiles_role",
        "model_profiles",
        "role IN ('llm', 'embedding', 'moderation', 'attention')",
    )

    # §1 — message_attention_judgements: one immutable intent per message.
    op.create_table(
        "message_attention_judgements",
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
        sa.Column("intent", sa.String(length=20), nullable=False),
        sa.Column("needs_response", sa.Boolean(), nullable=False),
        sa.Column("path", sa.String(length=20), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
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
    op.create_index(
        "uq_attention_judgement_current",
        "message_attention_judgements",
        ["telegram_chat_id", "telegram_message_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )
    op.create_index(
        "ix_attention_judgements_profile",
        "message_attention_judgements",
        ["model_profile_id", "prompt_version"],
    )

    # §2 — message_attention_attempts: exclusions (recorded once) and failures (appended).
    op.create_table(
        "message_attention_attempts",
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
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
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
    op.create_index(
        "uq_attention_attempt_exclusion",
        "message_attention_attempts",
        ["telegram_chat_id", "telegram_message_id"],
        unique=True,
        postgresql_where=sa.text("outcome = 'excluded'"),
    )
    op.create_index(
        "ix_attention_attempts_message",
        "message_attention_attempts",
        ["telegram_chat_id", "telegram_message_id", "created_at"],
    )

    # §3 — attention_items: which judgement opened it, and exactly one link on a model item.
    op.add_column(
        "attention_items",
        sa.Column("attention_judgement_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_attention_judgement",
        "attention_items",
        "message_attention_judgements",
        ["attention_judgement_id"],
        ["id"],
    )
    op.create_check_constraint(
        "ck_attention_ai_link",
        "attention_items",
        "CASE WHEN source = 'ai' "
        "THEN num_nonnulls(message_classification_id, attention_judgement_id) = 1 "
        "ELSE num_nonnulls(message_classification_id, attention_judgement_id) = 0 END",
    )


def downgrade() -> None:
    op.drop_constraint("ck_attention_ai_link", "attention_items", type_="check")
    op.drop_constraint("fk_attention_judgement", "attention_items", type_="foreignkey")
    op.drop_column("attention_items", "attention_judgement_id")

    op.drop_constraint("ck_model_profiles_role", "model_profiles", type_="check")
    op.create_check_constraint(
        "ck_model_profiles_role",
        "model_profiles",
        "role IN ('llm', 'embedding', 'moderation')",
    )

    op.drop_index("ix_attention_attempts_message", table_name="message_attention_attempts")
    op.drop_index("uq_attention_attempt_exclusion", table_name="message_attention_attempts")
    op.drop_table("message_attention_attempts")

    op.drop_index("ix_attention_judgements_profile", table_name="message_attention_judgements")
    op.drop_index("uq_attention_judgement_current", table_name="message_attention_judgements")
    op.drop_table("message_attention_judgements")
