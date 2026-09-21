# Phase 0 Research: TG-M2 — Groups, Users, Messages and Moderator Ownership

**Feature**: `specs/005-tg-m2-groups-and-ownership`
**Date**: 2026-09-12
**Inputs**: `spec.md` (FR-001…FR-070, SC-001…SC-035, 3 clarifications) ·
`docs/plan/telegram/telegram-moderation-intelligence.md` (§9, §10.3–10.6, §12, §13.4, §15.4, §17,
§19.2, §20.2, §22, §23, §24, §25 TG-M2) · `docs/runbooks/tg-operator-prerequisites.md` (§C TG-M2) ·
`.specify/memory/constitution.md` · the merged TG-M0 and TG-M1 code

Decision ids continue the domain's log at **D-TG-46** (TG-M1 ended at D-TG-45).

---

## §0 — Four findings

Each was produced by a probe against the live stack or the installed framework, and each would have
shipped as a **silent** failure: no exception, no failing test, a screen that looks correct.

### ⚠ Finding 1 — Per-navigation-group text direction is not something the panel can do. FR-051 cannot be implemented as written.

The source plan's §17 says: *"v1 sets `direction: rtl` and Arabic labels for this navigation group
only."* FR-051 carries that forward: the new group's reading direction must suit the operator's
language **and must not alter the rest of the panel**.

Probe 1 read the installed framework. Direction is a single attribute on the document root:

```
vendor/filament/filament/resources/views/components/layout/base.blade.php:16
    dir="{{ __('filament-panels::layout.direction') ?? 'ltr' }}"

vendor/filament/filament/resources/lang/en/layout.php:5   'direction' => 'ltr'
vendor/filament/filament/resources/lang/ar/layout.php:5    'direction' => 'rtl'
```

It resolves from **one translation key**, driven by the application locale, and is written once onto
`<html>`. There is no per-resource, per-page or per-navigation-group direction anywhere in Filament
v5.7.8. The two halves of FR-051 are in direct conflict under this framework: switching the locale to
`ar` turns the whole panel RTL *and* translates all of its chrome — including the model-roster screen —
which is precisely what FR-051's second half forbids.

**Resolution (D-TG-56).** Leave the panel locale and `dir` alone, and set direction **per field of
Arabic content** — `dir="auto"` on the text columns and inputs that carry group titles, moderator
names and, later, message text. `auto` rather than `rtl` is deliberate: the plan's own §17 example
lists *"الرخصة المهنية"* beside *"STEP"*, so the column genuinely mixes scripts, and `auto` lets the
browser pick per value from the first strong character. Labels are Arabic string literals on the two
resources, which needs no locale at all. This satisfies what FR-051 was actually protecting — Arabic
titles that read correctly, with trailing punctuation in the right place — while satisfying the half
that the literal reading breaks. **This narrows an approved requirement's mechanism; escalated to the
operator in `plan.md`.**

### ⚠ Finding 2 — Two timestamps in one reassignment open a silent hole in ownership history.

The reassign action closes the incumbent interval and opens the successor's. Probe 3 measured what
happens when the two timestamps are not the same value:

```
-- one transaction timestamp for both sides (now() == transaction_timestamp())
UPDATE asg SET valid_to = now() WHERE chat_id=1 AND role='primary' AND valid_to IS NULL;
INSERT INTO asg (...) VALUES (1, 11, 'primary', now());
  →  mod 10: 2026-09-01 … 16:52:51.321338
     mod 11: 16:52:51.321338 … (open)
     owners at the handover instant: 1          ✓

-- two clock readings, as two separate PHP now() calls produce
… valid_to = clock_timestamp() … then … valid_from = clock_timestamp() …
     owners in the 10 ms gap: 0                 ✗
```

Nothing objects. No constraint is violated, the screen shows a clean handover, and the history looks
right to a human reading it. But `responsible_at(chat, t)` returns **nothing** for any instant inside
the hole, which a later milestone renders as *"Unassigned"* — a coverage problem that never existed,
manufactured by the handover itself.

This is a PHP-side hazard, not a Python one: **the panel is the writer**, and Laravel's `now()` is
evaluated in PHP per call, returning a fresh microsecond value each time. The natural Filament code —
`$incumbent->update(['valid_to' => now()]); Assignment::create(['valid_from' => now()]);` — has the
bug.

