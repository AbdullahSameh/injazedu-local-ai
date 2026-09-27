# Data Model: TG-M4 — Policy Incidents

**Feature**: `specs/007-tg-m4-policy-incidents`
**Revision**: `0006_moderation_incidents` — down-revision `0005`, confirmed head in both databases
(research probe 4). `0007`–`0009` stay reserved for TG-M5…TG-M6.

Two tables created, two views created, nothing altered. Alembic owns all of it; the panel owns none of
it. The one code change outside the new objects — TG-M2's handling of messages sent on behalf of a
chat (§6) — changes no schema.

The shape of this revision follows from research Finding 3: **an incident stores what was decided when
it was flagged, and nothing about what happened afterwards.** What happened afterwards is evidence,
and the incident's state, moments and timings are functions of that evidence, defined once in SQL.

---

## §1 — `moderation_incidents`

One message that needed a moderator to act. Source plan §10.8, corrected by research Finding 3
(no stored state) and by TG-M3's Finding 2 (the anchor includes the chat).

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | bigserial | no | PK |
| `telegram_chat_id` | bigint | no | FK → `telegram_chats.id` |
| `telegram_message_id` | bigint | no | the offending message's **platform** id, per chat |
| `opened_at` | timestamptz | no | the posting moment = that message's `sent_at` (FR-003). Never the flagging time |
| `detected_at` | timestamptz | no | the flagging moment — the database's `now()` at insert (FR-004) |
| `source` | varchar(20) | no | `operator`. `ai` is reserved for TG-M5 and never written here (FR-005, FR-009) |
| `opened_by_user_id` | bigint | yes | the panel account that flagged it. Required when `source='operator'`. No FK, as TG-M3's `closed_by_user_id` |
| `category` | varchar(30) | no | `SPAM_OR_AD` \| `ABUSE` \| `OTHER` — D-TG-08's spelling (FR-006) |
| `severity` | varchar(10) | no | `low` \| `medium` \| `high` — D-TG-08's scale without `none` (FR-006) |
| `message_classification_id` | bigint | yes | shaped for TG-M5, always NULL here. No FK until `0007` creates the table |
| `responsible_moderator_id` | bigint | yes | FK → `moderators.id`. Snapshotted from `responsible_at(chat, detected_at)`; NULL is a real answer (FR-046, FR-047) |
| `created_at` | timestamptz | no | `server_default now()`. Never used for period selection (FR-064) |

**There is no `status` column and no `acknowledged_*` / `resolved_*` / `closed_*` column.** They are
`moderation_incident_state`'s (§3.2). Labels are written once at insert; no code path updates them.

### Constraints

| Name | Shape | Protects |
|---|---|---|
| `uq_incident_anchor` | `UNIQUE (telegram_chat_id, telegram_message_id)` | FR-002. The chat id is load-bearing — TG-M3's Finding 2 |
| `fk_incident_message` | FK `(telegram_chat_id, telegram_message_id)` → `telegram_messages (telegram_chat_id, message_id)` | an incident can never anchor on a message that was never stored |
| `ck_incident_source` | `source IN ('operator','ai')` | D-TG-102 |
| `ck_incident_opener` | `(source = 'operator') = (opened_by_user_id IS NOT NULL)` | FR-005 |
| `ck_incident_category` | `category IN ('SPAM_OR_AD','ABUSE','OTHER')` | FR-006, D-TG-101 |
| `ck_incident_severity` | `severity IN ('low','medium','high')` | FR-006, D-TG-101 |
| `ck_incident_operator_labels` | `source <> 'operator' OR message_classification_id IS NULL` | operator labels can never be mistaken for a prediction (FR-006) |

A service message cannot be flagged (FR-007). That is enforced by the panel form and by
`open_incident`'s own check, not by a constraint: `is_service` lives on the referenced row, and a
cross-table CHECK is not available.

### Indexes

