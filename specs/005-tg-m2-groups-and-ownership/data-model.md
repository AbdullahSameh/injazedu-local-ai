# Data Model: TG-M2 — Groups, Users, Messages and Moderator Ownership

**Revision**: `0004_moderation_actors`, down-revision `0003` (probe 10: `0003` is head)
**Tables added**: 4 · **Tables altered**: 0 · **Grants added**: 0 (probe 9)
**Source**: `docs/plan/telegram/telegram-moderation-intelligence.md` §10.4, §10.5, §10.6, §19.2

---

## §0 — Conventions, inherited unchanged

From `0002_model_gateway` and `0003_moderation_ingest`: SQLAlchemy Core `Table` objects appended to
`app/infrastructure/models_moderation.py` on the **same** `metadata` as `models.py`; `BIGINT` identity
primary keys, never UUIDs; every timestamp `TIMESTAMPTZ`; `server_default=sa.func.now()` where a value
is always present; constraint names spelled explicitly (`uq_`, `ck_`, `ix_`); hand-written migration,
`target_metadata = None`, autogenerate not wired; invariants expressed as database objects rather than
application conventions.

**No `ALTER TABLE` in this revision (D-TG-46).** Everything the screens need on `telegram_chats` —
`is_monitored`, `injaz_course_id`, `bot_status`, `bot_can_delete`, `last_event_at`,
`migrated_to_chat_id`, `migrated_from_chat_id` — already exists from `0003`. This milestone is their
first consumer. `telegram_messages.attention_item_id` belongs to `0005` and is deliberately absent.

**No `GRANT`.** `infra/postgres/initdb/01-roles.sql:20` sets `ALTER DEFAULT PRIVILEGES FOR ROLE
ai_migrator`, and `02-test-database.sql` mirrors it into `injaz_ai_test`, so DML on anything the
migrator creates reaches `ai_app` and `ai_control` automatically. TG-M1 shipped no screens, so this is
the first milestone where the panel's access to new tables matters at all — probe 9 confirmed it before
any code was written.

---

## §1 — `telegram_users` — sender identities

**Purpose.** One row per distinct person the bot has observed, plus placeholder rows created by mapping
someone who has not been observed yet. The numeric identifier is a durable pseudonym; the names beside
it are personal data.

| Column | Type | Notes |
|---|---|---|
| `id` | BIGINT PK | |
| `tg_user_id` | BIGINT NOT NULL | the platform's own numeric identifier — the durable pseudonym (FR-016) |
| `username` | VARCHAR(100) NULL | personal data; removable |
| `display_name` | VARCHAR(300) NULL | personal data; removable |
| `is_bot` | BOOLEAN NOT NULL DEFAULT false | never a moderator, whatever the mapping says (FR-017) |
| `first_seen_at` | TIMESTAMPTZ **NULL** | **NULL means placeholder** — mapped but never observed (D-TG-52) |
| `last_seen_at` | TIMESTAMPTZ NULL | |
| `identity_purged_at` | TIMESTAMPTZ NULL | set by TG-M10's job; nothing writes it here (FR-058) |
| `created_at`, `updated_at` | TIMESTAMPTZ NOT NULL | `server_default=now()` |

**Constraints.** `uq_telegram_users_tg_user_id UNIQUE (tg_user_id)` — FR-014, and the arbiter for every
upsert below.

`first_seen_at` is deliberately nullable, which `telegram_chats` did not need. It is how a placeholder
is *distinguishable* from an observed person without a second flag column, and it is what
`COALESCE`/`LEAST` keys off in §1.1.

**The one upsert statement (D-TG-51, Finding 4).** Replay-safe in all three directions:

```sql
INSERT INTO telegram_users (tg_user_id, username, display_name, is_bot, first_seen_at, last_seen_at)
VALUES (:id, :username, :display_name, :is_bot, :observed_at, :observed_at)
ON CONFLICT (tg_user_id) DO UPDATE SET
  first_seen_at = LEAST (COALESCE(telegram_users.first_seen_at, EXCLUDED.first_seen_at),
                         EXCLUDED.first_seen_at),
  last_seen_at  = GREATEST(COALESCE(telegram_users.last_seen_at,  EXCLUDED.last_seen_at),
                           EXCLUDED.last_seen_at),
  username     = CASE WHEN EXCLUDED.last_seen_at
                         >= COALESCE(telegram_users.last_seen_at, EXCLUDED.last_seen_at)
                      THEN EXCLUDED.username     ELSE telegram_users.username     END,
  display_name = CASE WHEN EXCLUDED.last_seen_at
                         >= COALESCE(telegram_users.last_seen_at, EXCLUDED.last_seen_at)
                      THEN EXCLUDED.display_name ELSE telegram_users.display_name END,
  is_bot = EXCLUDED.is_bot,
  updated_at = now();
```

