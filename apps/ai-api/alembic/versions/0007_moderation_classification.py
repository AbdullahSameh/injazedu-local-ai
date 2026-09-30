"""AI classification: message_classifications, message_classification_attempts, the
moderation_incidents/attention_items links, and the moderation model_profiles role.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-27

data-model.md §1-§5. Every statement below ran exactly as written, as `ai_migrator`, inside
`BEGIN … ROLLBACK` in `injaz_ai_test`, and each of research probe 9's twelve planted violations
was rejected by the constraint named for it. **Finding 1**: the seeded `moderation` profile's
params carry `reasoning_effort: "none"` — without it every classification answer is cut off.
**Finding 2**: the model's self-reported confidence barely moves (0.90-1.00); the thresholds
below are the approved defaults, not a safety signal. **Finding 3**: moderation code reaches a
model only through `app.application.gateway`, never `app.providers.llm` — this migration has no
bearing on that boundary, enforced by `make check`. **Finding 4**: classification runs on its own
queue (`infra/docker-compose.yml`'s `ai-classifier`), not this migration's concern either.
**Finding 5**: predictions read a message's captured event, never `telegram_messages` — this
migration stores no text either way. **Finding 6**: `model_run_id` is nullable here — a
`model_runs` write can fail without failing the prediction it was made for. No `GRANT` — the
migrator's default ACL already reaches `ai_control` and `ai_app` for new tables (probe 9). No
view: the route's value has one definition, in Python (D-TG-142); this migration checks shape
only. `0008`-`0009` stay reserved for TG-M6…TG-M8.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # §1 — model_profiles gains the moderation role.
    op.drop_constraint("ck_model_profiles_role", "model_profiles", type_="check")
    op.create_check_constraint(
        "ck_model_profiles_role",
        "model_profiles",
        "role IN ('llm', 'embedding', 'moderation')",
    )

    # §2 — message_classifications: one immutable prediction per message.
    op.create_table(
        "message_classifications",
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
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
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
    op.create_index(
        "uq_classification_current",
        "message_classifications",
        ["telegram_chat_id", "telegram_message_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )
    op.create_index(
        "ix_classifications_possible",
        "message_classifications",
        ["created_at"],
        postgresql_where=sa.text("route = 'possible_violation'"),
    )
    op.create_index(
        "ix_classifications_profile",
        "message_classifications",
        ["model_profile_id", "prompt_version", "taxonomy_version"],
    )

    # §3 — message_classification_attempts: exclusions and failures.
    op.create_table(
        "message_classification_attempts",
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
    op.create_index(
        "uq_attempt_exclusion",
        "message_classification_attempts",
        ["telegram_chat_id", "telegram_message_id"],
        unique=True,
        postgresql_where=sa.text("outcome = 'excluded'"),
    )
    op.create_index(
        "ix_attempts_message",
        "message_classification_attempts",
        ["telegram_chat_id", "telegram_message_id", "created_at"],
    )

    # §4 — moderation_incidents: who opened it, and what prompted it.
    op.add_column(
        "moderation_incidents",
        sa.Column("prompted_by_classification_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_incident_classification",
        "moderation_incidents",
        "message_classifications",
        ["message_classification_id", "telegram_chat_id", "telegram_message_id"],
        ["id", "telegram_chat_id", "telegram_message_id"],
    )
    op.create_foreign_key(
        "fk_incident_prompted_by",
        "moderation_incidents",
        "message_classifications",
        ["prompted_by_classification_id", "telegram_chat_id", "telegram_message_id"],
        ["id", "telegram_chat_id", "telegram_message_id"],
    )
    op.create_check_constraint(
        "ck_incident_ai_link",
        "moderation_incidents",
        "source <> 'ai' OR message_classification_id IS NOT NULL",
    )
    op.create_check_constraint(
        "ck_incident_prompted_by",
        "moderation_incidents",
        "prompted_by_classification_id IS NULL OR source = 'operator'",
    )

    # §5 — attention_items: the link TG-M3 shaped, and no more.
    op.create_foreign_key(
        "fk_attention_classification",
        "attention_items",
        "message_classifications",
        ["message_classification_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_attention_classification", "attention_items", type_="foreignkey")

    op.drop_constraint("ck_incident_prompted_by", "moderation_incidents", type_="check")
    op.drop_constraint("ck_incident_ai_link", "moderation_incidents", type_="check")
    op.drop_constraint("fk_incident_prompted_by", "moderation_incidents", type_="foreignkey")
    op.drop_constraint("fk_incident_classification", "moderation_incidents", type_="foreignkey")
    op.drop_column("moderation_incidents", "prompted_by_classification_id")

    op.drop_index("ix_attempts_message", table_name="message_classification_attempts")
    op.drop_index("uq_attempt_exclusion", table_name="message_classification_attempts")
    op.drop_table("message_classification_attempts")

    op.drop_index("ix_classifications_profile", table_name="message_classifications")
    op.drop_index("ix_classifications_possible", table_name="message_classifications")
    op.drop_index("uq_classification_current", table_name="message_classifications")
    op.drop_table("message_classifications")

    op.drop_constraint("ck_model_profiles_role", "model_profiles", type_="check")
    op.create_check_constraint(
        "ck_model_profiles_role",
        "model_profiles",
        "role IN ('llm', 'embedding')",
    )