| Name | Shape | Serves |
|---|---|---|
| `ix_incidents_detected` | `(detected_at)` | period selection (M1) and the list's default ordering |
| `ix_incidents_chat` | `(telegram_chat_id, detected_at DESC)` | per-group figures and filter |
| `ix_incidents_moderator` | `(responsible_moderator_id, detected_at DESC)` | per-moderator figures and filter |

---

## §2 — `moderation_actions` — append-only evidence

One observed act. Source plan §10.9. Rows are **never updated and never deleted** (FR-018, D-TG-113).

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | bigserial | no | PK |
| `telegram_chat_id` | bigint | no | FK → `telegram_chats.id` — where the act happened |
| `action_type` | varchar(30) | no | see the kind table below |
| `action_strength` | varchar(20) | yes | `acknowledgement` \| `enforcement` \| `confirmation`; NULL for a reversal or a false-positive closure |
| `occurred_at` | timestamptz | no | the platform's `date` for a captured act; the database's `now()` for a panel act |
| `actor_telegram_user_id` | bigint | yes | FK → `telegram_users.id`. The reactor, or the performer the platform names |
| `actor_moderator_id` | bigint | yes | FK → `moderators.id`. Set when the actor was a declared moderator **when recorded**; never recomputed (FR-015) |
| `actor_is_anonymous` | boolean | no | default false. The performer was the platform's anonymous-administrator account (D-TG-109) |
| `panel_user_id` | bigint | yes | the panel account, for panel acts. No FK |
| `subject_telegram_user_id` | bigint | yes | FK → `telegram_users.id`. The member a membership change affected |
| `target_message_id` | bigint | yes | the reacted-to message's **platform** id, in `telegram_chat_id` |
| `moderation_incident_id` | bigint | yes | FK → `moderation_incidents.id`. Panel acts only — a captured act is linked by the view, never by a column (§3.1) |
| `source_update_id` | bigint | yes | FK → `telegram_updates.id`. The captured event, for every captured act |
| `detail` | jsonb | no | default `'{}'`. Emoji added; old/new status; `until_date`. **Never message text** |
| `note` | text | yes | the operator's resolve note or false-positive reason |
| `created_at` | timestamptz | no | `server_default now()` |

### Kinds

| `action_type` | `action_strength` | Written by | Evidence |
|---|---|---|---|
| `reaction` | `acknowledgement` | `process_update` | a reaction **added** by a declared moderator (D-TG-110) |
| `ban` | `enforcement` | `process_update` | membership change → `kicked`, by someone else (D-TG-108) |
| `expulsion` | `enforcement` | `process_update` | `member`/`restricted`/`administrator` → `left`, by someone else |
| `restriction` | `enforcement` | `process_update` | → `restricted`, by someone else |
| `reversal` | — | `process_update` | `kicked` → `left`/`member`; restriction lifted. Recorded and inert (FR-014) |
| `panel_acknowledge` | `acknowledgement` | the panel | FR-034 |
| `panel_resolve` | `confirmation` | the panel | FR-035 — note required |
| `panel_false_positive` | — | the panel | FR-036 — reason required. A closure, not a handling |

A moderator's **direct reply** is not a row here (FR-012, D-TG-111); the evidence view reads it from
`telegram_messages` in place. The source plan's `alert_button_handled` arrives with TG-M6 as one more
`confirmation` kind; nothing else changes.