Three requirements, one statement, verified by probe 5:

- **FR-015** — `first_seen_at` never moves *forward*; `LEAST` also lets a genuinely older replayed
  observation move it *back*, which is correct.
- **FR-028** — a placeholder's NULL `first_seen_at` is filled by the first real observation, and no
  second identity row is created.
- **Finding 4** — the guarded name write stops a re-derivation of August events replacing a September
  display name, and `GREATEST` stops `last_seen_at` moving backwards (which a coverage read would
  otherwise report as a group having gone quiet).

**Placeholder creation (D-TG-52).** `INSERT INTO telegram_users (tg_user_id, is_bot) VALUES (:id,
false) ON CONFLICT (tg_user_id) DO NOTHING` — names NULL, `first_seen_at` NULL. Probe 5, step C1.

**Indexes.** None beyond the unique constraint. The screens reach identities through `moderators`, and
`0004` deliberately adds no index for TG-M10's purge scan — that index belongs to the revision that
ships the job.

**Retention shape (FR-055, FR-056).** `username` and `display_name` are removable and
`identity_purged_at` records it; `tg_user_id`, `first_seen_at`, `last_seen_at` and every join survive.
Identities reachable from `moderators` are excluded from removal — expressible as
`WHERE NOT EXISTS (SELECT 1 FROM moderators m WHERE m.telegram_user_id = telegram_users.id)`, which the
foreign key makes exact. Nothing in this milestone removes anything.

---

## §2 — `telegram_messages` — the derived fact

**Purpose.** One row per message in a **measured** group. Every later milestone reads this table rather
than `telegram_updates`, and every metric is arithmetic over `sent_at`, `is_from_moderator` and the
reply linkage.

| Column | Type | Notes |
|---|---|---|
| `id` | BIGINT PK | |
| `telegram_chat_id` | BIGINT NOT NULL FK → `telegram_chats.id` | the surrogate key, not the platform's `chat_id` |
| `message_id` | BIGINT NOT NULL | the platform's own, unique only within a chat |
| `telegram_user_id` | BIGINT NULL FK → `telegram_users.id` | NULL for an anonymous or channel sender |
| `sender_chat_id` | BIGINT NULL | the platform's numeric id of a group/channel sender (FR-005) |
| `sent_at` | TIMESTAMPTZ NOT NULL | **the platform's `date`** — never `received_at` (FR-003) |
| `edited_at` | TIMESTAMPTZ NULL | set by the edit path only (FR-010) |
| `reply_to_message_id` | BIGINT NULL | the platform's identifier, **deliberately not a FK** (FR-004) |
| `message_thread_id` | BIGINT NULL | recorded as a fact; scopes nothing until TG-M3 |
| `is_service` | BOOLEAN NOT NULL DEFAULT false | FR-006 |
| `is_from_moderator` | BOOLEAN NOT NULL DEFAULT false | **written once, at insert, never recomputed** (FR-032, FR-033) |
| `original_text` | TEXT NULL | verbatim; never normalised in place (FR-008) |
| `normalized_text` | TEXT NULL | `normalize()` from TG-M0 (D-TG-63) |
| `text_purged_at` | TIMESTAMPTZ NULL | TG-M10 writes it; nothing here does |
| `media_kind` | VARCHAR(20) NULL | coarse; **no CHECK** — see below |
| `entity_flags` | JSONB NOT NULL DEFAULT `'{}'` | `has_url`, `has_phone`, `has_mention`, `forwarded` (FR-007) |
| `source_update_id` | BIGINT NOT NULL FK → `telegram_updates.id` | the captured event this row came from |
| `created_at` | TIMESTAMPTZ NOT NULL | when derivation ran — never used as a message time |

**Constraints.**

- `uq_telegram_messages_chat_msg UNIQUE (telegram_chat_id, message_id)` — FR-002. This *is* the
  idempotency mechanism and, through D-TG-49, also the mechanism that makes FR-033 hold.
