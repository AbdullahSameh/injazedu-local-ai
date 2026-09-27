"""policy incidents: moderation_incidents, moderation_actions, and the two derived-state views

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-24

data-model.md §1-§3. **Finding 3**: an incident stores only what was decided when it was
flagged — no `status` column and no `acknowledged_*` / `resolved_*` / `closed_*` columns.
`moderation_incident_evidence` and `moderation_incident_state` compute all of that, the **only**
definitions read by Python and PHP alike (lifecycle contract N6); this migration creates them
verbatim from `data-model.md` §3.1-§3.2. **TG-M3's Finding 2** applies unchanged: the anchor is
`UNIQUE (telegram_chat_id, telegram_message_id)`, not `telegram_message_id` alone — Telegram
numbers messages per chat from 1. No `GRANT` (`ALTER DEFAULT PRIVILEGES FOR ROLE ai_migrator`
already reaches `ai_control` for tables **and views**, research probe 6). No FK to
`message_classifications` — that table does not exist until `0007`. `0007`-`0009` stay reserved
for TG-M5/TG-M6.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "moderation_incidents",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "telegram_chat_id",
            sa.BigInteger(),
            sa.ForeignKey("telegram_chats.id"),
            nullable=False,
        ),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("opened_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("category", sa.String(length=30), nullable=False),
        sa.Column("severity", sa.String(length=10), nullable=False),
        sa.Column("message_classification_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "responsible_moderator_id",
            sa.BigInteger(),
            sa.ForeignKey("moderators.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "telegram_chat_id", "telegram_message_id", name="uq_incident_anchor"
        ),
        sa.ForeignKeyConstraint(
            ["telegram_chat_id", "telegram_message_id"],
            ["telegram_messages.telegram_chat_id", "telegram_messages.message_id"],
            name="fk_incident_message",
        ),
        sa.CheckConstraint("source IN ('operator', 'ai')", name="ck_incident_source"),
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

    op.create_table(
        "moderation_actions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "telegram_chat_id",
            sa.BigInteger(),
            sa.ForeignKey("telegram_chats.id"),
            nullable=False,
        ),
        sa.Column("action_type", sa.String(length=30), nullable=False),
        sa.Column("action_strength", sa.String(length=20), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "actor_telegram_user_id",
            sa.BigInteger(),
            sa.ForeignKey("telegram_users.id"),
            nullable=True,
        ),
        sa.Column(
            "actor_moderator_id",
            sa.BigInteger(),
            sa.ForeignKey("moderators.id"),
            nullable=True,
        ),
        sa.Column(
            "actor_is_anonymous", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("panel_user_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "subject_telegram_user_id",
            sa.BigInteger(),
            sa.ForeignKey("telegram_users.id"),
            nullable=True,
        ),
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
        sa.Column(
            "detail", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "source_update_id", name="uq_moderation_actions_source_update"
        ),
        sa.CheckConstraint(
            "action_type IN ('reaction', 'ban', 'expulsion', 'restriction', 'reversal', "
            "'panel_acknowledge', 'panel_resolve', 'panel_false_positive')",
            name="ck_actions_type",
        ),
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
        sa.CheckConstraint(
            r"(action_type LIKE 'panel\_%') = (moderation_incident_id IS NOT NULL)",
            name="ck_actions_panel_link",
        ),
        sa.CheckConstraint(
            r"(action_type LIKE 'panel\_%' "
            r"AND panel_user_id IS NOT NULL AND source_update_id IS NULL) "
            r"OR (action_type NOT LIKE 'panel\_%' AND source_update_id IS NOT NULL)",
            name="ck_actions_provenance",
        ),
        sa.CheckConstraint(
            "action_type NOT IN ('panel_resolve', 'panel_false_positive') OR "
            "(note IS NOT NULL AND btrim(note) <> '')",
            name="ck_actions_note",
        ),
        sa.CheckConstraint(
            "action_type NOT IN ('ban', 'expulsion', 'restriction', 'reversal') OR "
            "subject_telegram_user_id IS NOT NULL",
            name="ck_actions_membership_subject",
        ),
        sa.CheckConstraint(
            "action_type <> 'reaction' OR "
            "(target_message_id IS NOT NULL AND actor_moderator_id IS NOT NULL)",
            name="ck_actions_reaction_shape",
        ),
    )

    op.create_index("ix_incidents_detected", "moderation_incidents", ["detected_at"])
    op.create_index(
        "ix_incidents_chat",
        "moderation_incidents",
        ["telegram_chat_id", sa.text("detected_at DESC")],
    )
    op.create_index(
        "ix_incidents_moderator",
        "moderation_incidents",
        ["responsible_moderator_id", sa.text("detected_at DESC")],
    )
    op.create_index(
        "ix_actions_reaction_target",
        "moderation_actions",
        ["telegram_chat_id", "target_message_id"],
        postgresql_where=sa.text("action_type = 'reaction'"),
    )
    op.create_index(
        "ix_actions_subject",
        "moderation_actions",
        ["subject_telegram_user_id", "occurred_at"],
        postgresql_where=sa.text("subject_telegram_user_id IS NOT NULL"),
    )
    op.create_index(
        "ix_actions_incident",
        "moderation_actions",
        ["moderation_incident_id"],
        postgresql_where=sa.text("moderation_incident_id IS NOT NULL"),
    )

    # data-model.md §3.1 — the only definition of which evidence belongs to which incident
    # (lifecycle contract N6). Evidence first: the state view (§3.2) reads it.
    op.execute(
        """
        CREATE VIEW moderation_incident_evidence AS
        -- (a) a moderator's reaction added to the anchor
        SELECT i.id AS incident_id, 1 AS source_rank, a.id AS evidence_id,
               a.action_type AS kind, a.action_strength AS strength, a.occurred_at,
               a.actor_telegram_user_id, a.actor_moderator_id, a.actor_is_anonymous,
               a.panel_user_id,
               a.subject_telegram_user_id, a.source_update_id, a.note, a.detail
        FROM moderation_incidents i
        JOIN telegram_messages m   ON m.telegram_chat_id = i.telegram_chat_id
                                  AND m.message_id       = i.telegram_message_id
        JOIN moderation_actions a  ON a.action_type       = 'reaction'
                                  AND a.telegram_chat_id  = i.telegram_chat_id
                                  AND a.target_message_id = i.telegram_message_id
        WHERE a.occurred_at > i.opened_at
          AND a.actor_telegram_user_id IS DISTINCT FROM m.telegram_user_id

        UNION ALL
        -- (b) a moderator's direct reply to the anchor, read in place (FR-012)
        SELECT i.id, 2, r.id,
               'reply', 'acknowledgement', r.sent_at,
               r.telegram_user_id, mo.id, false, NULL,
               NULL, r.source_update_id, NULL, '{}'::jsonb
        FROM moderation_incidents i
        JOIN telegram_messages m   ON m.telegram_chat_id = i.telegram_chat_id
                                  AND m.message_id       = i.telegram_message_id
        JOIN telegram_messages r   ON r.telegram_chat_id    = i.telegram_chat_id
                                  AND r.reply_to_message_id = i.telegram_message_id
                                  AND r.is_from_moderator
        LEFT JOIN moderators mo    ON mo.telegram_user_id = r.telegram_user_id
        WHERE r.sent_at > i.opened_at
          AND r.telegram_user_id IS DISTINCT FROM m.telegram_user_id

        UNION ALL
        -- (c) a membership change against the anchor's sender, in the anchor's chat or its
        -- successor
        SELECT i.id, 1, a.id,
               a.action_type, a.action_strength, a.occurred_at,
               a.actor_telegram_user_id, a.actor_moderator_id, a.actor_is_anonymous,
               a.panel_user_id,
               a.subject_telegram_user_id, a.source_update_id, a.note, a.detail
        FROM moderation_incidents i
        JOIN telegram_messages m   ON m.telegram_chat_id = i.telegram_chat_id
                                  AND m.message_id       = i.telegram_message_id
        JOIN telegram_chats c      ON c.id = i.telegram_chat_id
        LEFT JOIN telegram_chats s ON s.chat_id = c.migrated_to_chat_id
        JOIN moderation_actions a  ON a.action_type IN
                                       ('ban', 'expulsion', 'restriction', 'reversal')
                                  AND a.subject_telegram_user_id = m.telegram_user_id
                                  AND (a.telegram_chat_id = i.telegram_chat_id
                                       OR a.telegram_chat_id = s.id)
        WHERE a.occurred_at > i.opened_at

        UNION ALL
        -- (d) a panel act on this incident
        SELECT i.id, 1, a.id,
               a.action_type, a.action_strength, a.occurred_at,
               a.actor_telegram_user_id, a.actor_moderator_id, a.actor_is_anonymous,
               a.panel_user_id,
               a.subject_telegram_user_id, a.source_update_id, a.note, a.detail
        FROM moderation_incidents i
        JOIN moderation_actions a  ON a.moderation_incident_id = i.id
        """
    )

    # data-model.md §3.2 — the only definition of status, moments and actors, derived
    # (lifecycle contract N6). `(occurred_at, source_rank, evidence_id)` is D-TG-106's tie-break.
    op.execute(
        """
        CREATE VIEW moderation_incident_state AS
        SELECT i.id AS incident_id,
               CASE WHEN fp.occurred_at  IS NOT NULL THEN 'closed_false_positive'
                    WHEN res.occurred_at IS NOT NULL THEN 'resolved'
                    WHEN ack.occurred_at IS NOT NULL THEN 'acknowledged'
                    ELSE 'open' END                              AS status,
               ack.occurred_at  AS first_acknowledgement_at, ack.kind AS acknowledgement_kind,
               ack.actor_moderator_id AS acknowledged_by_moderator_id,
               ack.panel_user_id AS acknowledged_by_user_id,
               enf.occurred_at  AS first_enforcement_at,
               conf.occurred_at AS first_confirmation_at,
               res.occurred_at  AS resolved_at, res.kind AS resolution_kind,
               res.strength AS resolution_strength,
               res.actor_moderator_id     AS resolved_by_moderator_id,
               res.actor_telegram_user_id AS resolved_by_telegram_user_id,
               res.actor_is_anonymous     AS resolved_by_anonymous,
               res.panel_user_id          AS resolved_by_user_id,
               fp.occurred_at   AS closed_at, fp.panel_user_id AS closed_by_user_id,
               fp.note AS close_reason
        FROM moderation_incidents i
        LEFT JOIN LATERAL (SELECT * FROM moderation_incident_evidence e
                           WHERE e.incident_id = i.id AND e.strength = 'acknowledgement'
                           ORDER BY e.occurred_at, e.source_rank, e.evidence_id
                           LIMIT 1) ack  ON true
        LEFT JOIN LATERAL (SELECT * FROM moderation_incident_evidence e
                           WHERE e.incident_id = i.id AND e.strength = 'enforcement'
                           ORDER BY e.occurred_at, e.source_rank, e.evidence_id
                           LIMIT 1) enf  ON true
        LEFT JOIN LATERAL (SELECT * FROM moderation_incident_evidence e
                           WHERE e.incident_id = i.id AND e.strength = 'confirmation'
                           ORDER BY e.occurred_at, e.source_rank, e.evidence_id
                           LIMIT 1) conf ON true
        LEFT JOIN LATERAL (SELECT * FROM moderation_incident_evidence e
                           WHERE e.incident_id = i.id
                             AND e.strength IN ('enforcement', 'confirmation')
                           ORDER BY e.occurred_at, e.source_rank, e.evidence_id
                           LIMIT 1) res  ON true
        LEFT JOIN LATERAL (SELECT * FROM moderation_incident_evidence e
                           WHERE e.incident_id = i.id AND e.kind = 'panel_false_positive'
                           ORDER BY e.occurred_at, e.evidence_id LIMIT 1) fp ON true
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW moderation_incident_state")
    op.execute("DROP VIEW moderation_incident_evidence")
    op.drop_index("ix_actions_incident", table_name="moderation_actions")
    op.drop_index("ix_actions_subject", table_name="moderation_actions")
    op.drop_index("ix_actions_reaction_target", table_name="moderation_actions")
    op.drop_index("ix_incidents_moderator", table_name="moderation_incidents")
    op.drop_index("ix_incidents_chat", table_name="moderation_incidents")
    op.drop_index("ix_incidents_detected", table_name="moderation_incidents")
    op.drop_table("moderation_actions")
    op.drop_table("moderation_incidents")