**Resolution (D-TG-47).** One timestamp value, computed once, used on both sides of every handover,
inside one transaction. Enforced in the Eloquent model rather than only in the Filament action
(D-TG-58), so it holds from `tinker` too, and asserted by a test that counts owners **at the exact
handover instant** rather than near it.

### ⚠ Finding 3 — TG-M1's supergroup migration leaves the new chat row unmeasured, so a group silently stops being measured when it is promoted.

TG-M1's `apply_chat_migration_if_any` links the old and new chat rows in both directions. Read
closely (`app/application/moderation/ingest.py:645`), it writes **only** the two linking columns:

```python
new_stmt = pg_insert(telegram_chats).values(
    chat_id=new_chat_id, chat_type="unknown", migrated_from_chat_id=old_chat_id
)
```

So the new row is created at the table's defaults — `is_monitored` **false**. Probe 4 confirmed it:

```
 chat_id | is_monitored | injaz_course_id
    -100 | t            |              77     ← old row, deliberately measured
    -200 | f            |                     ← new row, created by TG-M1's migration handler
```

From the promotion onward, events arrive under the new identifier, are captured, and produce **no
messages** — because FR-019 correctly refuses to derive for an unmeasured group. Capture stays green,
the health block stays green, and measurement of that group has stopped. This is the same silent class
as a lost administrator right, which the source plan's §27 calls the single most likely way the system
quietly stops working, except that here the system does it to itself.

TG-M1 could not have caught this: it derives nothing, so an unmeasured flag had no consequence. It
acquires one here.

**Resolution (D-TG-54).** The migration re-point is a single transaction that moves the ownership
assignments to the surviving row **and carries `is_monitored` and `injaz_course_id` forward**, then
clears `is_monitored` on the superseded row so one logical group is never measured under two
identities at once. Probe 4 ran the whole sequence and it holds.

### ⚠ Finding 4 — A re-derivation of older events would overwrite a sender's current display name with a stale one.

FR-020's re-derivation replays captured events that may be weeks old. The obvious identity upsert
takes the incoming observation as truth:

```sql
ON CONFLICT (tg_user_id) DO UPDATE SET
  username = EXCLUDED.username, display_name = EXCLUDED.display_name, …
```

Probe 5 replayed an August observation after a September one and the September name was replaced by
the August name. No error, no test failure — the row is simply wrong, and stays wrong until that
person posts again. Worse, `last_seen_at` moved **backwards**, which a coverage report reads as a group
having gone quiet.

Like Finding 3, this is a hazard TG-M1 could not have had: it never replayed anything.

**Resolution (D-TG-51).** `first_seen_at = LEAST(…)`, `last_seen_at = GREATEST(…)` so neither
timestamp can be dragged the wrong way by an out-of-order replay, and the name fields are written only
when the incoming observation is **not older** than the stored `last_seen_at`. Probe 5 confirms one
statement then satisfies FR-015 (first-observed never moves), FR-028 (a placeholder fills in) and
replay-safety together.

---

## §1 — Probes

Ten probes. Postgres 16.15 in `injazedu-local-ai-postgres-1`, every schema probe inside
`BEGIN … ROLLBACK` against `injaz_ai_test` — no development data touched, no schema left behind
(Principle II).

