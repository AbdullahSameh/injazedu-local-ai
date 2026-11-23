"""Alerts: the destination, rules, alerts, three button acts (TG-M6).

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-14

`specs/013-tg-m6-alerts/data-model.md` §1-§6, `contracts/alerting.md`.

- **§1 `telegram_chats.is_alert_destination`** (D-TG-211): at most one destination
  (`uq_chat_one_alert_destination`), and never a monitored chat, in either order
  (`ck_chat_destination_not_monitored`).
- **§2 `alert_rules`** (D-TG-212): operator data. Nothing is seeded; no threshold is in code.
- **§3 `alerts`**: one row per rule, subject, episode and repeat (`uq_alerts_dedupe`). A press finds
  its alert by `uq_alerts_posted`.
- **§4 `moderation_actions`**: `alert_id` and three kinds (D-TG-217). `alert_handled` is a
  confirmation and names its incident, `alert_false_positive` names its incident, and `alert_take`
  names neither: it reaches its item through `alerts.subject_id`.
- **§5 two views, replaced in place** (D-TG-218):
  - `moderation_incident_state`: the false-positive lateral reads both closure kinds, and
    `close_kind` and `closed_by_moderator_id` are appended;
  - `attention_item_assignee`: a fourth branch, `alert_take`, rank 4, via `'alert'`.

No `GRANT`: the migrator's default ACL reaches `ai_app` and `ai_control` for new tables and views.
No existing row is touched.

The downgrade restores 0012's constraints and views. It fails loudly while any `alert_*` act exists,
rather than rewriting a recorded act (§6).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

_TRIGGERS = (
    "'question_waiting', 'incident_flagged', 'incident_unhandled', 'group_silent', "
    "'bot_not_admin'"
)

# --- moderation_actions: the three re-created CHECKs (0012's text, then TG-M6's) ---

_OLD_TYPE = (
    "action_type IN ('reaction', 'ban', 'expulsion', 'restriction', 'reversal', "
    "'panel_acknowledge', 'panel_resolve', 'panel_false_positive')"
)
_NEW_TYPE = (
    "action_type IN ('reaction', 'ban', 'expulsion', 'restriction', 'reversal', "
    "'panel_acknowledge', 'panel_resolve', 'panel_false_positive', "
    "'alert_handled', 'alert_false_positive', 'alert_take')"
)

_OLD_STRENGTH = (
    "(action_type = 'reaction' AND action_strength IN ('acknowledgement', 'confirmation')) OR "
    "(action_type IN ('ban', 'expulsion', 'restriction') "
    "AND action_strength = 'enforcement') OR "
    "(action_type = 'reversal' AND action_strength IS NULL) OR "
    "(action_type = 'panel_acknowledge' AND action_strength = 'acknowledgement') OR "
    "(action_type = 'panel_resolve' AND action_strength = 'confirmation') OR "
    "(action_type = 'panel_false_positive' AND action_strength IS NULL)"
)
_NEW_STRENGTH = (
    _OLD_STRENGTH + " OR "
    "(action_type = 'alert_handled' AND action_strength = 'confirmation') OR "
    "(action_type IN ('alert_false_positive', 'alert_take') AND action_strength IS NULL)"
)

_OLD_PANEL_LINK = r"(action_type LIKE 'panel\_%') = (moderation_incident_id IS NOT NULL)"
_NEW_PANEL_LINK = (
    r"(action_type LIKE 'panel\_%' "
    r"OR action_type IN ('alert_handled', 'alert_false_positive')) "
    r"= (moderation_incident_id IS NOT NULL)"
)

_ALERT_LINK = r"(action_type LIKE 'alert\_%') = (alert_id IS NOT NULL)"
_ALERT_ACTOR = (
    r"action_type NOT LIKE 'alert\_%' OR "
    r"(actor_moderator_id IS NOT NULL AND actor_telegram_user_id IS NOT NULL "
    r"AND panel_user_id IS NULL)"
)

# --- the views (0006's state view and 0011's attention assignee, then TG-M6's) ---

_STATE_LATERALS = """
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
"""

_STATE_COLUMNS = """
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
       fp.note AS close_reason"""

_OLD_STATE_VIEW = (
    "CREATE VIEW moderation_incident_state AS"
    + _STATE_COLUMNS
    + _STATE_LATERALS
    + """LEFT JOIN LATERAL (SELECT * FROM moderation_incident_evidence e
                   WHERE e.incident_id = i.id AND e.kind = 'panel_false_positive'
                   ORDER BY e.occurred_at, e.evidence_id LIMIT 1) fp ON true