- `ck_telegram_messages_sender` — `NOT (telegram_user_id IS NOT NULL AND sender_chat_id IS NOT NULL)`.
  At most one sender form. Deliberately permits **neither**, so an unmodelled sender shape is stored
  rather than rejected.
- `ck_telegram_messages_moderator_needs_user` — `is_from_moderator = false OR telegram_user_id IS NOT
  NULL`. D-TG-60 in the database: an anonymous administrator, a channel post or a senderless message can
  never be flagged as a moderator's, because the platform withholds who acted and the flattering guess
  is the one this domain must not make.
- `ck_telegram_messages_edit_order` — `edited_at IS NULL OR edited_at >= sent_at`. An edit cannot
  precede the message.

**No CHECK on `media_kind`**, unlike `telegram_updates.update_type` and `telegram_chats.bot_status`.
Those enumerate things the domain controls; media kinds are the platform's and it adds them. A CHECK
here would make "an event containing content this domain does not model" — an edge case the spec
requires to be *stored regardless* — into an insert failure that loses a message. Unrecognised kinds map
to `'other'`.

**Indexes** (§10.6, each with a named consumer):

| Index | Consumer |
|---|---|
| `ix_messages_chat_sent (telegram_chat_id, sent_at DESC)` | the chat transcript, and every windowed metric from TG-M3 |
| `ix_messages_chat_moderator_sent (telegram_chat_id, is_from_moderator, sent_at)` | the response scan of §13.2 — the source plan calls this "the index the response scan lives on" |
| `ix_messages_reply (telegram_chat_id, reply_to_message_id)` | direct-reply correlation, TG-M3 |

No index on `source_update_id`: re-derivation walks `telegram_updates` and inserts, never scans
messages by their source. Adding one now would be an index for a query nothing makes.

**Write modes — two, and never confused (D-TG-49, D-TG-50).**

```sql
-- (a) derivation, live or re-derived: INSERT-ONLY, never DO UPDATE
INSERT INTO telegram_messages (…) VALUES (…)
ON CONFLICT (telegram_chat_id, message_id) DO NOTHING
RETURNING id;                          -- 0 rows ⇒ already derived; leave it entirely alone

-- (b) an edit: a targeted UPDATE of text and edit time, and nothing else
UPDATE telegram_messages
   SET original_text = :text, normalized_text = :normalized, edited_at = :edit_date, 
 WHERE telegram_chat_id = :chat AND message_id = :message_id;
```

Probes 6 and 7 confirm the consequence: `sent_at` and `is_from_moderator` are written exactly once,
at insert, and survive every replay and every edit. Making derivation an upsert would silently rewrite
the moderator flag on historical messages each time a re-derivation ran — the precise retroactive
rewrite this milestone exists to prevent.

**Retention shape (FR-057).** `original_text` and `normalized_text` are removable with
`text_purged_at` recording it; `telegram_chat_id`, `telegram_user_id`, `sent_at`, `edited_at`,
`reply_to_message_id`, `is_from_moderator`, `entity_flags` and every timing survive. So does
`media_kind`, which carries no content.

---

## §3 — `moderators` — declared people

**Purpose.** A moderator is someone the operator named. It is this domain's fact, informed by the
platform's administrator lists but never granted by them (FR-031).

| Column | Type | Notes |
|---|---|---|
| `id` | BIGINT PK | |
| `telegram_user_id` | BIGINT NOT NULL FK → `telegram_users.id` **ON DELETE RESTRICT** | |
| `display_name` | VARCHAR(200) NOT NULL | operator-set and stable; a platform rename cannot touch it (FR-029) |
| `injaz_user_id` | BIGINT NULL | free reference; **no FK** — that database is on another host (Principle III) |
| `is_active` | BOOLEAN NOT NULL DEFAULT true | availability for *new* assignments only (FR-030) |
| `notes` | TEXT NULL | |
| `created_at`, `updated_at` | TIMESTAMPTZ NOT NULL | |

**Constraints.**

- `uq_moderators_telegram_user_id UNIQUE (telegram_user_id)` — this single object gives **both**
  directions of FR-026: the uniqueness stops one identity mapping to two moderators, and the column
  being single-valued and `NOT NULL` stops one moderator mapping to two identities.
