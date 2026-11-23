# Data Model: TG-M6 — Alerts

One revision, **`0013_moderation_alerts`** (`down_revision = "0012"`). Alembic owns it, and the panel adds no
migration. There is no `GRANT`, because the migrator's default ACL already reaches `ai_control` and `ai_app`.
ORM parity goes in `app/infrastructure/models_moderation.py`.

## §1 — `telegram_chats`: the destination flag (D-TG-211)

| Column | Type | Notes |
|---|---|---|
| `is_alert_destination` | `BOOLEAN NOT NULL DEFAULT false` | set and cleared only by the panel |

- `uq_chat_one_alert_destination`: `UNIQUE ((true)) WHERE is_alert_destination`. There is at most one
  destination (FR-501).
- `ck_chat_destination_not_monitored`: `NOT (is_alert_destination AND is_monitored)` (FR-502). It refuses
  both orders: designating a monitored chat, and monitoring the designated chat.

## §2 — `alert_rules` (D-TG-212)

| Column | Type | Notes |
|---|---|---|
| `id` | `BIGSERIAL PK` | |
| `trigger` | `VARCHAR(30) NOT NULL` | `question_waiting` · `incident_flagged` · `incident_unhandled` · `group_silent` · `bot_not_admin` |
| `telegram_chat_id` | `BIGINT NULL FK telegram_chats(id)` | NULL means all groups |
| `threshold_s` | `INTEGER NULL` | |
| `min_severity` | `VARCHAR(10) NULL` | `low` · `medium` · `high` |
| `categories` | `JSONB NULL` | an array of taxonomy codes; NULL means any |
| `openers` | `JSONB NULL` | an array, a subset of `rule` · `ai` · `operator`; NULL means any |
| `repeat_every_s` | `INTEGER NULL` | |
| `max_repeats` | `SMALLINT NULL` | |
| `quiet_hours` | `JSONB NOT NULL DEFAULT '[]'` | `[{"from": "HH:MM", "to": "HH:MM"}, …]`, in `Asia/Riyadh` |
| `is_enabled` | `BOOLEAN NOT NULL DEFAULT false` | |
| `enabled_at` | `TIMESTAMPTZ NULL` | stamped on every change from disabled to enabled (FR-515) |
| `updated_by_user_id` | `BIGINT NULL` | the panel user who last saved the rule |
| `created_at`, `updated_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | |

Constraints:
- `ck_alert_rule_trigger`: `trigger IN (…the five…)`.
- `ck_alert_rule_threshold`: two conditions:
  - `(trigger IN ('question_waiting','incident_unhandled','group_silent')) = (threshold_s IS NOT NULL)`;
  - `threshold_s IS NULL OR threshold_s > 0`.
- `ck_alert_rule_filters`: `trigger IN ('incident_flagged','incident_unhandled') OR (min_severity IS NULL AND
  categories IS NULL AND openers IS NULL)`.
- `ck_alert_rule_severity`: `min_severity IS NULL OR min_severity IN ('low','medium','high')`.
- `ck_alert_rule_repeats`: two conditions:
  - `(repeat_every_s IS NULL) = (max_repeats IS NULL)`;
  - `repeat_every_s IS NULL OR (repeat_every_s > 0 AND max_repeats > 0)`.
- `ck_alert_rule_quiet_hours`: `jsonb_typeof(quiet_hours) = 'array'`. The window shape and `from <> to` are
  checked by the panel's validation and by the evaluator's parser, which skips a malformed window and logs
  `rule_id`.
- `ck_alert_rule_enabled_at`: `NOT is_enabled OR enabled_at IS NOT NULL`.
- `uq_alert_rule_global`: `UNIQUE (trigger) WHERE telegram_chat_id IS NULL`.
- `uq_alert_rule_chat`: `UNIQUE (trigger, telegram_chat_id) WHERE telegram_chat_id IS NOT NULL`.

**The rule in force** for chat C and trigger T is C's row for T if one exists, enabled or not. Otherwise it is
the global row for T. A disabled chat row mutes T for C (FR-513).

## §3 — `alerts`

| Column | Type | Notes |
|---|---|---|
| `id` | `BIGSERIAL PK` | |
| `alert_rule_id` | `BIGINT NOT NULL FK alert_rules(id) ON DELETE RESTRICT` | FR-514 |
| `trigger` | `VARCHAR(30) NOT NULL` | copied from the rule at firing |
| `telegram_chat_id` | `BIGINT NOT NULL FK telegram_chats(id)` | the **source** group |
| `subject_type` | `VARCHAR(20) NOT NULL` | `attention_item` · `incident` · `chat` |
| `subject_id` | `BIGINT NOT NULL` | `attention_items.id`, `moderation_incidents.id` or `telegram_chats.id` |
| `episode_at` | `TIMESTAMPTZ NULL` | health only: the `last_event_at` or `bot_status_at` that opened the episode |
| `repeat_index` | `SMALLINT NOT NULL` | 0 for the first alert |
| `dedupe_key` | `VARCHAR(160) NOT NULL` | `{rule}:{subject_type}:{subject_id}[@{episode epoch}]:{repeat_index}` |
| `rule_values` | `JSONB NOT NULL` | the threshold, filters, repeats and quiet hours in force at firing |
| `qualified_at` | `TIMESTAMPTZ NOT NULL` | the subject's qualifying moment (FR-515) |
| `fired_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | |
| `delivery_status` | `VARCHAR(12) NOT NULL DEFAULT 'pending'` | §3.1 |
| `not_sent_reason` | `VARCHAR(20) NULL` | `no_destination` · `subject_ended` |
| `attempts` | `SMALLINT NOT NULL DEFAULT 0` | |
| `last_error_category` | `VARCHAR(40) NULL` | the provider's error category; never a message text |
| `last_error_at` | `TIMESTAMPTZ NULL` | |
| `delivered_at` | `TIMESTAMPTZ NULL` | |
| `sent_chat_id` | `BIGINT NULL` | the platform chat id it was posted to |
| `sent_message_id` | `BIGINT NULL` | |
| `rendered_state` | `JSONB NULL` | the inputs of the last rendered text (D-TG-216); never the text |
| `excerpt_shown` | `BOOLEAN NOT NULL DEFAULT false` | true while the posted text contains an excerpt |
| `final_at` | `TIMESTAMPTZ NULL` | when the alert last rendered its subject's end |
| `last_edit_at` | `TIMESTAMPTZ NULL` | |
| `edit_attempts` | `SMALLINT NOT NULL DEFAULT 0` | reset to 0 on a successful edit |
| `last_edit_error_category` | `VARCHAR(40) NULL` | |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | |

