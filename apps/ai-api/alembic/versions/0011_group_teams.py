"""Group teams and first-action assignment (TG-M2.1).

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-19

`specs/012-tg-m2-1-group-teams/data-model.md` §1-§5, `contracts/group-teams.md`.

- **The index swap** (T1, T2): `uq_assignment_one_current_primary` allowed one current primary
  per group. `uq_assignment_one_current_membership` allows a team, one current row per moderator
  per group whatever the role.
- **`attention_items.closed_by_moderator_id`** (C1): the moderator linked to the panel account that
  dismissed the item, snapshotted at write time.
- **Three views:**
  - `moderation_team_intervals` (T3) is the one definition of a team, following a chat migration one
    hop;
  - `attention_item_assignee` and `moderation_incident_assignee` (G2-G6) derive each assigned
    moderator from recorded acts, never stored.

No `GRANT`: `ALTER DEFAULT PRIVILEGES FOR ROLE ai_migrator` already reaches `ai_app` and
`ai_control` for new views, and table-level privileges cover a new column. No existing row is
touched.

The downgrade restores the old index. It fails loudly while any group has two current members,
rather than choosing one (data-model §1).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("uq_assignment_one_current_primary", table_name="moderator_group_assignments")
    op.create_index(
        "uq_assignment_one_current_membership",
        "moderator_group_assignments",
        ["telegram_chat_id", "moderator_id"],
        unique=True,
        postgresql_where=sa.text("valid_to IS NULL"),
    )

    op.add_column(
        "attention_items",
        sa.Column(
            "closed_by_moderator_id",
            sa.BigInteger(),
            sa.ForeignKey("moderators.id", name="fk_attention_closed_by_moderator"),
            nullable=True,
        ),
    )

    # data-model.md §3 — T3: the only definition of "on the team". A membership on group S is
    # listed for S and for every group whose `migrated_to_chat_id` is S's platform id, because a
    # migration re-points memberships but leaves items, incidents and messages on the superseded
    # row (ownership contract §6, D-TG-107).
    op.execute(
        """
        CREATE VIEW moderation_team_intervals AS
        SELECT a.id AS assignment_id,
               c.id AS telegram_chat_id,
               a.moderator_id,
               a.valid_from,
               a.valid_to
        FROM moderator_group_assignments a
        JOIN telegram_chats own ON own.id = a.telegram_chat_id
        JOIN telegram_chats c   ON c.id = own.id
                                OR (c.migrated_to_chat_id IS NOT NULL
                                    AND c.migrated_to_chat_id = own.chat_id)
        WHERE a.assignment_role = 'primary'
        """
    )

    # data-model.md §4 — G2, G4, G5: the earliest act, by a team member at that instant, at or
    # before the item's end. Ranked reply, dismissal, reaction on a tied instant.
    op.execute(
        """
        CREATE VIEW attention_item_assignee AS
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
                                    AND m.attention_item_id = i.id))
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
    )

    # data-model.md §5 — G3, G4, G5: the earliest non-reversal evidence by a team member at that
    # instant, at or before the incident's end, in D-TG-106's order.
    op.execute(
        """
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
    )


def downgrade() -> None:
    op.execute("DROP VIEW moderation_incident_assignee")
    op.execute("DROP VIEW attention_item_assignee")
    op.execute("DROP VIEW moderation_team_intervals")
    op.drop_column("attention_items", "closed_by_moderator_id")
    op.drop_index("uq_assignment_one_current_membership", table_name="moderator_group_assignments")
    op.create_index(
        "uq_assignment_one_current_primary",
        "moderator_group_assignments",
        ["telegram_chat_id"],
        unique=True,
        postgresql_where=sa.text("assignment_role = 'primary' AND valid_to IS NULL"),
    )
