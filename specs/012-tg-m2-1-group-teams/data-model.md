# Data Model: TG-M2.1 — revision `0011_group_teams`

Additive except for one index swap. No table is dropped or rewritten, and no row is updated. There is no
`GRANT`: the migrator's default ACL reaches `ai_app` and `ai_control` for new views.

## §1 — `moderator_group_assignments`: the index swap

| Before (0004) | After (0011) |
|---|---|
| `uq_assignment_one_current_primary` UNIQUE `(telegram_chat_id)` WHERE `assignment_role = 'primary' AND valid_to IS NULL` | **dropped** |
| — | `uq_assignment_one_current_membership` UNIQUE `(telegram_chat_id, moderator_id)` WHERE `valid_to IS NULL` |

The new index spans both roles: a moderator is current in a group at most once, whether as a member or a
backup. Existing data satisfies it. Production backups have no write path, so no row has both a current
primary and a current backup for one moderator.

**Downgrade** restores the old index. It fails loudly (unique violation) if any group has two current
members by then. That is intended: picking one would silently discard an ownership fact.

## §2 — `attention_items.closed_by_moderator_id`

`BIGINT NULL`, FK `moderators.id`. It is set only by a panel dismissal whose user is linked to a moderator
(contract C1), at write time, and never updated afterwards. There is no check constraint: NULL is the normal
value for every non-dismissed item and for an unlinked dismissal.

## §3 — `moderation_team_intervals` (view)

```sql
CREATE VIEW moderation_team_intervals AS
SELECT a.id            AS assignment_id,
       c.id            AS telegram_chat_id,
       a.moderator_id,
       a.valid_from,
       a.valid_to
FROM moderator_group_assignments a
JOIN telegram_chats own ON own.id = a.telegram_chat_id
JOIN telegram_chats c   ON c.id = own.id
                        OR (c.migrated_to_chat_id IS NOT NULL AND c.migrated_to_chat_id = own.chat_id)
WHERE a.assignment_role = 'primary';
```

A membership on group *S* is listed once for *S* and once for every group whose `migrated_to_chat_id` is
*S*'s platform id. Assignments are re-pointed by a migration, but items, incidents and messages stay on the
superseded row (ownership contract §6, D-TG-107).

## §4 — `attention_item_assignee` (view)

```sql
CREATE VIEW attention_item_assignee AS
SELECT i.id AS attention_item_id,
       x.moderator_id AS assigned_moderator_id,
       x.at           AS assigned_at,
       x.via          AS assigned_via
FROM attention_items i
LEFT JOIN LATERAL (
    SELECT act.moderator_id, act.at, act.via
    FROM (
        SELECT i.first_response_moderator_id AS moderator_id, i.first_response_at AS at,
               'reply'::text AS via, 1 AS act_rank, i.id AS act_id
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
                            AND m.message_id = a.target_message_id
                            AND m.attention_item_id = i.id))
    ) act
    WHERE act.at <= COALESCE(i.first_response_at, i.closed_at, 'infinity'::timestamptz)
      AND EXISTS (SELECT 1 FROM moderation_team_intervals t
                  WHERE t.telegram_chat_id = i.telegram_chat_id
                    AND t.moderator_id = act.moderator_id
                    AND t.valid_from <= act.at
                    AND (t.valid_to IS NULL OR t.valid_to > act.at))
    ORDER BY act.at, act.act_rank, act.act_id
    LIMIT 1
) x ON true;
```

## §5 — `moderation_incident_assignee` (view)

```sql
CREATE VIEW moderation_incident_assignee AS
SELECT i.id AS incident_id,
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
      AND e.occurred_at <= COALESCE(LEAST(s.resolved_at, s.closed_at), 'infinity'::timestamptz)
      AND EXISTS (SELECT 1 FROM moderation_team_intervals t
                  WHERE t.telegram_chat_id = i.telegram_chat_id
                    AND t.moderator_id = e.actor_moderator_id
                    AND t.valid_from <= e.occurred_at
                    AND (t.valid_to IS NULL OR t.valid_to > e.occurred_at))
    ORDER BY e.occurred_at, e.source_rank, e.evidence_id
    LIMIT 1
) x ON true;
```

0006's two views are unchanged in definition. Their output changes in one way: the moderator actor
columns of panel-act rows are now filled for linked users (contract C1).

## §6 — `responsible_moderator_id`

The column, its FK and its index stay. New rows get NULL (G1). Nothing reads it for a figure (N6). The
panel no longer displays it.