Constraints:
- `uq_alerts_dedupe`: `UNIQUE (dedupe_key)`. Postgres, not a TTL, makes alerting idempotent (FR-522).
- `ck_alerts_subject_type`: `subject_type IN ('attention_item','incident','chat')`.
- `ck_alerts_episode`: `(subject_type = 'chat') = (episode_at IS NOT NULL)`.
- `ck_alerts_repeat`: `repeat_index >= 0`.
- `ck_alerts_status`: `delivery_status IN ('pending','sending','sent','failed','suppressed','not_sent')`.
- `ck_alerts_not_sent`: `(delivery_status = 'not_sent') = (not_sent_reason IS NOT NULL)`.
- `ck_alerts_posted`: `(delivery_status = 'sent') = (sent_message_id IS NOT NULL AND sent_chat_id IS NOT NULL)`.
- `uq_alerts_posted`: `UNIQUE (sent_chat_id, sent_message_id) WHERE sent_message_id IS NOT NULL`. A press finds
  its alert by this key (D-TG-219).

Indexes:
- `ix_alerts_subject`: `(alert_rule_id, subject_type, subject_id, episode_at)`, for the first alert and
  repeats.
- `ix_alerts_live`: `(id) WHERE delivery_status = 'sent' AND final_at IS NULL`, for the refresh scan.
- `ix_alerts_excerpt`: `(id) WHERE excerpt_shown`, for the retention scan.
- `ix_alerts_fired`: `(fired_at DESC)`, for the history.

### §3.1 Delivery status

```
pending ──claim──▶ sending ──200──▶ sent
   │                  │──connect failure / 5xx / 429 (attempt < 5)──▶ failed ──backoff──▶ (claimed again)
   │                  │──attempt 5 fails──▶ failed (final)
   │                  └──outcome unknown──▶ failed, category telegram_outcome_unknown (final, D-TG-215)
   ├──firing inside quiet hours──▶ suppressed   (set at insert; never claimed)
   ├──no destination at claim──▶ not_sent / no_destination
   └──subject no longer qualifies at claim──▶ not_sent / subject_ended
```