| # | Question | Result |
|---|---|---|
| 1 | Can the panel set text direction per navigation group? | **No.** One `dir` on `<html>` from `filament-panels::layout.direction`, locale-driven, panel-wide → **Finding 1** |
| 2 | Can the current-primary partial unique index be deferred, so a reassignment could insert before closing? | **No.** `CREATE UNIQUE INDEX … WHERE … DEFERRABLE` → `ERROR: syntax error at or near "DEFERRABLE"`. A partial unique index cannot be a constraint, and only constraints can be deferred. **Statement order is therefore mandatory: close, then open** |
| 3 | Does a reassignment leave exactly one owner at the handover instant? | With one transaction timestamp, **yes** (1 owner). With two clock readings, **0 owners in the gap** → **Finding 2** |
| 4 | What does TG-M1's supergroup migration do to the opt-in flag? | New row created at defaults, `is_monitored = false` → **Finding 3**. The carry-forward + re-point sequence was run and holds |
| 5 | Does the obvious identity upsert survive an out-of-order replay? | **No** — stale name overwrites current, `last_seen_at` moves backwards → **Finding 4**. `LEAST`/`GREATEST` + a guarded name write fixes all three requirements in one statement |
| 6 | Does `ON CONFLICT … DO NOTHING RETURNING` let a re-derive avoid rewriting an existing message? | **Yes.** Returns 0 rows for the already-present message; `is_from_moderator` and the text are untouched. Insert-only derivation and FR-033 are the same mechanism |
| 7 | Does the edit path stay separable from the insert path? | **Yes.** A targeted `UPDATE … SET original_text, normalized_text, edited_at WHERE (chat, message_id)` leaves `sent_at` and `is_from_moderator` intact — FR-010 and FR-033 do not fight |
| 8 | What happens when a re-point's destination row already has a current primary? | `ERROR: duplicate key value violates unique constraint "uq_cur"`. Needs a defined resolution rather than a crashed job (D-TG-54) |
| 9 | Will the panel's role be able to read and write the four new tables? | **Yes, automatically.** `infra/postgres/initdb/01-roles.sql:20` sets `ALTER DEFAULT PRIVILEGES FOR ROLE ai_migrator` granting DML to `ai_app, ai_control`, and `02-test-database.sql` mirrors it into `injaz_ai_test`. **No follow-up `GRANT` in the migration** — and this is the first milestone where it matters, since TG-M1 shipped no screens |
| 10 | Is `0004` free, and what is the partial-index precedent? | `alembic current` → `0003 (head)`. `0002_model_gateway.py:65` establishes the exact idiom: `op.create_index(name, table, cols, unique=True, postgresql_where=sa.text(...))` |

**Not probed, deliberately**: Filament's own table rendering and form validation, Eloquent attribute
casting, Dramatiq delivery, and `httpx` behaviour. All are framework behaviour, exempt under
Principle I.

---

## §2 — Decisions

### Schema and migration

**D-TG-46 — Revision `0004_moderation_actors` creates four tables and alters nothing.**
`telegram_users`, `telegram_messages`, `moderators`, `moderator_group_assignments`. The columns
TG-M2's screens need on `telegram_chats` — `is_monitored`, `injaz_course_id`, `bot_status`,
`bot_can_delete`, `last_event_at`, the two migration links — all already exist from `0003`, so this
revision contains **no `ALTER TABLE`**. `telegram_messages.attention_item_id` belongs to `0005` and is
not added here. Down-revision `0003`; probe 10 confirms it is head. *Alternative rejected:* adding the
attention link now "since we are here" — it would make `0005` a no-op and put a forward reference to an
unapproved milestone in this one's schema.

**D-TG-69 — Every invariant in FR-069 is a database object, and the migration's `downgrade()` drops
them in dependency order.** Four: `uq_telegram_messages_chat_msg`, `uq_telegram_users_tg_user_id`,
`uq_moderators_telegram_user_id`, and `uq_assignment_one_current_primary` (partial). Probe 10's idiom
is used verbatim for the partial one. Each gets a test that attempts the violation directly, not
through the application (SC-031).

### Ownership — the milestone's core

**D-TG-47 — A handover is: close the incumbent, then open the successor, in one transaction, with one
timestamp used on both sides.** All three clauses are load-bearing and each comes from a probe.
*Order* is forced by probe 2 — the partial unique index cannot be deferred, so opening first is an
immediate violation. *One transaction* is the existing `ModelProfile::save()` pattern. *One timestamp*
is Finding 2: two readings leave a hole that nothing detects. SQL `now()` is
`transaction_timestamp()` and is therefore identical across both statements; a single PHP value passed
to both is equivalent. *Alternative rejected:* a `tstzrange` `EXCLUDE` constraint forbidding all
historical overlap — the source plan §10.5 already rejected it (needs `btree_gist` enabled at initdb
on a shipped database), and it would not have caught Finding 2 anyway, since a *gap* is not an overlap.

**D-TG-48 — `responsible_at(chat, t)` is one half-open predicate, defined once.**
`assignment_role = 'primary' AND valid_from <= t AND (valid_to IS NULL OR valid_to > t)` — start
inclusive, expiry exclusive (FR-044). It lives in `app/application/moderation/assignments.py` as the
single Python definition and is mirrored once in the Eloquent scope the panel uses; both are tested at
the four boundary positions (SC-014). It returns `None` rather than the current owner when nothing
covers `t` (FR-042). *Alternative rejected:* a database view. It would need re-creating in a later
revision the moment a metric query wants a different shape, and the predicate is four tokens.

