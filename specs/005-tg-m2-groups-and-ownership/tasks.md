---
description: "Task list for TG-M2 — Groups, Users, Messages and Moderator Ownership"
---

# Tasks: TG-M2 — Groups, Users, Messages and Moderator Ownership

**Input**: Design documents from `specs/005-tg-m2-groups-and-ownership/`
**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`

**Tests**: **Required**, not optional. Constitution Principle I mandates tests for contracts, data
integrity, idempotency and retry safety, business rules, and migrations — which is nearly all of this
milestone. `plan.md`'s Constitution Check enumerates the **25 behaviours that earn one**, each mapped
to an FR/SC. Behaviours named exempt there — Filament rendering, pagination, sorting, filtering, form
validation messages, navigation placement, help-text wording, Eloquent casting, migration column types,
Dramatiq delivery, SQLAlchemy Core wiring, the normaliser itself — get **no** test task here.

**Four tests exist because a probe proved the obvious test would pass while the code was broken:**
**T047** (a reassignment test that checks *near* the handover instant cannot see a microsecond hole —
it must assert the two timestamps are the *identical value*), **T063** (a chat promotion silently
un-measures the group, and nothing red appears), **T026** (a replayed older observation clobbers a
current display name), and **T037** (the moderator flag must survive a later mapping, *and* an
unmapping, *and* a deactivation — testing only the first leaves two open doors).

**Organization**: Grouped by user story so each is independently implementable and testable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on incomplete work)
- **[Story]**: US1…US6, mapping to `spec.md`'s user stories
- Paths are relative to the repository root

## Path Conventions

Per `plan.md` → Project Structure. Python service at `apps/ai-api/`, its tests at
`apps/ai-api/tests/`, migrations at `apps/ai-api/alembic/versions/`. **This is the first milestone that
also changes `apps/ai-control/`** — Eloquent models at `app/Models/`, resources at
`app/Filament/Resources/<Plural>/` with `Pages/`, `Schemas/`, `Tables/` beside them, feature tests at
`tests/Feature/`.

⚠ Three placements are load-bearing, not stylistic:

- **`rederive_chat.py` in `app/scripts/`**, not in the moderation package — it must import both
  moderation modules and shared infrastructure, which is the composition-root standing `app/scripts/`
  already has (same as `tg_doctor.py`). Putting it under `app/application/moderation/` fails
  `make check`.
- **`assignments.py` holds the only Python definition of `responsible_at`**; the Eloquent scope mirrors
  it. Two divergent definitions is the failure mode.
- **The handover lives on `ModeratorGroupAssignment`**, not in the Filament action — mirroring
  `ModelProfile::save()`, so it holds from `tinker` too.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: One setting and the test scaffolding. Nothing here has behaviour.

- [X] T001 [P] Add `MODERATION_REDERIVE_BATCH_SIZE` (default `500`) to `apps/ai-api/app/infrastructure/config.py`, with a positive-value validator following the existing `MODERATION_*` block's shape (FR-065, research §3)
- [X] T002 [P] Add `MODERATION_REDERIVE_BATCH_SIZE=500` to `.env.example` beside the existing TG-M1 block (FR-065)
- [X] T003 [P] Create the test package `apps/ai-api/tests/moderation/actors/__init__.py`
- [X] T004 [P] Create `apps/ai-api/tests/moderation/actors/conftest.py` — an async session factory against `injaz_ai_test` following `tests/moderation/ingest/conftest.py`, plus builders for `message`, `edited_message` and `my_chat_member` update payloads reusing TG-M1's fixture shapes. No new transport is needed: this milestone reads stored events, it does not poll

**Checkpoint**: The setting validates, the test package exists, and update payloads can be built.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The four tables, their four invariants, and the Eloquent models three stories need.

**⚠ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T005 Append the four tables to `apps/ai-api/app/infrastructure/models_moderation.py` on the shared `metadata`, exactly per `data-model.md` §1–§4: `telegram_users`, `telegram_messages`, `moderators`, `moderator_group_assignments`. **`telegram_users.first_seen_at` is nullable** — that is how a placeholder is distinguishable without a second flag column. **No CHECK on `telegram_messages.media_kind`** — the platform adds kinds, and a CHECK would turn an unmodelled shape into a lost message (FR-069, D-TG-46)
- [X] T006 Create `apps/ai-api/alembic/versions/0004_moderation_actors.py`, down-revision `0003`. `upgrade()` creates the tables in dependency order, then `ix_messages_chat_sent`, `ix_messages_chat_moderator_sent`, `ix_messages_reply`, `ix_assignment_chat_from`, `ix_assignment_moderator`, and the partial unique index via `op.create_index(..., unique=True, postgresql_where=sa.text("assignment_role = 'primary' AND valid_to IS NULL"))` — the idiom `0002_model_gateway.py:65` establishes. `downgrade()` reverses. **No `ALTER TABLE` and no `GRANT`** (FR-068, D-TG-46, probe 9)
- [X] T007 [P] `apps/ai-api/tests/moderation/actors/test_migration_0004.py` — upgrade to `0004`, assert the four tables and six indexes exist, downgrade to `0003`, assert they are gone, upgrade again. Column types are **not** asserted (exempt) (FR-068, SC-030)
- [X] T008 [P] `apps/ai-api/tests/moderation/actors/test_db_invariants.py` — attempt each of the four violations **directly in SQL**, not through the application: a duplicate `(telegram_chat_id, message_id)`; a duplicate `tg_user_id`; two moderators on one identity; a second current primary for one chat. Each must raise (FR-069, SC-031)
- [X] T009 [P] Create `apps/ai-control/app/Models/TelegramChat.php` — `$table = 'telegram_chats'`, fillable limited to what the panel may change (`is_monitored`, `injaz_course_id`, `notes`), casts for the booleans and timestamps, and a header comment recording that Alembic owns this schema, as `ModelProfile.php` does
- [X] T010 [P] Create `apps/ai-control/app/Models/Moderator.php` — `$table = 'moderators'`, relation to the sender identity, and a `telegramUserId` accessor. Deactivation must change nothing but availability (FR-030)
- [X] T011 [P] Create `apps/ai-control/app/Models/ModeratorGroupAssignment.php` — `$table = 'moderator_group_assignments'`, relations to chat and moderator, and a `currentPrimary` scope. The handover method is T048; this task creates only the model and its relations
- [X] T012 [P] Edit `apps/ai-control/app/Filament/Resources/ModelProfiles/ModelProfileResource.php` to add `protected static string|UnitEnum|null $navigationGroup = 'Platform';` and the `UnitEnum` import. ⚠ `UnitEnum`, **not** `BackedEnum` — that is what `$navigationIcon` takes, and swapping them is a fatal error. One line plus an import; no behaviour, query or form change (FR-045, D-TG-57)

**Checkpoint**: `make migrate` reaches `0004` and rolls back cleanly; the four invariants are the
database's; the panel has models and no orphaned screen.

---

## Phase 3: User Story 1 — Captured events become typed messages, exactly once (Priority: P1) 🎯 MVP

**Goal**: Each captured event in a measured group becomes exactly one message record, carrying the
platform's own send time, its sender, its reply target and its text — and deriving it again changes
nothing.

**Independent Test**: Feed a scripted set of captured events through the interpreting step, then the
identical set again, then a third time shuffled. One row per distinct message, identical values across
all three passes, send times from the platform's stamp. No credential, no network.

**Note**: sender identities are built here rather than in US3, because a message cannot be derived
without resolving its sender. US3 adds *moderators*, the placeholder path and the flag's semantics.

### Tests for User Story 1

- [X] T013 [P] [US1] `apps/ai-api/tests/moderation/actors/test_derivation.py` — the six message shapes each derive correctly and none is discarded: a plain message; a reply to a message that was never captured; an anonymous-administrator or channel post; a service announcement; a message with media and no text; an edited message (FR-001, FR-004…FR-007, FR-009, SC-004)
- [X] T014 [P] [US1] `apps/ai-api/tests/moderation/actors/test_idempotency.py` — the same captured event derived three times yields one row with byte-identical field values; a shuffled batch yields the same rows as an ordered one (FR-002, SC-001)
- [X] T015 [P] [US1] In `test_idempotency.py`, assert `sent_at` comes from the platform's `date` and never from `received_at` or `now()`, using a fixture whose two times differ by a known amount (FR-003, SC-002)
- [X] T016 [P] [US1] `apps/ai-api/tests/moderation/actors/test_edits.py` — an edit updates `original_text`, `normalized_text` and `edited_at` and **nothing else**: `sent_at`, `is_from_moderator`, `telegram_user_id` and `source_update_id` are unchanged. An edit for a message that was never derived matches zero rows and is a no-op, not an error (FR-010, SC-005)
- [X] T017 [P] [US1] In `test_derivation.py`, assert a message with no text stores `NULL` in both text columns — **never `''`** — and that punctuation-only text may legitimately normalise to `''` without that being read as a missing record (FR-009)
- [X] T018 [P] [US1] `apps/ai-api/tests/moderation/actors/test_drain.py` — a backlog of at least 100 not-yet-interpreted captured records is handed over in the platform's assigned order, all interpreted, zero duplicates (FR-013, SC-024)

### Implementation for User Story 1

- [X] T019 [US1] Create `apps/ai-api/app/application/moderation/identities.py` with the single replay-safe sender upsert from `data-model.md` §1: `first_seen_at = LEAST(...)`, `last_seen_at = GREATEST(...)`, and the name fields written only when the incoming observation is not older than the stored `last_seen_at`. One statement satisfies FR-014, FR-015 and FR-028 (D-TG-51)
- [X] T020 [US1] Create `apps/ai-api/app/application/moderation/messages.py` with `derive_message` as **INSERT-ONLY**: `INSERT … ON CONFLICT (telegram_chat_id, message_id) DO NOTHING RETURNING id`. ⚠ Never `DO UPDATE`, for any field. This one choice makes FR-002 and FR-033 the same mechanism; an upsert would silently rewrite the moderator flag on every re-derivation (D-TG-49, `contracts/message-derivation.md` §2)
- [X] T021 [US1] In `messages.py`, implement the per-field rules of `contracts/message-derivation.md` §3: `sent_at` from the platform's `date`; `sender_chat_id` for a senderless message; `reply_to_message_id` as the platform's own identifier with no foreign key; `is_service`; `media_kind` with `'other'` as the fallback; `entity_flags` for url/phone/mention/forward; `normalized_text` via TG-M0's `normalize()` with `original_text` left untouched (FR-003…FR-009, D-TG-63)
- [X] T022 [US1] In `messages.py`, implement `apply_edit` as a targeted `UPDATE … SET original_text, normalized_text, edited_at WHERE (telegram_chat_id, message_id)` — and nothing else (FR-010, D-TG-50)
- [X] T023 [US1] Fill in the body of `apps/ai-api/app/workers/tasks/moderation/process_update.py`, dispatching by kind: `message` → derive, `edited_message` → apply edit, `my_chat_member` → the standing path TG-M1 already owns. Every other kind is marked handled and derives nothing — declining to interpret is not a failure (FR-011, FR-012, D-TG-61). The actor's existing contract and its registration in `app/workers/main.py` are unchanged
- [X] T024 [US1] Confirm `drain_pending_updates` covers the filled-in actor and needs no change; add a test-only assertion if it does not. It reconciles the *unhandled* backlog and is deliberately **not** extended into a re-derivation engine (FR-013, D-TG-64)

**Checkpoint**: Post in a measured group and see a typed message row with the right send time, sender
and reply target. The table every later milestone reads now exists.

---

## Phase 4: User Story 2 — A group is measured only when someone decides it is (Priority: P2)

**Goal**: Derivation happens only for groups someone deliberately opted in, the groups screen is where
that decision is made, and one command catches a group up on what was captured before.

**Independent Test**: With captured events present for two groups, mark one measured and confirm
messages exist for it and none for the other. Then mark the second and run the re-derivation command:
its earlier events become messages with their original timestamps, a second run derives nothing, and
switching the toggle by itself derived nothing.

### Tests for User Story 2

- [X] T025 [P] [US2] `apps/ai-api/tests/moderation/actors/test_unmonitored.py` — a captured event whose chat is not measured produces zero message rows, zero sender identities and zero other derived state, and is **still marked handled**. Switching measurement off leaves already-derived rows intact (FR-019, FR-024, SC-003)
- [X] T026 [P] [US2] ⚠ `apps/ai-api/tests/moderation/actors/test_identities.py` — replay an **older** observation after a newer one and assert the current `display_name` and `username` are **not** overwritten and `last_seen_at` does **not** move backwards; assert `first_seen_at` correctly moves *back*. Probe 5 showed the obvious upsert fails all three silently (FR-015, SC-010, research Finding 4)
- [X] T027 [P] [US2] `apps/ai-api/tests/moderation/actors/test_rederive.py` — a measured chat's previously-captured events derive with their original send times; a second identical run derives zero; the run reports examined / derived / skipped (FR-020, FR-021, SC-006, SC-007)
- [X] T028 [P] [US2] In `test_rederive.py`, assert it **refuses** a chat that is not measured, and that a captured event whose `payload_purged_at` is set is counted skipped-because-purged — producing no hollow row and not aborting the run (FR-022, FR-023, SC-008)
- [X] T029 [P] [US2] In `test_rederive.py`, assert it walks captured events in `update_id` order and in batches bounded by `MODERATION_REDERIVE_BATCH_SIZE` (FR-021)
- [X] T030 [P] [US2] `apps/ai-control/tests/Feature/TelegramChatResourceTest.php` — switching the measured toggle writes one boolean and **starts no job**; the resource exposes no create and no delete action; setting the course reference stores a plain value and validates nothing against another system. `DatabaseTransactions` against `injaz_ai_test` (FR-018, FR-046, FR-070, SC-034)

### Implementation for User Story 2

- [X] T031 [US2] In `apps/ai-api/app/application/moderation/messages.py`, gate derivation on the chat's `is_monitored`: an unmeasured chat derives nothing and the event is still marked handled. Capture is unconditional and derivation is opt-in — that asymmetry is what makes catching up later possible (FR-019, `contracts/message-derivation.md` §6)
- [X] T032 [US2] Create `apps/ai-api/app/scripts/rederive_chat.py` — `python -m app.scripts.rederive_chat --chat <id> [--since …] [--until …]`. It refuses an unmeasured chat, walks `telegram_updates` in `update_id` order in bounded batches, calls the **same** derivation functions the actor calls, counts purged payloads as skipped, and prints examined / derived / skipped (FR-020…FR-023, D-TG-53, `contracts/message-derivation.md` §7)
- [X] T033 [US2] Create `apps/ai-control/app/Filament/Resources/TelegramChats/TelegramChatResource.php` with `$navigationGroup = 'Moderation Intelligence'`, plus `Pages/ListTelegramChats.php` and `Pages/EditTelegramChat.php`. **List and edit only** — groups are discovered by capture, never typed in, and deleting one would orphan messages and assignments (FR-046, D-TG-57)
- [X] T034 [US2] Create `apps/ai-control/app/Filament/Resources/TelegramChats/Tables/TelegramChatsTable.php` — columns for platform identifier, kind, title, bot standing and when observed, whether the bot may remove messages, when anything last happened, and measured. The title column carries `dir="auto"` (FR-046, FR-051, D-TG-56)
- [X] T035 [US2] Create `apps/ai-control/app/Filament/Resources/TelegramChats/Schemas/TelegramChatForm.php` — the measured toggle, the course reference as a plain integer with no relational link and no cross-system validation, and notes. Help text on the toggle names the re-derivation command and states that the toggle itself starts nothing (FR-046, D-TG-68)

**Checkpoint**: The operator switches one group on from a screen, and brings its back-history in with one
command whose output they can read. Presence is no longer mistaken for consent.

---

## Phase 5: User Story 3 — Moderators are named people, and a message remembers what its sender was (Priority: P3)

**Goal**: Moderators are declared — mappable before they have ever posted — and every message carries
whether its sender was a moderator **at the time of that message**, written once and never recomputed.

**Independent Test**: Map a moderator by a numeric identifier before that person has been observed;
confirm a placeholder exists with no name, then that their first message fills it in and is flagged as
a moderator's. Separately, derive a message from an unmapped sender, then map them, and confirm the
earlier message's flag has not moved.

### Tests for User Story 3

- [X] T036 [P] [US3] `apps/ai-api/tests/moderation/actors/test_placeholders.py` — mapping a never-observed numeric identifier creates exactly one placeholder identity (names `NULL`, `first_seen_at` `NULL`); the first real observation fills it in and creates **zero** second identities (FR-027, FR-028, SC-009)
- [X] T037 [P] [US3] ⚠ `apps/ai-api/tests/moderation/actors/test_moderator_snapshot.py` — a message written before its sender was a moderator keeps `is_from_moderator = false` after **all three** of: mapping that sender as a moderator, unmapping them, and deactivating them. Testing only the first leaves two open doors (FR-033, SC-011)
- [X] T038 [P] [US3] In `test_moderator_snapshot.py`, assert the flag is `false` for a bot sender and `false` for a message with no personal sender, and that the **database** refuses the flag without a personal sender (FR-017, D-TG-60)
- [X] T039 [P] [US3] In `test_moderator_snapshot.py`, assert the flag does not depend on whether that moderator owns the chat — anyone's answer ends a student's wait (FR-034)
- [X] T040 [P] [US3] `apps/ai-api/tests/moderation/actors/test_moderators.py` — mapping one identity to two moderators is refused, and a moderator cannot hold two identities; deactivation preserves the record, the assignment history and every flag already written (FR-026, FR-030)
- [X] T041 [P] [US3] In `test_moderators.py`, assert the operator-set display name is what reports use, so a changed platform profile name cannot alter who a report is about (FR-029)

### Implementation for User Story 3

- [X] T042 [US3] In `apps/ai-api/app/application/moderation/identities.py`, add placeholder creation: `INSERT INTO telegram_users (tg_user_id, is_bot) VALUES (:id, false) ON CONFLICT (tg_user_id) DO NOTHING`. Names `NULL`, `first_seen_at` `NULL` (FR-027, D-TG-52)
- [X] T043 [US3] In `apps/ai-api/app/application/moderation/messages.py`, resolve `is_from_moderator` **at insert** from whether the sender is a declared, mapped moderator at that moment — and never recompute it. `false` for a bot and for a senderless message. T020's insert-only write is the mechanism that keeps it (FR-032…FR-034, D-TG-49, D-TG-60)
- [X] T044 [US3] Add the mapping helper to `apps/ai-api/app/application/moderation/identities.py` that creates a moderator against an observed or placeholder identity in one transaction, so the panel and any future command share one path (FR-025…FR-027)

**Checkpoint**: The operator maps themselves and two test accounts before anyone has posted, and every
message from then on records what its sender was — permanently.

---

## Phase 6: User Story 4 — Ownership of a group is history, not a current value (Priority: P4)

**Goal**: Ownership is a half-open interval; a handover leaves no instant with two owners and none with
zero; and "who was responsible at *T*" is stable no matter what happens afterwards.

**Independent Test**: Open an assignment, close it, open a successor, and query responsibility before,
at, inside and after each interval. Separately, attempt a second current primary and confirm the store
refuses it.

### Tests for User Story 4

- [X] T045 [P] [US4] `apps/ai-api/tests/moderation/actors/test_responsible_at.py` — the **four boundary positions**: before `valid_from`, exactly at `valid_from` (included), exactly at `valid_to` (excluded), after `valid_to`. Tested *at* the boundaries, not near them (FR-044, SC-014)
- [X] T046 [P] [US4] In `test_responsible_at.py`, an instant covered by no assignment returns **no owner** and never substitutes the current one; a past instant's answer is unchanged after two later handovers, across at least three past instants spanning two owners; a backup is visible but never returned as responsible (FR-040, FR-042, FR-043, SC-015…SC-017)
- [X] T047 [P] [US4] ⚠ `apps/ai-api/tests/moderation/actors/test_handover.py` — after a handover, assert (a) the incumbent's `valid_to` and the successor's `valid_from` are the **identical value**, and (b) **exactly one** owner covers that exact instant. Probe 3 measured a ~10 ms hole with zero owners when two clock readings are used, and **no constraint fires** — a test that checks *near* the boundary cannot see it (FR-037, SC-013, research Finding 2)
- [X] T048 [P] [US4] In `test_handover.py`, assert a second current primary is refused with no partial rows; a failure induced partway leaves the incumbent current and zero successors open; a zero-width interval is refused; and no closed interval is deleted or rewritten across three handovers (FR-036…FR-038, SC-012, SC-013, SC-018)
- [X] T049 [P] [US4] `apps/ai-control/tests/Feature/AssignmentHandoverTest.php` — the same two assertions as T047, through the Eloquent model rather than the Python path, because **the panel is the writer** and Laravel's `now()` is evaluated per call. `DatabaseTransactions` against `injaz_ai_test` (FR-037, SC-013, research Finding 2)

### Implementation for User Story 4

- [X] T050 [US4] Create `apps/ai-api/app/application/moderation/assignments.py` with `responsible_at(chat, t)` as the single Python definition of the half-open predicate from `data-model.md` §4.2: `assignment_role = 'primary' AND valid_from <= t AND (valid_to IS NULL OR valid_to > t)`. Returns `None`, never the current owner, when nothing covers `t` (FR-041…FR-044, D-TG-48)
- [X] T051 [US4] In `assignments.py`, implement `open_assignment` and `handover` per `contracts/moderator-ownership.md` §2: one transaction, **close before open** — the partial unique index cannot be deferred (probe 2), so opening first is an immediate violation — and **one timestamp value bound to both sides** (FR-035…FR-038, D-TG-47)
- [X] T052 [US4] Add the handover method to `apps/ai-control/app/Models/ModeratorGroupAssignment.php`, wrapped in `DB::transaction()`, computing `$at = now()` **once** and binding it to both the incumbent's `valid_to` and the successor's `valid_from`. ⚠ Two separate `now()` calls are the bug. It lives on the model, not in the Filament action, mirroring `ModelProfile::save()` so it holds from `tinker` too (FR-037, D-TG-47, D-TG-58)
- [X] T053 [US4] Add a `responsibleAt` scope to `ModeratorGroupAssignment.php` mirroring T050's predicate exactly, and reference T050 in a comment as the canonical definition so the two cannot silently drift (FR-041, D-TG-48)

**Checkpoint**: Reassign ownership twice and ask who was responsible last Tuesday — the answer does not
move. This is the milestone's core claim, and it is now defensible rather than merely plausible.

---

## Phase 7: User Story 5 — The operator runs all of this from screens (Priority: P5)

**Goal**: Moderators are mapped and ownership handed over from the panel, with reassignment as one
action rather than two edits someone must remember to pair, and coverage problems visible at a glance.

**Independent Test**: Exercise each screen's actions against the test store inside a transaction —
switch measurement, add a moderator from a proposed candidate, open an assignment, perform a
reassignment — and confirm the panel makes no platform call and runs no schema change.

### Tests for User Story 5

- [X] T054 [P] [US5] `apps/ai-control/tests/Feature/ModeratorResourceTest.php` — a moderator can be added with an observed sender identity **or** with a numeric identifier never observed (creating exactly one placeholder); deactivation changes only availability (FR-047, SC-009)
- [X] T055 [P] [US5] In `ModeratorResourceTest.php`, the reassign action **delegates to the model method** rather than performing two writes of its own, and the assignments view lists every past and current assignment with role, interval and note, in chronological order, with nothing deletable (FR-048, D-TG-58)
- [X] T056 [P] [US5] `apps/ai-control/tests/Feature/PanelModerationGuardsTest.php` — no panel action issues a platform call, initiates a model call, or performs a schema change; there is no bulk-derivation action anywhere in the panel (FR-050, SC-022)
- [X] T057 [P] [US5] In `TelegramChatResourceTest.php`, measured groups with no primary owner and measured groups where the bot is not an administrator are each distinguishable without opening a record (FR-049, SC-023)

### Implementation for User Story 5

- [X] T058 [US5] Create `apps/ai-control/app/Filament/Resources/Moderators/ModeratorResource.php` with `$navigationGroup = 'Moderation Intelligence'`, plus `Pages/{ListModerators,CreateModerator,EditModerator}.php`, `Tables/ModeratorsTable.php` and `Schemas/ModeratorForm.php`. The form takes a stable display name and **either** an observed identity **or** a not-yet-observed numeric identifier — the latter being the runbook's normal path, not a fallback (FR-047, D-TG-52)
- [X] T059 [US5] Create `apps/ai-control/app/Filament/Resources/Moderators/RelationManagers/AssignmentsRelationManager.php` with the history list and a single **reassign** action delegating to T052's model method. A relation manager rather than a resource of its own, because assignments must be created through the handover action rather than a free-form create form (FR-048, D-TG-66)
- [X] T060 [US5] In the moderator form, propose candidates from **stored observations** — `chat_member` and `my_chat_member` payloads in `telegram_updates` for that chat. Read-only, no platform call, and confirming a candidate is what creates the mapping: an administrator on the platform is **not** a moderator here, and the two lists may differ (FR-031, FR-050, D-TG-62)
- [X] T061 [US5] Add coverage indicators to `Tables/TelegramChatsTable.php`: measured with no current primary owner, and measured with the bot not an administrator. Both failures are silent by nature — the source plan calls the second the single most likely way the system quietly stops working (FR-049)
- [X] T062 [US5] Apply `dir="auto"` to every Arabic-content field and column across both resources — titles, display names, notes. ⚠ The panel locale and its `dir` are **not** changed: Filament writes `dir` once onto `<html>` from one locale-driven key, so "RTL for this navigation group only" is not something the framework can do. `auto` also beats a fixed `rtl`, because these columns genuinely mix scripts (FR-051, D-TG-56, research Finding 1)

**Checkpoint**: The operator does the whole milestone from two screens, and the one sequence that could
corrupt ownership is the only sequence available to them.

---

## Phase 8: User Story 6 — Identity changes and coverage loss do not break the record (Priority: P6)

**Goal**: A promoted group keeps its ownership and its measurement; a demoted bot is visible rather than
tidied away; and every name and text is shaped so it can later be removed without breaking a count.

**Independent Test**: Feed a group-promotion sequence and confirm the assignments moved to the
surviving identity with zero intervals closed or opened and measurement carried forward. Feed a
demotion and confirm the standing changed, measurement did not, and the group is surfaced. Assert
removing a name or a text leaves every timestamp and count intact.

### Tests for User Story 6

- [X] T063 [P] [US6] ⚠ `apps/ai-api/tests/moderation/actors/test_migration_repoint.py` — after a promotion, the assignments point at the surviving chat row, **zero** intervals were closed and **zero** opened, and `is_monitored` and `injaz_course_id` were carried forward. Probe 4 showed TG-M1 leaves the surviving row at `is_monitored = false`, so the group silently stops being measured while every health signal stays green (FR-052, SC-019, research Finding 3)
- [X] T064 [P] [US6] In `test_migration_repoint.py`, assert the re-point **refuses** when the surviving row already has a current primary, rather than picking a winner and discarding an ownership fact; and that messages either side of the promotion are countable as one group's history with zero lost and zero double-counted (FR-053, D-TG-54)
- [X] T065 [P] [US6] `apps/ai-api/tests/moderation/actors/test_coverage.py` — a bot demotion in a measured group records the new standing, switches measurement off **zero** times, and surfaces the group as a coverage problem; a removal leaves existing messages and assignments untouched (FR-054, SC-020)
- [X] T066 [P] [US6] `apps/ai-api/tests/moderation/actors/test_retention_shape.py` — every name and text field subject to retention carries a removal marker; removing a name or a text leaves 100% of timestamps, flags and counts intact; names of identities linked to a moderator are excluded from removal; and this milestone removes nothing in normal operation (FR-055…FR-058, SC-025)

### Implementation for User Story 6

- [X] T067 [US6] In `apps/ai-api/app/application/moderation/assignments.py`, implement `repoint_for_migration(old_chat, new_chat)` per `data-model.md` §4.3: one transaction that moves the assignment rows, carries `is_monitored` and `injaz_course_id` forward, clears `is_monitored` on the superseded row, and **refuses** if the surviving row already has a current primary. **No interval is closed and none is opened** — a technical migration is not a handover, and recording one would show a false ownership change on the day of a promotion (FR-052, D-TG-54)
- [X] T068 [US6] In `apps/ai-api/app/application/moderation/ingest.py`, call `repoint_for_migration` after `apply_chat_migration_if_any`. Do **not** patch TG-M1's discovery path instead: only the re-point knows which row survives (FR-052, research Finding 3)
- [X] T069 [US6] In `apps/ai-api/app/application/moderation/messages.py`, add the read helper that follows `migrated_from_chat_id` / `migrated_to_chat_id` so a group's messages either side of a promotion are countable as one history. Messages are **not** re-pointed: that would mutate immutable derived rows, and `uq_telegram_messages_chat_msg` makes it unsafe besides, since message numbering either side of a promotion can collide (FR-053, D-TG-55)
- [X] T070 [US6] Confirm a coverage-losing standing change never clears `is_monitored` — the group stays measured so the loss *shows*. Surfacing is T061's job; this task is only the guarantee that the data is not quietly changed (FR-054, D-TG-65)

**Checkpoint**: The two ways this record silently degrades — a promotion and a demotion — are both
handled, and the retention shape is right before the tables hold real data.

---

## Phase 9: Polish & Cross-Cutting Concerns

- [X] T071 [P] Confirm `make check` passes with **no credential set and no model runtime running**, twice consecutively with identical results (FR-066, SC-028)
- [X] T072 [P] Confirm `check.sh`'s no-message-text rule still holds now that `original_text` and `normalized_text` are handled heavily: no `logger.*()` call may appear on a line that also references them. This is the first milestone that stresses that rule (FR-063, SC-029)
- [X] T073 [P] Confirm TG-M1's two non-negotiable guarantees have not regressed, by re-running `apps/ai-api/tests/moderation/ingest/test_no_outbound.py` against the widened change set: zero send, reaction, deletion, removal or restriction capability exists anywhere under `apps/ai-api/app/`, and zero inbound ports are opened (FR-060, FR-061)
- [X] T074 [P] Confirm zero files inside `injazedu/` were created, modified or deleted, and zero credentials appear in version-controlled files, via `./scripts/scan_secrets.sh` and a repository diff (FR-064, FR-067, SC-033)
- [X] T075 [P] Confirm zero panel tests reset, re-migrate or recreate a database, and all of them run against a store whose name carries the `_test` marker (FR-070, SC-034)
- [ ] T076 Run the `quickstart.md` walkthrough end to end, including §3's handover check (the two timestamps must be the identical value) and §4's three negatives (FR-001…FR-070). §1 (migration round-trip) and §6 (`make check` twice, with and without `TELEGRAM_BOT_TOKEN`) verified by the agent. §2–§5 need the operator's own Telegram id, the panel UI, and real messages in the dev group (`docs/runbooks/tg-operator-prerequisites.md` §C) — still open
- [X] T077 ⚠ **After operator agreement only** — add a one-line correction note to `docs/plan/telegram/telegram-moderation-intelligence.md` §17 recording that per-navigation-group text direction is not available in Filament and that direction is set per field instead. Do not edit it before the operator has agreed the change in `plan.md`'s operator item (Principle V)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies.
- **Foundational (Phase 2)**: depends on Setup. **Blocks every user story** — all four tables and the
  three Eloquent models are needed before any derivation or ownership work.
- **US1 (Phase 3)**: depends on Phase 2 only.
- **US2 (Phase 4)**: depends on US1 — re-derivation calls US1's derivation functions (R3), and the
  measurement gate lives in US1's module.
- **US3 (Phase 5)**: depends on US1 — the flag is written by US1's insert. Independent of US2 and US4.
- **US4 (Phase 6)**: depends on Phase 2 only. **Independent of US1, US2 and US3** — ownership intervals
  need no messages.
- **US5 (Phase 7)**: depends on US3 and US4 — it is the screen over both, and its reassign action
  delegates to US4's model method. Its groups-screen additions also touch US2's table class.
- **US6 (Phase 8)**: depends on US4 — the re-point moves assignments.
- **Polish (Phase 9)**: depends on everything wanted.

### User Story Dependencies

- **US1 (P1)** — the MVP. Nothing depends on Phase 2 but Phase 2.
- **US2 (P2)** — needs US1.
- **US3 (P3)** — needs US1. Can run alongside US2 and US4.
- **US4 (P4)** — needs only Phase 2. **The one story that can be built first if someone wants to.**
- **US5 (P5)** — needs US3 and US4.
- **US6 (P6)** — needs US4.

### Within Each Story

Tests before implementation. Modules before the actors and scripts that call them. Python before the
panel, since the panel mirrors predicates the Python side defines.

### Parallel Opportunities

- T001–T004 (Setup) are four independent files.
- T007–T012 (Foundational, after T005 and T006) are six independent files — two Python tests, three
  Eloquent models, one resource edit.
- Every test task inside a story is `[P]`: different files, no shared state beyond the test database.
- **US4 and US1 can be built in parallel by two people** right after Phase 2, since ownership intervals
  and message derivation touch no common file.

---

## Parallel Example: Foundational

```bash
# After T005 and T006 land, these six are independent files:
Task: "T007 test_migration_0004.py — up, assert, down, assert, up"
Task: "T008 test_db_invariants.py — the four violations, attempted directly in SQL"
Task: "T009 app/Models/TelegramChat.php"
Task: "T010 app/Models/Moderator.php"
Task: "T011 app/Models/ModeratorGroupAssignment.php"
Task: "T012 ModelProfileResource.php — one line, $navigationGroup = 'Platform'"
```

## Parallel Example: the two independent stories

```bash
# Once Phase 2 is complete, these share no file:
Developer A: Phase 3 (US1) → Phase 4 (US2) → Phase 5 (US3)
Developer B: Phase 6 (US4) → Phase 8 (US6)
# They converge at Phase 7 (US5), which needs both US3 and US4.
```

---

## Implementation Strategy

### MVP first (US1 only)

1. Phase 1 — Setup.
2. Phase 2 — Foundational. **Blocks everything.**
3. Phase 3 — US1.
4. **STOP and VALIDATE**: derive a scripted set three times and confirm one row per message with
   identical values, send times from the platform's stamp.

At that point captured events have become queryable facts, which is already more than the repository
can do today — though nothing is attributed to anyone yet.

### Incremental delivery

1. Setup + Foundational → four tables, four invariants, no orphaned screen.
2. **+ US1** → typed messages, idempotent. **MVP.**
3. **+ US2** → measurement is deliberate, and back-history can be brought in.
4. **+ US3** → every message remembers what its sender was, permanently.
5. **+ US4** → ownership is history, and a past attribution is defensible.
6. **+ US5** → the operator needs no SQL.
7. **+ US6** → a promotion and a demotion no longer degrade the record silently.

### Suggested MVP scope

**Phases 1–3 (T001–T024).** But note that the milestone's *acceptance* criterion — *"For any event
timestamp, the panel shows the moderator who was responsible then"* — needs **US3, US4 and US5**. US1
alone is a technical milestone, not the operator-visible one; Phases 1–7 are the smallest set that
satisfies the source plan's TG-M2 row.

---

## Notes

- `[P]` = different files, no dependency on incomplete work.
- Four tasks are marked ⚠ because a probe proved the obvious version of the test passes while the code
  is broken: **T026**, **T037**, **T047**, **T063**. Treat those four as the milestone's real risk.
- **T047 and T049 are the same assertion in two languages**, deliberately. The hazard is PHP-side —
  Laravel's `now()` is evaluated per call — but the Python path must not be allowed to regress either.
- ⚠ **T077 is gated on the operator**, not on any task. Do not edit the source plan before they have
  agreed FR-051's changed mechanism.
- Git actions are **operator steps**, never agent steps (Constitution IV). No task here commits,
  branches, pushes or merges.
- `.specify/scripts/bash/check-prerequisites.sh` aborts with *"Not on a feature branch. Current branch:
  m2/moderator-ownership"* — because the operator names branches their own way and the agent creates
  none. Paths were resolved from `.specify/feature.json` instead, exactly as TG-M1 did. The
  constitution wins over a Spec Kit naming convention, as its Governance clause provides.