Two narrowings of §10.9, both recorded in the spec's Assumptions: `reversal` (the plan's `unban`)
carries no strength, and `panel_false_positive` (the plan's `dismiss_false_positive`) carries no
strength — so neither can ever stand as an incident's earliest enforcement or confirmation.

### Constraints

| Name | Shape | Protects |
|---|---|---|
| `uq_moderation_actions_source_update` | `UNIQUE (source_update_id)` | FR-019 — one captured event, at most one row, however often it is interpreted. NULLs (panel acts) are distinct |
| `ck_actions_type` | `action_type IN ('reaction','ban','expulsion','restriction','reversal','panel_acknowledge','panel_resolve','panel_false_positive')` | D-TG-103 |
| `ck_actions_strength` | the kind table above, as one boolean expression | a reversal or a closure can never be given a strength |
| `ck_actions_panel_link` | `(action_type LIKE 'panel\_%') = (moderation_incident_id IS NOT NULL)` | panel acts name their incident; captured acts never do |
| `ck_actions_provenance` | panel kinds ⇒ `panel_user_id IS NOT NULL AND source_update_id IS NULL`; other kinds ⇒ `source_update_id IS NOT NULL` | every row says where it came from |
| `ck_actions_note` | `action_type NOT IN ('panel_resolve','panel_false_positive') OR (note IS NOT NULL AND btrim(note) <> '')` | FR-035, FR-036 |
| `ck_actions_membership_subject` | membership kinds ⇒ `subject_telegram_user_id IS NOT NULL` | a ban with no subject cannot link to anything |
| `ck_actions_reaction_shape` | `reaction` ⇒ `target_message_id IS NOT NULL AND actor_moderator_id IS NOT NULL` | only a moderator's reaction is ever recorded |

### Indexes

| Name | Shape | Serves |
|---|---|---|
| `ix_actions_reaction_target` | `(telegram_chat_id, target_message_id) WHERE action_type = 'reaction'` | view branch (a) |
| `ix_actions_subject` | `(subject_telegram_user_id, occurred_at) WHERE subject_telegram_user_id IS NOT NULL` | view branch (c) |
| `ix_actions_incident` | `(moderation_incident_id) WHERE moderation_incident_id IS NOT NULL` | view branch (d) |

Branch (b) — replies — is served by TG-M2's existing `ix_messages_reply (telegram_chat_id,
reply_to_message_id)`.

---

## §3 — The two views

Both are plain (non-materialised) views, created by the migrator, readable by `ai_control` without a
`GRANT` (research probe 6). Both were run exactly as written below against a scripted scenario in
`injaz_ai_test` (research probe 8). Each branch joins the incident directly rather than through a CTE, so a
filter on `incident_id` pushes down into every branch.

### §3.1 `moderation_incident_evidence` — which evidence belongs to which incident

The single definition (D-TG-105). Every branch shares the spine: **platform timestamp strictly after the
posting moment** (FR-025), and **never the offending message's own sender** (FR-016). Branch (c) alone
crosses a promotion, one hop forward (D-TG-107).

```sql
CREATE VIEW moderation_incident_evidence AS
-- (a) a moderator's reaction added to the anchor
SELECT i.id AS incident_id, 1 AS source_rank, a.id AS evidence_id,
       a.action_type AS kind, a.action_strength AS strength, a.occurred_at,
       a.actor_telegram_user_id, a.actor_moderator_id, a.actor_is_anonymous, a.panel_user_id,
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
-- (c) a membership change against the anchor's sender, in the anchor's chat or its successor
SELECT i.id, 1, a.id,
       a.action_type, a.action_strength, a.occurred_at,
       a.actor_telegram_user_id, a.actor_moderator_id, a.actor_is_anonymous, a.panel_user_id,
       a.subject_telegram_user_id, a.source_update_id, a.note, a.detail
FROM moderation_incidents i
JOIN telegram_messages m   ON m.telegram_chat_id = i.telegram_chat_id
                          AND m.message_id       = i.telegram_message_id
JOIN telegram_chats c      ON c.id = i.telegram_chat_id
LEFT JOIN telegram_chats s ON s.chat_id = c.migrated_to_chat_id
JOIN moderation_actions a  ON a.action_type IN ('ban','expulsion','restriction','reversal')
                          AND a.subject_telegram_user_id = m.telegram_user_id
                          AND (a.telegram_chat_id = i.telegram_chat_id OR a.telegram_chat_id = s.id)
WHERE a.occurred_at > i.opened_at

UNION ALL
-- (d) a panel act on this incident
SELECT i.id, 1, a.id,
       a.action_type, a.action_strength, a.occurred_at,
       a.actor_telegram_user_id, a.actor_moderator_id, a.actor_is_anonymous, a.panel_user_id,
       a.subject_telegram_user_id, a.source_update_id, a.note, a.detail
