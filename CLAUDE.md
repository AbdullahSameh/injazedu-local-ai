<!-- SPECKIT START -->
Active feature: **TG-M2 — Groups, Users, Messages and Moderator Ownership** (`specs/005-tg-m2-groups-and-ownership/`)

Read before working on this feature:

- `specs/005-tg-m2-groups-and-ownership/plan.md` — implementation plan, Constitution Check, the one operator item
- `specs/005-tg-m2-groups-and-ownership/spec.md` — requirements (FR-001…FR-070), success criteria, 3 clarifications
- `specs/005-tg-m2-groups-and-ownership/research.md` — 24 decisions (D-TG-46…D-TG-69), 10 probes, **4 findings**
- `specs/005-tg-m2-groups-and-ownership/data-model.md` — the four tables of revision `0004`, the handover SQL, the retention shape
- `specs/005-tg-m2-groups-and-ownership/contracts/moderator-ownership.md` — **the** TG-M2 contract: the interval algebra, the handover protocol, `responsible_at` (O1–O5), the attribution rules, the non-promises
- `specs/005-tg-m2-groups-and-ownership/contracts/message-derivation.md` — the two write modes, the moderator snapshot and its limits, re-derivation, G-D1–G-D7
- `specs/005-tg-m2-groups-and-ownership/contracts/control-panel-moderation.md` — the two screens, navigation, the RTL finding, what the panel may not do
- `specs/005-tg-m2-groups-and-ownership/quickstart.md` — operator walkthrough, smoke test, 10 known limitations

This is the third milestone of a **second bounded domain**, not a feature of the first. Its source
plan of record is `docs/plan/telegram/telegram-moderation-intelligence.md` (11 milestones, TG-M0…TG-M10);
the operator's human steps are `docs/runbooks/tg-operator-prerequisites.md` — **§C's TG-M2 row (the
operator's own numeric Telegram id and the two test accounts') is a prerequisite for the smoke test**,
on top of §B still holding, though every automated test runs without either.

TG-M2 **judges nothing**: no question recognised, no attention item, no duration, no incident, no model
call, no outbound message, no inbound port. It produces the *subjects* of every later measurement and
none of the measurements. It is the first milestone to change **both** the Python service and the PHP
control panel. Alembic revision `0004` is consumed here; `0005`–`0009` stay reserved.

The two rules that carry this milestone:

- **Ownership is history, never a current value.** An assignment is a half-open interval
  `[valid_from, valid_to)`. A handover is **one transaction, close before open, one timestamp value
  bound to both sides**. Exactly one *current* primary per group is a partial unique index's job.
- **Every attribution is write-once.** `is_from_moderator` is resolved at insert and **never**
  recomputed; message derivation is therefore `ON CONFLICT … DO NOTHING`, never an upsert. An edit is a
  separate targeted `UPDATE` of text and `edited_at` only.

Four measured facts that drive this design (see research.md §0):

1. ⚠ **Per-navigation-group text direction does not exist in Filament v5.7.8.** `dir` is written once
   onto `<html>` from one locale-driven translation key (`base.blade.php:16`), so spec FR-051's two
   halves conflict: switching the locale to `ar` turns the *whole* panel RTL. Direction is set
   **per field** as `dir="auto"` and the locale is left alone — D-TG-56. The source plan's §17 asserts a
   capability the framework does not have.
2. ⚠ **Two timestamps in one reassignment open a hole in ownership history that nothing detects.**
   Measured: two clock readings leave a ~10 ms window with **zero** owners; no constraint fires and
   `responsible_at` reports "nobody responsible", which a later milestone renders as a coverage problem
   that never existed. It is a **PHP-side** hazard — Laravel's `now()` is evaluated per call, so
   `$incumbent->update(['valid_to' => now()])` followed by `create([... 'valid_from' => now()])` **is
   the bug**. One value, bound twice — D-TG-47. A partial unique index **cannot** be deferred, so
   close-before-open is also mandatory.
3. ⚠ **TG-M1's `apply_chat_migration_if_any` leaves the surviving chat row at `is_monitored = false`**,
   so a group **silently stops being measured when it is promoted** to a supergroup while every health
   signal stays green. The re-point must carry `is_monitored` and `injaz_course_id` forward — D-TG-54.
4. ⚠ **A re-derivation of older events would overwrite a sender's current display name with a stale
   one** and drag `last_seen_at` backwards. Use `LEAST`/`GREATEST` on the timestamps and write the name
   fields only when the incoming observation is not older — one statement — D-TG-51.

Architecture rules, mechanically enforced by `make check`:

- **no `httpx` / `ollama` / `openai` import outside `app/providers/`** (M1);
- **moderation modules may import only** `app.{domain,application}.moderation`, `app.providers.telegram`,
  `app.workers.tasks.moderation`, `app.application.gateway`, `app.infrastructure`, `app.domain.model_profile`;
- **no assessment-side module may import moderation** (composition roots — `app/main.py`, `app/workers/`,
  `app/scripts/`, and `app/`-root files such as `app/telegram_main.py` — are exempt **by directory**;
  this is why `app/scripts/rederive_chat.py` may import both);
- **no Telegram SDK** outside `app/providers/telegram/`; the provider speaks the Bot API over `httpx`;
- **no message text in any log line.** `check.sh`'s check 4 fails a `logger.*()` call on a line that
  also mentions `original_text`, `normalized_text`, `redacted_text`, `message_text` or `caption` — this
  is the first milestone that handles those columns heavily. The correlation key is `message_id`, never
  `message` — stdlib `logging` rejects `extra={"message": …}` inside `makeRecord` (TG-M0's D-TG-24).

Panel rules: Alembic owns the schema, so **no migration from Filament**; no platform call, no model
call, no bulk job behind a toggle. Feature tests use `DatabaseTransactions` against `injaz_ai_test` —
never `RefreshDatabase`, `DatabaseMigrations` or `migrate:fresh`. No `GRANT` is needed in a migration:
`ALTER DEFAULT PRIVILEGES FOR ROLE ai_migrator` already reaches `ai_control` in both databases.

Previous milestones (still current infrastructure): `specs/001-m0-foundation/`,
`specs/002-m1-model-gateway/`, `specs/003-tg-m0-moderation-foundation/`,
`specs/004-tg-m1-telegram-ingestion/`. The M1 gateway is untouched; TG-M0's boundary, settings and
normaliser and TG-M1's captured events, chat records and `process_update` handoff are all consumed here.

Project-wide, always: `.specify/memory/constitution.md`. Its non-negotiables in one line —
`injazedu/` is read-only, Git actions belong to the operator, and no test may touch a database
whose name lacks `_test`.

Broader context: `docs/plan/core/final-injazedu-local-ai-code-agent-implementation-plan.md`.
<!-- SPECKIT END -->