`sent` is terminal for delivery. Later edits change only the `*_edit_*` columns, `rendered_state`,
`excerpt_shown` and `final_at`.

## §4 — `moderation_actions`: three alert kinds (D-TG-217)

New column: `alert_id BIGINT NULL FK alerts(id) ON DELETE RESTRICT`. New index: `ix_actions_alert (alert_id)
WHERE alert_id IS NOT NULL`.

Constraint changes, each dropped and re-created:
- `ck_actions_type` adds `'alert_handled', 'alert_false_positive', 'alert_take'`.
- `ck_actions_strength` adds `(action_type = 'alert_handled' AND action_strength = 'confirmation') OR
  (action_type IN ('alert_false_positive','alert_take') AND action_strength IS NULL)`.
- `ck_actions_panel_link` becomes `(action_type LIKE 'panel\_%' OR action_type IN ('alert_handled',
  'alert_false_positive')) = (moderation_incident_id IS NOT NULL)`.
- New: `ck_actions_alert_link`: `(action_type LIKE 'alert\_%') = (alert_id IS NOT NULL)`.
- New: `ck_actions_alert_actor`: `action_type NOT LIKE 'alert\_%' OR (actor_moderator_id IS NOT NULL AND
  actor_telegram_user_id IS NOT NULL AND panel_user_id IS NULL)`.

Unchanged and relied on:
- `ck_actions_provenance`: an alert act is not `panel_*`, so it must carry `source_update_id`.
- `uq_moderation_actions_source_update`: one act per press.
- `ck_actions_note`: it binds `panel_*` kinds only, so `alert_false_positive` has no note.

`telegram_chat_id` is the **source** group's: the group where the subject lives, never the alert group.

## §5 — Views, replaced in place (D-TG-218)

### §5.1 `moderation_incident_state`

The 0006 definition is kept with two changes:
- the false-positive lateral reads both closure kinds;
- two columns are appended at the end.

```sql
CREATE OR REPLACE VIEW moderation_incident_state AS
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
       fp.note AS close_reason,
       fp.kind               AS close_kind,               -- appended (TG-M6)
       fp.actor_moderator_id AS closed_by_moderator_id    -- appended (TG-M6)
FROM moderation_incidents i
LEFT JOIN LATERAL (… ack, enf, conf, res exactly as 0006 …)
LEFT JOIN LATERAL (SELECT * FROM moderation_incident_evidence e
                   WHERE e.incident_id = i.id
                     AND e.kind IN ('panel_false_positive', 'alert_false_positive')
                   ORDER BY e.occurred_at, e.evidence_id LIMIT 1) fp ON true
```

The evidence view itself is unchanged: branch (d) already selects any act that names the incident (Finding 26).
An `alert_handled` row is a `confirmation` and resolves through `conf`/`res` like `panel_resolve`.

### §5.2 `attention_item_assignee`

The 0011 definition gains a fourth branch inside the `act` union:

```sql
UNION ALL
SELECT a.actor_moderator_id, a.occurred_at, 'alert', 4, a.id
FROM moderation_actions a
JOIN alerts al ON al.id = a.alert_id
WHERE a.action_type = 'alert_take'
  AND al.subject_type = 'attention_item'
  AND al.subject_id   = i.id
```

The live bound (`act.at <= COALESCE(first_response_at, closed_at, 'infinity')`), the team check and the order
`(at, act_rank, act_id)` apply to it unchanged. On a tied instant a take ranks after a reaction.

## §6 — Downgrade

The downgrade restores 0012's constraints and views and drops §1–§4. **It fails loudly while any `alert_*`
action exists**, as 0012's does, rather than rewriting a recorded act. Removing the alerts' history is a
deliberate operator decision: delete the alert acts by hand, then downgrade.

## §7 — Configuration

One new key: `MODERATION_PANEL_BASE_URL`. It is non-secret and optional, for example
`https://panel.example.org`. When blank, alerts carry no panel link (D-TG-224). It is added to `.env.example`
and `infra/docker-compose.yml` (`ai-worker`, `ai-telegram`), and is checked as a URL when set.