FROM moderation_incidents i
JOIN moderation_actions a  ON a.moderation_incident_id = i.id;
```

Consequences worth stating, because each is a requirement:

- An anchor sent on behalf of a chat has `telegram_user_id IS NULL`, so branch (c)'s equality is never
  true — no membership evidence can link to it (FR-033), and the screen says so (D-TG-127).
- Pre-flagging evidence is included, because the spine compares against `opened_at`, not
  `detected_at` (the first clarification, FR-043).
- A membership change is performed by someone other than its subject by construction (D-TG-108), so
  branch (c) needs no sender-exclusion clause of its own.

### §3.2 `moderation_incident_state` — status, moments and actors, derived

```sql
CREATE VIEW moderation_incident_state AS
SELECT i.id AS incident_id,
       CASE WHEN fp.occurred_at  IS NOT NULL THEN 'closed_false_positive'
            WHEN res.occurred_at IS NOT NULL THEN 'resolved'
            WHEN ack.occurred_at IS NOT NULL THEN 'acknowledged'
            ELSE 'open' END                              AS status,
       ack.occurred_at  AS first_acknowledgement_at, ack.kind AS acknowledgement_kind,
       ack.actor_moderator_id AS acknowledged_by_moderator_id, ack.panel_user_id AS acknowledged_by_user_id,
       enf.occurred_at  AS first_enforcement_at,
       conf.occurred_at AS first_confirmation_at,
       res.occurred_at  AS resolved_at, res.kind AS resolution_kind, res.strength AS resolution_strength,
       res.actor_moderator_id     AS resolved_by_moderator_id,
       res.actor_telegram_user_id AS resolved_by_telegram_user_id,
       res.actor_is_anonymous     AS resolved_by_anonymous,
       res.panel_user_id          AS resolved_by_user_id,
       fp.occurred_at   AS closed_at, fp.panel_user_id AS closed_by_user_id, fp.note AS close_reason
FROM moderation_incidents i
LEFT JOIN LATERAL (SELECT * FROM moderation_incident_evidence e
                   WHERE e.incident_id = i.id AND e.strength = 'acknowledgement'
                   ORDER BY e.occurred_at, e.source_rank, e.evidence_id LIMIT 1) ack  ON true
LEFT JOIN LATERAL (SELECT * FROM moderation_incident_evidence e
                   WHERE e.incident_id = i.id AND e.strength = 'enforcement'
                   ORDER BY e.occurred_at, e.source_rank, e.evidence_id LIMIT 1) enf  ON true
LEFT JOIN LATERAL (SELECT * FROM moderation_incident_evidence e
                   WHERE e.incident_id = i.id AND e.strength = 'confirmation'
                   ORDER BY e.occurred_at, e.source_rank, e.evidence_id LIMIT 1) conf ON true
LEFT JOIN LATERAL (SELECT * FROM moderation_incident_evidence e
                   WHERE e.incident_id = i.id AND e.strength IN ('enforcement','confirmation')
                   ORDER BY e.occurred_at, e.source_rank, e.evidence_id LIMIT 1) res  ON true
LEFT JOIN LATERAL (SELECT * FROM moderation_incident_evidence e
                   WHERE e.incident_id = i.id AND e.kind = 'panel_false_positive'
                   ORDER BY e.occurred_at, e.evidence_id LIMIT 1)             fp   ON true;
```

`(occurred_at, source_rank, evidence_id)` is D-TG-106's tie-break: deterministic on every read, because
`evidence_id` alone collides between the `moderation_actions` and `telegram_messages` branches.

---

## §4 — The state machine, derived

```
                reply | reaction | panel acknowledge          ban | expulsion | restriction | panel resolve
   open ───────────────────────────────────────▶ acknowledged ─────────────────────────────────────▶ resolved
     │                                                  │                                              ▲
     │ ban | expulsion | restriction | panel resolve ───┼──────────────────────────────────────────────┘
     │                                                  │
     └──── panel "not a violation" ─────────────────────┴──────────▶ closed_false_positive