"""
)

# data-model.md §5.1: `close_kind` and `closed_by_moderator_id` are appended last, so every
# existing column keeps its name and position and `CREATE OR REPLACE` is allowed.
_NEW_STATE_VIEW = (
    "CREATE OR REPLACE VIEW moderation_incident_state AS"
    + _STATE_COLUMNS
    + """,
       fp.kind               AS close_kind,
       fp.actor_moderator_id AS closed_by_moderator_id"""
    + _STATE_LATERALS
    + """LEFT JOIN LATERAL (SELECT * FROM moderation_incident_evidence e
                   WHERE e.incident_id = i.id
                     AND e.kind IN ('panel_false_positive', 'alert_false_positive')
                   ORDER BY e.occurred_at, e.evidence_id LIMIT 1) fp ON true
"""
)

# 0011's definition, restored on the downgrade after the state view is re-created.
_INCIDENT_ASSIGNEE_VIEW = """
CREATE VIEW moderation_incident_assignee AS
SELECT i.id                 AS incident_id,
       x.actor_moderator_id AS assigned_moderator_id,
       x.occurred_at        AS assigned_at,
       x.kind               AS assigned_via
FROM moderation_incidents i
JOIN moderation_incident_state s ON s.incident_id = i.id
LEFT JOIN LATERAL (
    SELECT e.actor_moderator_id, e.occurred_at, e.kind
    FROM moderation_incident_evidence e
    WHERE e.incident_id = i.id
      AND e.kind <> 'reversal'
      AND e.actor_moderator_id IS NOT NULL
      AND e.occurred_at <= COALESCE(LEAST(s.resolved_at, s.closed_at),
                                    'infinity'::timestamptz)
      AND EXISTS (SELECT 1 FROM moderation_team_intervals t
                  WHERE t.telegram_chat_id = i.telegram_chat_id
                    AND t.moderator_id     = e.actor_moderator_id
                    AND t.valid_from      <= e.occurred_at
                    AND (t.valid_to IS NULL OR t.valid_to > e.occurred_at))
    ORDER BY e.occurred_at, e.source_rank, e.evidence_id
    LIMIT 1
) x ON true
"""

_ITEM_ASSIGNEE_HEAD = """
SELECT i.id         AS attention_item_id,
       x.moderator_id AS assigned_moderator_id,
       x.at           AS assigned_at,
       x.via          AS assigned_via