**D-TG-58 — The handover invariant lives on the Eloquent model, not only in the Filament action.**
Directly mirroring `ModelProfile::save()`, which wraps itself in `DB::transaction()` and enforces
"exactly one active per role" at the model layer *"so they hold regardless of entry point (panel,
tinker, a future artisan command) — not only when a Filament form happens to be in front of them."*
The Filament reassign action calls that model method. *Alternative rejected:* the action alone — it
would leave `tinker` and any future command able to produce Finding 2's hole.

**D-TG-59 — `moderators` is not time-versioned, so "was X a moderator at time T" is answerable only
from the flag on each message.** The source plan's §10.5 gives `moderators` an `is_active` boolean and
no interval. This is accepted, not corrected: a second history table here would duplicate what
FR-032's snapshot already records at the only granularity that matters. The consequence is stated
plainly in `contracts/message-derivation.md` §5 and is why re-derivation must be insert-only
(D-TG-49): a re-derive resolves the flag as of the moment it runs, which for a range spanning a
mapping change is **not** what live derivation would have written.

**D-TG-62 — Assignment candidates are proposed from stored observations, read-only, and confirming one
is what creates the mapping.** The candidate list is a read over `telegram_updates.payload` for
`chat_member` / `my_chat_member` observations in that chat (§12 "the bot's `chat_member` history
reveals who the chat's administrators are, and Filament proposes them as assignment candidates. The
operator confirms"). No live platform call — FR-050 forbids the panel making one, and the data is
already stored. An administrator on the platform is explicitly **not** a moderator in this domain
(FR-031); the two lists may differ, and that is allowed rather than reconciled.

### Message derivation

**D-TG-49 — Message derivation is INSERT-ONLY: `ON CONFLICT (telegram_chat_id, message_id) DO
NOTHING`.** Never `DO UPDATE`. Probe 6 confirms the already-present row is untouched, which makes
FR-033 (the moderator flag is never recomputed) and FR-002 (idempotency) the *same mechanism* rather
than two rules that could drift. It is also what makes re-derivation safe to run over a range that
overlaps already-derived messages. *Alternative rejected:* an upsert refreshing text and flags — it
would silently rewrite `is_from_moderator` on historical messages every time a re-derive ran, which is
exactly the retroactive rewrite the whole milestone exists to prevent.

**D-TG-50 — An edit is a targeted `UPDATE` of `original_text`, `normalized_text` and `edited_at`, and
of nothing else.** Probe 7 confirms `sent_at` and `is_from_moderator` survive it. This is the session's
second clarification made mechanical: the pre-edit text is not lost, it lives in the immutable
captured event that carried it, for as long as `telegram_updates.payload` survives retention. No
text-version table. *Alternative rejected:* a `telegram_message_texts` table — a fifth table, a join on
every text read, and scope this milestone did not budget, to preserve text beyond the window in which
the domain has already decided not to keep it.

**D-TG-51 — One identity upsert statement, replay-safe.** `first_seen_at = LEAST(stored, incoming)`,
`last_seen_at = GREATEST(stored, incoming)`, and the name fields written only when
`incoming >= COALESCE(stored.last_seen_at, incoming)`. Finding 4 and probe 5.

**D-TG-52 — Mapping a not-yet-observed moderator creates a placeholder identity by `INSERT … ON
CONFLICT (tg_user_id) DO NOTHING` with the numeric id alone.** Names null, `first_seen_at` null.
Probe 5 shows the first real observation then fills it in through the ordinary upsert path, creating no
second identity. This is the session's third clarification; it keeps one identity table, keeps the
relational link, and removes the ordering trap in which a moderator's very first message would be
flagged as a student's forever.

**D-TG-60 — A message with no personal sender has `is_from_moderator = false`, always.** An anonymous
administrator or a channel post carries `sender_chat` instead of `from`. The platform deliberately
withholds who acted, so the honest value is false, and the row is distinguishable by
`sender_chat_id IS NOT NULL` (FR-005). *Alternative rejected:* inferring a moderator from the group's
administrator list — it would attribute an answer to someone who may not have written it, in the
flattering direction, on exactly the data the domain is least sure about. A bot sender is likewise
always false (FR-017).

**D-TG-61 — Only `message`, `edited_message` and `my_chat_member` are interpreted here.**
`chat_member`, `message_reaction` and `callback_query` stay stored and marked handled, and are
interpreted at TG-M4 where the actions they represent have somewhere to attach (FR-011). TG-M1 already
requests all of them, which was the decision that could not be deferred; interpreting them is not this
milestone's.

**D-TG-63 — `normalized_text` comes from TG-M0's `normalize()`, unchanged, and `original_text` is never
passed through it.** `app/application/moderation/text.py` exposes `normalize(text)` and `redact(text)`.
Only the first is used here; the redactor stays unused until a model is called at TG-M5. A message with
no text stores `NULL` in both, never `''` (FR-009), so later matching cannot mistake an absent value
for empty content.

### Re-derivation

**D-TG-53 — Re-derivation is one operator CLI at `app/scripts/rederive_chat.py`, bounded, reported,
and refusing.** `python -m app.scripts.rederive_chat --chat <id> [--since …] [--until …]`. It is a
composition root, so check.sh's forward allowlist does not scan it and its reverse rule exempts
`app/scripts/` by directory — the same standing `tg_doctor.py` already has. It refuses a chat that is
not measured (FR-022), walks `telegram_updates` in `update_id` order in bounded batches (FR-021),
reports examined / derived / skipped (FR-021), and counts a captured event whose `payload_purged_at` is
set as skipped-because-purged rather than deriving a hollow row (FR-023). It re-uses the *same*
derivation function the actor calls — a second code path would be a second set of bugs.
*Alternative rejected:* triggering it from the monitor toggle. The operator chose the explicit command
in this session's first clarification, and a screen switch that silently starts a bulk job over
retained student messages is the wrong shape for the one action in this milestone with real data-volume
consequences.

**D-TG-64 — `drain_pending_updates` is reused as-is, not extended into a re-derivation engine.**
TG-M1's drain reconciles `processed_at IS NULL`. Re-derivation deliberately targets *already-handled*
events, which is why it is a separate, operator-invoked path rather than a flag on the drain.

### Chat identity and continuity

**D-TG-54 — The migration re-point is one transaction: move assignments, carry the opt-in and the
course reference forward, clear the opt-in on the superseded row; refuse if the destination already has
a current primary.** Findings 3 and probes 4 and 8. The refusal is surfaced as a coverage problem for
the operator to resolve rather than resolved by guessing which of two owners wins — picking one would
silently discard an ownership fact.

**D-TG-55 — Messages are *not* re-pointed across a migration; "one history" is a read-side union over
the link columns.** Re-pointing would mutate `telegram_chat_id` on immutable derived rows, and
`uq(telegram_chat_id, message_id)` makes it unsafe besides: the platform's message numbering either
side of a promotion can collide. The source plan's §20.2 asks for assignments and open items to follow
the group, and says nothing about messages. FR-053's "countable as one group's continuous history" is
satisfied by following `migrated_from_chat_id` / `migrated_to_chat_id`, which `0003` already stores.

**D-TG-65 — A coverage-losing standing change never clears `is_monitored`.** FR-054. The group stays
measured so the loss is *visible*; switching it off would tidy away the single failure the source plan
calls most likely to go unnoticed. Surfacing is a screen concern (D-TG-57), not a data change.

### The control panel

**D-TG-56 — Direction is `dir="auto"` per Arabic-content field; the panel locale and `dir` are not
touched.** Finding 1. Labels are Arabic string literals on the two resources.

**D-TG-57 — Two navigation groups, declared as plain strings.**
`protected static string|UnitEnum|null $navigationGroup` — probe 1 read the exact signature at
`vendor/filament/filament/src/Resources/Resource/Concerns/HasNavigation.php:24`; note it is `UnitEnum`,
not `BackedEnum` as `$navigationIcon` is. `'Moderation Intelligence'` for the two new resources and
`'Platform'` on `ModelProfileResource`, which is the one-line edit to existing panel code the source
plan's §17 names (FR-045). Resources are auto-discovered — `AdminPanelProvider` already calls
`discoverResources(in: app_path('Filament/Resources'), …)` — so no registration is needed. Directory
layout follows the installed convention exactly: `Resources/<Plural>/<Name>Resource.php` with
`Pages/`, `Schemas/`, `Tables/` beside it. *Alternative rejected:* a backed enum for the group names.
Two string literals need no type, and the repo has no enum precedent.

**D-TG-66 — Assignments are a relation manager on the moderators resource, not a resource of their
own.** The source plan's §25 TG-M2 row says *"Moderators resource with an Assignments relation
manager"*. They are never navigated to independently, and they must be created through the handover
action rather than a free-form create form — which a relation manager's action set expresses and a
top-level resource invites bypassing.

**D-TG-67 — No migration, no `GRANT`, and no platform call from the panel.** Probe 9 confirms
`ALTER DEFAULT PRIVILEGES` already grants the panel's role DML on anything the migrator creates, in
both databases, so the revision adds no `GRANT` — the first milestone where that mattered, since
TG-M1 shipped no screens. `config/database.php` already records that Alembic owns the schema and
`DB::prohibitDestructiveCommands()` is on outside testing. Panel tests use `DatabaseTransactions`
against `injaz_ai_test` (FR-070, SC-034).

**D-TG-68 — The course reference is a plain integer field with no relational link and no validation.**
Source plan §24: the reference application holds invite URLs, not numeric chat ids, and a bot cannot
resolve a link to an id — so automatic mapping is impossible without a change inside a read-only
directory. `telegram_chats.injaz_course_id` already exists from `0003`, unused; this milestone is its
first consumer, and it stays manual (FR-046, Principle III).

---

## §3 — Settings

One new setting; everything else this milestone needs already exists from TG-M0.

| Setting | Default | Why | Validation |
|---|---|---|---|
| `MODERATION_REDERIVE_BATCH_SIZE` | `500` | FR-021's bounded batches. Large enough that a 90-day catch-up is a handful of round trips, small enough that one batch is a short transaction | must be positive, rejected at startup otherwise (FR-065) |

Already present and first consumed here: `MODERATION_TEXT_RETENTION_DAYS` (the retention *shape* only
— no purge runs), and `MODERATION_BURST_GAP_S` / `MODERATION_ITEM_MAX_AGE_S`, which remain
configured-but-unconsumed until TG-M3.

---

## §4 — What this milestone deliberately does not build

Recorded so each omission reads as a decision rather than an oversight (Principle V).

1. **No time-versioned `moderators` table.** D-TG-59. The message flag is the historical record.
2. **No message text-version table.** D-TG-50. The captured event is the archive.
3. **No re-pointing of messages across a chat migration.** D-TG-55. A read-side union instead.
4. **No automatic re-derivation on opt-in.** D-TG-53, and the operator's own clarification.
5. **No purge of names or text.** The markers exist; the job is TG-M10 (FR-058).
6. **No panel localisation, and no locale change.** D-TG-56. Per-field direction only.
7. **No interpretation of `chat_member`, `message_reaction` or `callback_query`.** D-TG-61, TG-M4.
8. **No metric, no query, no dashboard, no duration.** FR-059. The subjects, none of the measurements.
9. **No model profile for this domain and no widening of the roster's roles.** TG-M5.
10. **No `GRANT` in the migration and no change to the database roles.** Probe 9 — already covered.

---

## §5 — Traceability

| Decision | Serves |
|---|---|
| D-TG-46, D-TG-69 | FR-068, FR-069, SC-030, SC-031 |
| D-TG-47, D-TG-58 | FR-036, FR-037, SC-012, SC-013 |
| D-TG-48 | FR-041…FR-044, SC-014, SC-015, SC-016 |
| D-TG-49 | FR-002, FR-032, FR-033, SC-001, SC-011 |
| D-TG-50 | FR-010, SC-005 |
| D-TG-51, D-TG-52 | FR-014, FR-015, FR-027, FR-028, SC-009, SC-010 |
| D-TG-53, D-TG-64 | FR-020…FR-024, SC-006, SC-007, SC-008 |
| D-TG-54, D-TG-55, D-TG-65 | FR-052, FR-053, FR-054, SC-019, SC-020 |
| D-TG-56, D-TG-57, D-TG-66, D-TG-67, D-TG-68 | FR-045…FR-051, FR-070, SC-021…SC-023, SC-034 |
| D-TG-59, D-TG-60, D-TG-61, D-TG-63 | FR-005, FR-008, FR-009, FR-011, FR-017, FR-034 |

**0 unresolved `NEEDS CLARIFICATION`.** The three genuine ambiguities were resolved with the operator
before the spec was written; the four findings above were resolved by measurement.