```

Nothing performs a transition. The status is whatever §3.2's precedence says the evidence implies:

1. a false-positive closure exists → **closed_false_positive**;
2. else any enforcement or confirmation exists → **resolved**;
3. else any acknowledgement exists → **acknowledged**;
4. else → **open**.

Why the three guarantees hold without a guarded update on a status row:

| Guarantee | Mechanism |
|---|---|
| Resolved is terminal (FR-041) | Evidence is never deleted (D-TG-113), so once a resolving row exists it always exists. A false-positive closure cannot be inserted over it: the panel guard reads *resolved* and inserts nothing (D-TG-115) |
| Closed is terminal (FR-041) | Rule 1 takes precedence over every later row of any kind |
| No resolution from acknowledgement (FR-023) | Rule 2 names only `enforcement` and `confirmation`; no acknowledgement kind carries either strength — enforced by `ck_actions_strength` |
| Order-independent (FR-045) | The status and every moment are aggregates over a set; a set has no processing order |
| No change on deletion, absence or time (FR-042) | No rule reads a clock, a missing row, or a deletion — there is no such row to read |

Probe 8 made the dependency explicit: a closure row inserted over a resolved incident *without* the
guard does change the status, because rule 1 takes precedence. **The guard is load-bearing**, which is
why it lives on the model (D-TG-115) rather than in a Filament action. The one serialisation needed is between inserting a false-positive closure and inserting enforcement —
D-TG-114's advisory lock. A human act is judged against the state visible when it is made; if a ban
dated earlier is captured *after* a closure was committed, the closure stands (rule 1) and the ban is
listed in the trail.

### How each status counts (the figures, `contracts/incident-metrics.md`)

| | Outcome counts | Timings | Detection latency |
|---|---|---|---|
| open / acknowledged | handled, missed or within window, by the resolution moment and the ceiling | each from its own earliest evidence, if any | yes |
| resolved | handled if resolved within the ceiling, otherwise missed (the third clarification) | yes | yes |
| closed_false_positive | **none** — counted only in its own figure | **none** | yes (D-TG-121) |

---

## §5 — Retention

Neither table stores message text. `moderation_incidents` holds identifiers, moments, labels and
attribution; `moderation_actions.detail` holds emoji and member statuses. `note` holds the **operator's**
words, not a student's. When TG-M10's purge nulls `telegram_messages.original_text`, an incident keeps
every moment, every piece of evidence and every figure, and loses only the words shown under "what was
posted" (FR-076). Performer and subject names live in `telegram_users` and follow its existing rules —
non-moderator names nulled at retention, moderators' kept.

---

## §6 — Changes outside the new objects

| Where | Change | Why |
|---|---|---|
| `app/application/moderation/messages.py` `derive_message` | when `sender_chat` is present, ignore `from`: no identity upsert, `telegram_user_id` NULL, `is_from_moderator` false | Finding 1, D-TG-99. **No schema change**; `ck_telegram_messages_sender` is untouched and is exactly what makes the fix necessary |
| `app/application/moderation/assignments.py` `repoint_for_migration` | docstring only: incidents, like items, are not re-pointed; the evidence view follows the lineage | D-TG-107 |
| `app/workers/tasks/moderation/process_update.py` | dispatch `chat_member` and `message_reaction` to evidence derivation | D-TG-112 |
| `infra/docker-compose.yml`, `config/moderation.php` | `${KEY:-default}` for both moderation keys; blank-safe reads | Finding 2, D-TG-122 |

---

## §7 — What revision `0006` deliberately does not do

- **No `GRANT`.** The default ACL for `ai_migrator` covers tables and views alike (probe 6).
- **No alter of any existing table**, and in particular no incident pointer on `telegram_messages` and
  no change to any TG-M2 or TG-M3 column.
- **No `status` column, no trigger, no materialised view.** Finding 3; source plan §31's rule against
  materialising before a query is measured to be slow.
- **No FK to `message_classifications`** — `0007` creates that table.
- **No enum types** — D-TG-103.
- **No data backfill.** There is none to do: probe 1 found no captured membership or reaction event, and
  ordinary derivation starts from this revision (FR-083).