FROM attention_items i
LEFT JOIN LATERAL (
    SELECT act.moderator_id, act.at, act.via
    FROM (
        SELECT i.first_response_moderator_id AS moderator_id,
               i.first_response_at           AS at,
               'reply'::text                 AS via,
               1                             AS act_rank,
               i.id                          AS act_id
        WHERE i.status = 'answered' AND i.first_response_moderator_id IS NOT NULL
        UNION ALL
        SELECT i.closed_by_moderator_id, i.closed_at, 'dismissal', 2, i.id
        WHERE i.status = 'dismissed' AND i.closed_by_moderator_id IS NOT NULL
        UNION ALL
        SELECT a.actor_moderator_id, a.occurred_at, 'reaction', 3, a.id
        FROM moderation_actions a
        WHERE a.action_type = 'reaction'
          AND a.actor_moderator_id IS NOT NULL
          AND a.telegram_chat_id = i.telegram_chat_id
          AND (a.target_message_id = i.telegram_message_id
               OR EXISTS (SELECT 1 FROM telegram_messages m
                          WHERE m.telegram_chat_id = i.telegram_chat_id
                            AND m.message_id       = a.target_message_id
                            AND m.attention_item_id = i.id))"""

# data-model.md §5.2: an `alert_take` reaches its item through the alert it was pressed on.
_ITEM_ASSIGNEE_TAKE = """
        UNION ALL
        SELECT a.actor_moderator_id, a.occurred_at, 'alert', 4, a.id
        FROM moderation_actions a
        JOIN alerts al ON al.id = a.alert_id
        WHERE a.action_type = 'alert_take'
          AND al.subject_type = 'attention_item'
          AND al.subject_id   = i.id"""

_ITEM_ASSIGNEE_TAIL = """
    ) act
    WHERE act.at <= COALESCE(i.first_response_at, i.closed_at, 'infinity'::timestamptz)
      AND EXISTS (SELECT 1 FROM moderation_team_intervals t
                  WHERE t.telegram_chat_id = i.telegram_chat_id
                    AND t.moderator_id     = act.moderator_id
                    AND t.valid_from      <= act.at
                    AND (t.valid_to IS NULL OR t.valid_to > act.at))
    ORDER BY act.at, act.act_rank, act.act_id
    LIMIT 1
) x ON true
"""

_OLD_ITEM_ASSIGNEE_VIEW = (
    "CREATE OR REPLACE VIEW attention_item_assignee AS"
    + _ITEM_ASSIGNEE_HEAD
    + _ITEM_ASSIGNEE_TAIL
)
_NEW_ITEM_ASSIGNEE_VIEW = (
    "CREATE OR REPLACE VIEW attention_item_assignee AS"
    + _ITEM_ASSIGNEE_HEAD
    + _ITEM_ASSIGNEE_TAKE
    + _ITEM_ASSIGNEE_TAIL
)


def upgrade() -> None:
    # §1 — the destination flag (D-TG-211).
    op.add_column(
        "telegram_chats",
        sa.Column(
            "is_alert_destination", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_chat_one_alert_destination ON telegram_chats ((true)) "
        "WHERE is_alert_destination"
    )
    op.create_check_constraint(
        "ck_chat_destination_not_monitored",
        "telegram_chats",
        "NOT (is_alert_destination AND is_monitored)",
    )

    # §2 — alert_rules (D-TG-212).
    op.create_table(
        "alert_rules",
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
        sa.Column(
            "quiet_hours", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("enabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_by_user_id", sa.BigInteger(), nullable=True),
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
        sa.CheckConstraint(f"trigger IN ({_TRIGGERS})", name="ck_alert_rule_trigger"),
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
        sa.CheckConstraint(
            "jsonb_typeof(quiet_hours) = 'array'", name="ck_alert_rule_quiet_hours"
        ),
        sa.CheckConstraint(
            "NOT is_enabled OR enabled_at IS NOT NULL", name="ck_alert_rule_enabled_at"
        ),
    )
    op.create_index(
        "uq_alert_rule_global",
        "alert_rules",
        ["trigger"],
        unique=True,
        postgresql_where=sa.text("telegram_chat_id IS NULL"),
    )
    op.create_index(
        "uq_alert_rule_chat",
        "alert_rules",
        ["trigger", "telegram_chat_id"],
        unique=True,
        postgresql_where=sa.text("telegram_chat_id IS NOT NULL"),
    )

    # §3 — alerts.
    op.create_table(
        "alerts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "alert_rule_id",
            sa.BigInteger(),
            sa.ForeignKey("alert_rules.id", name="fk_alerts_rule", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("trigger", sa.String(length=30), nullable=False),
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
        sa.Column(
            "excerpt_shown", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("final_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_edit_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "edit_attempts", sa.SmallInteger(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("last_edit_error_category", sa.String(length=40), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("dedupe_key", name="uq_alerts_dedupe"),
        sa.CheckConstraint(
            "subject_type IN ('attention_item', 'incident', 'chat')",
            name="ck_alerts_subject_type",
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
    op.create_index(
        "uq_alerts_posted",
        "alerts",
        ["sent_chat_id", "sent_message_id"],
        unique=True,
        postgresql_where=sa.text("sent_message_id IS NOT NULL"),
    )
    op.create_index(
        "ix_alerts_subject",
        "alerts",
        ["alert_rule_id", "subject_type", "subject_id", "episode_at"],
    )
    op.create_index(
        "ix_alerts_live",
        "alerts",
        ["id"],
        postgresql_where=sa.text("delivery_status = 'sent' AND final_at IS NULL"),
    )
    op.create_index(
        "ix_alerts_excerpt", "alerts", ["id"], postgresql_where=sa.text("excerpt_shown")
    )
    op.create_index("ix_alerts_fired", "alerts", [sa.text("fired_at DESC")])

    # §4 — moderation_actions: three alert kinds (D-TG-217).
    op.add_column(
        "moderation_actions",
        sa.Column(
            "alert_id",
            sa.BigInteger(),
            sa.ForeignKey("alerts.id", name="fk_actions_alert", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_actions_alert",
        "moderation_actions",
        ["alert_id"],
        postgresql_where=sa.text("alert_id IS NOT NULL"),
    )
    op.drop_constraint("ck_actions_type", "moderation_actions", type_="check")
    op.create_check_constraint("ck_actions_type", "moderation_actions", _NEW_TYPE)
    op.drop_constraint("ck_actions_strength", "moderation_actions", type_="check")
    op.create_check_constraint("ck_actions_strength", "moderation_actions", _NEW_STRENGTH)
    op.drop_constraint("ck_actions_panel_link", "moderation_actions", type_="check")
    op.create_check_constraint("ck_actions_panel_link", "moderation_actions", _NEW_PANEL_LINK)
    op.create_check_constraint("ck_actions_alert_link", "moderation_actions", _ALERT_LINK)
    op.create_check_constraint("ck_actions_alert_actor", "moderation_actions", _ALERT_ACTOR)

    # §5 — the two views, replaced in place (D-TG-218).
    op.execute(_NEW_STATE_VIEW)
    op.execute(_NEW_ITEM_ASSIGNEE_VIEW)


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM moderation_actions WHERE action_type LIKE 'alert\\_%') THEN
                RAISE EXCEPTION 'cannot downgrade 0013: an alert button act is recorded, '
                                'and a recorded act is never rewritten';
            END IF;
        END $$;
        """
    )
    # The take branch reads `alerts`, so 0011's definition comes back before the table goes.
    op.execute(_OLD_ITEM_ASSIGNEE_VIEW)
    # `CREATE OR REPLACE` cannot drop the two appended columns, so the state view and the one view
    # that reads it are dropped and re-created exactly as 0006 and 0011 left them.
    op.execute("DROP VIEW moderation_incident_assignee")
    op.execute("DROP VIEW moderation_incident_state")
    op.execute(_OLD_STATE_VIEW)
    op.execute(_INCIDENT_ASSIGNEE_VIEW)

    op.drop_constraint("ck_actions_alert_actor", "moderation_actions", type_="check")
    op.drop_constraint("ck_actions_alert_link", "moderation_actions", type_="check")
    op.drop_constraint("ck_actions_panel_link", "moderation_actions", type_="check")
    op.create_check_constraint("ck_actions_panel_link", "moderation_actions", _OLD_PANEL_LINK)
    op.drop_constraint("ck_actions_strength", "moderation_actions", type_="check")
    op.create_check_constraint("ck_actions_strength", "moderation_actions", _OLD_STRENGTH)
    op.drop_constraint("ck_actions_type", "moderation_actions", type_="check")
    op.create_check_constraint("ck_actions_type", "moderation_actions", _OLD_TYPE)
    op.drop_index("ix_actions_alert", table_name="moderation_actions")
    op.drop_column("moderation_actions", "alert_id")

    op.drop_table("alerts")
    op.drop_table("alert_rules")

    op.drop_constraint("ck_chat_destination_not_monitored", "telegram_chats", type_="check")
    op.execute("DROP INDEX uq_chat_one_alert_destination")
    op.drop_column("telegram_chats", "is_alert_destination")