- `ON DELETE RESTRICT` on the identity — a moderator's identity row must not be able to vanish beneath
  them, which is also what keeps FR-056's name-retention join exact.

`is_active = false` changes nothing else. The record, the assignment history and every
`is_from_moderator` already written stay exactly as they are (FR-030, SC-011) — deactivation is not a
retraction of history.

**Indexes.** None beyond the unique constraint: five rows are expected, a few dozen at most.

---

## §4 — `moderator_group_assignments` — ownership as history

**Purpose.** The milestone's core. Who owned which group, over which interval. The one piece of this
design that cannot be added later, because a current-owner column, once overwritten, has destroyed the
previous owner.

| Column | Type | Notes |
|---|---|---|
| `id` | BIGINT PK | |
| `telegram_chat_id` | BIGINT NOT NULL FK → `telegram_chats.id` | re-pointed on a chat migration (D-TG-54) |
| `moderator_id` | BIGINT NOT NULL FK → `moderators.id` | |
| `assignment_role` | VARCHAR(20) NOT NULL | `primary` \| `backup` |
| `valid_from` | TIMESTAMPTZ NOT NULL | **inclusive** |
| `valid_to` | TIMESTAMPTZ NULL | **exclusive**; NULL = current |
| `note` | TEXT NULL | e.g. "covering while Ahmed is on leave" |
| `created_at` | TIMESTAMPTZ NOT NULL | |

**Constraints.**

- **`uq_assignment_one_current_primary UNIQUE (telegram_chat_id) WHERE assignment_role = 'primary' AND
  valid_to IS NULL`** — FR-036, the same partial-index idiom as
  `uq_model_profiles_one_active_per_role` (`0002_model_gateway.py:65`). Probe 2 established that it
  **cannot be deferred**, which is what forces the statement order in §4.1.
- `ck_assignment_role` — `assignment_role IN ('primary', 'backup')`.
- `ck_assignment_interval` — `valid_to IS NULL OR valid_to > valid_from`. Strictly greater, not `>=`,
  so a zero-width interval is impossible. A zero-width interval covers no instant, so
  `responsible_at` could never return it: it would be an ownership record that exists and is invisible.
  **Consequence, accepted:** assigning and then reassigning at the same instant is refused. That is the
  honest outcome — the intermediate owner owned nothing.

**Indexes.**

| Index | Consumer |
|---|---|
| `uq_assignment_one_current_primary` (above) | the invariant, and the current-owner lookup |
| `ix_assignment_chat_from (telegram_chat_id, valid_from DESC)` | `responsible_at`, and the per-group history view |
| `ix_assignment_moderator (moderator_id, valid_from DESC)` | the assignments relation manager on a moderator |

### §4.1 The handover, exactly (D-TG-47, Finding 2)

One transaction, one timestamp, close before open:

```sql
BEGIN;
  UPDATE moderator_group_assignments
     SET valid_to = :at
   WHERE telegram_chat_id = :chat AND assignment_role = 'primary' AND valid_to IS NULL;

  INSERT INTO moderator_group_assignments
         (telegram_chat_id, moderator_id, assignment_role, valid_from, note)
  VALUES (:chat, :new_moderator, 'primary', :at, :note);
COMMIT;
```

Each clause is forced by a measurement, not a preference:

| Clause | Forced by |
|---|---|
| Close **before** open | Probe 2 — the partial index cannot be deferred, so opening first violates it immediately |
| **One** transaction | The existing `ModelProfile::save()` pattern; a partial failure must leave the incumbent current |
| **One** `:at` for both | Finding 2 — two clock readings leave a hole with **zero** owners that no constraint detects |

`:at` is SQL `now()` (which is `transaction_timestamp()`, identical across both statements) or a single
value computed once and bound twice. Two PHP `now()` calls are **not** equivalent and are the bug.

`responsible_at` at the handover instant returns the **successor**, because `valid_from` is inclusive
and `valid_to` exclusive — probe 3 measured exactly one owner there.

### §4.2 `responsible_at(chat, t)` (D-TG-48)

```sql
SELECT moderator_id FROM moderator_group_assignments
 WHERE telegram_chat_id = :chat
   AND assignment_role  = 'primary'
   AND valid_from <= :t
   AND (valid_to IS NULL OR valid_to > :t);
```

Returns at most one row. Returns **nothing** when no interval covers `:t`, and the current owner is
never substituted (FR-042). Backups are excluded by the role predicate (FR-040). Tested at the four
boundary positions — before `valid_from`, at `valid_from`, at `valid_to`, after `valid_to` — rather than
near them (SC-014).

### §4.3 The chat-migration re-point (D-TG-54, Findings 3)

One transaction, and it **refuses** rather than guesses:

```sql
BEGIN;
  -- refuse if the surviving row already has a current primary (probe 8 shows the raw failure)
  -- move ownership: a technical migration is NOT a handover, so no interval is closed or opened
  UPDATE moderator_group_assignments SET telegram_chat_id = :new WHERE telegram_chat_id = :old;
  -- carry the deliberate decisions forward — Finding 3
  UPDATE telegram_chats SET is_monitored = :old_is_monitored, injaz_course_id = :old_course
   WHERE id = :new;
  UPDATE telegram_chats SET is_monitored = false WHERE id = :old;
COMMIT;
```

No `valid_to` is set and no row is inserted: the same person owned the same group before and after, and
recording a handover would invent an ownership change that never happened (FR-052, SC-019).

Carrying `is_monitored` forward is Finding 3's fix — without it a group silently stops being measured at
the moment it is promoted, while every health signal stays green. Clearing it on the superseded row
stops one logical group being measured under two identities at once.

Messages are **not** re-pointed (D-TG-55): that would mutate immutable derived rows, and
`uq_telegram_messages_chat_msg` makes it unsafe besides, since the platform's message numbering either
side of a promotion can collide. "One group's continuous history" (FR-053) is a read that follows
`migrated_from_chat_id` / `migrated_to_chat_id`, which `0003` already stores.

---

## §5 — Relationships

```
telegram_updates ──source_update_id──▶ telegram_messages
      (0003, append-only)                     │
                                              ├──telegram_chat_id──▶ telegram_chats  (0003)
                                              │                            ▲
                                              └──telegram_user_id──▶ telegram_users  │
                                                                           │         │
                                                     moderators ──telegram_user_id───┘ (UNIQUE)
                                                          │                          │
                                    moderator_group_assignments ──telegram_chat_id───┘
                                                (valid_from, valid_to]
```

`reply_to_message_id` has no arrow: it is the platform's own identifier and deliberately not a foreign
key, because the replied-to message may predate measurement or predate the bot joining (FR-004).
`injaz_course_id` and `injaz_user_id` have no arrows for the same reason in a different direction — the
system they name is on another host and is read-only (Principle III).

---

## §6 — Migration `0004_moderation_actors`

`upgrade()` creates, in dependency order: `telegram_users`, `moderators`, `telegram_messages`,
`moderator_group_assignments`; then the three non-unique indexes and the partial unique index, using
`op.create_index(..., unique=True, postgresql_where=sa.text(...))` exactly as
`0002_model_gateway.py:65` does.

`downgrade()` drops in reverse: the partial index, then `moderator_group_assignments`,
`telegram_messages`, `moderators`, `telegram_users`. It is exercised by a test, not merely written
(FR-068, SC-030) — Principle I names migrations explicitly.

No data migration. No backfill: the four tables start empty, and filling them from already-captured
events is the operator's deliberate re-derivation command (D-TG-53), not a migration side effect.

---

## §7 — Requirement coverage

| Requirement | Where |
|---|---|
| FR-001…FR-004, FR-007…FR-009 | §2 columns, §2 write mode (a) |
| FR-005, FR-006, FR-017 | §2 `ck_telegram_messages_sender`, `is_service`, `ck_..._moderator_needs_user` |
| FR-010 | §2 write mode (b), `ck_telegram_messages_edit_order` |
| FR-002, FR-032, FR-033 | §2 `uq_telegram_messages_chat_msg` + insert-only |
| FR-014…FR-016, FR-027, FR-028 | §1 and its single upsert statement |
| FR-025, FR-026, FR-029, FR-030 | §3 |
| FR-034 | §2 `is_from_moderator` independent of any assignment |
| FR-035…FR-040 | §4 columns, `uq_assignment_one_current_primary`, §4.1 |
| FR-041…FR-044 | §4.2 |
| FR-052, FR-053 | §4.3, D-TG-55 |
| FR-055…FR-058 | §1 and §2 retention shape; nothing removed here |
| FR-068, FR-069 | §6, and the four database-enforced invariants |
