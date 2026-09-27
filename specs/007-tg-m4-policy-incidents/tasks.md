---
description: "Task list for TG-M4 — Policy Incidents"
---

# Tasks: TG-M4 — Policy Incidents

**Input**: Design documents from `specs/007-tg-m4-policy-incidents/`
**Prerequisites**: `plan.md` (three operator items — **all approved 2026-09-24**), `spec.md`, `research.md`,
`data-model.md`, `contracts/`, `quickstart.md`

**Tests**: **Required**, not optional. Constitution Principle I mandates tests for contracts, business
rules, idempotency and retry safety, data integrity, and data-transforming migrations — which is this
milestone. `plan.md`'s Constitution Check enumerates the behaviours that earn one. Behaviours it names
exempt — Filament resource, infolist, table and action wiring; Eloquent casting; Dramatiq delivery;
column types; JSON serialisation of `detail` — get **no** test task here.

**Five tests exist because a finding or probe proved the obvious test would pass while the code was
broken:** **T022** (TG-M2's own test sends a channel message with no `from`, a shape the platform never
sends — the real payload crashes derivation, research **Finding 1**), **T005** (the panel's percentile
floor reads `0` from a set-but-empty variable — every config test with a real value passes, **Finding
2**), **T038** (no membership change has ever been captured, so the classifier table is the only proof
of the payload shapes, **Finding 4**), **T041** (a ban recorded in the *promoted* chat must resolve an
incident on the *old* chat's message — a single-chat test is green), and **T048** (a closure inserted
without the guard *does* change a resolved incident's status — probe 8; the guard is load-bearing).

**Organization**: Grouped by user story so each is independently implementable and testable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on incomplete work)
- **[Story]**: US1…US6, mapping to `spec.md`'s user stories
- Paths are relative to the repository root

## Path Conventions

Per `plan.md` → Project Structure. Python service at `apps/ai-api/`, its new tests at
`apps/ai-api/tests/moderation/incidents/`, migrations at `apps/ai-api/alembic/versions/`. Panel at
`apps/ai-control/` — models at `app/Models/`, the resource at `app/Filament/Resources/Incidents/`
(following `Resources/TelegramChats/`'s `Pages/`, `Schemas/`, `Tables/` layout), feature tests at
`tests/Feature/`.

⚠ Four rules are load-bearing, not stylistic:

- **The lifecycle lives in the database.** `moderation_incident_evidence` and `moderation_incident_state`
  (`data-model.md` §3) are the **only** definitions of linkage and state. Python and PHP *read* them.
  **No code — including a test helper — computes a status, a "first" moment or a link** (lifecycle
  contract N6). Tests assert what the view returns.
- **`app/domain/moderation/incident.py` stays pure** — no I/O, no clock, no session — exactly as TG-M3's
  `attention.py`. It holds the membership classifier, the reaction delta and the label vocabularies.
- **The guard is on `ModerationIncident`**, not in a Filament action, and it is load-bearing (probe 8).
  Its lock literal is `'moderation:incidents'`, identical in both languages (lifecycle contract H4).
- **Never write the Bot API's admin method names** (`banChatMember`, `restrictChatMember`,
  `unbanChatMember`, `banChatSenderChat`, `unbanChatSenderChat`, `deleteMessage`, `setMessageReaction`,
  `sendMessage`) anywhere in application source — not even in a comment or docstring.
  `tests/moderation/ingest/test_no_outbound.py` scans both applications' source for them. Refer to the
  *events* (`chat_member`, `message_reaction`), never the methods.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: The one new setting, research Finding 2's fix, and the test scaffolding.

- [X] T001 [P] Add `MODERATION_INCIDENT_MAX_AGE_S` (default `86400`) to `apps/ai-api/app/infrastructure/config.py` in a new `# --- Policy Incidents (TG-M4, optional, defaulted) ---` block following the existing `MODERATION_*` shape, with a positive-value validator in the same style as `MODERATION_ITEM_MAX_AGE_S`'s (research §3, D-TG-122)
- [X] T002 [P] Add `MODERATION_INCIDENT_MAX_AGE_S=86400` to `.env.example` beside the TG-M3 block
- [X] T003 [P] In `infra/docker-compose.yml`: change the `ai-control` line to `MODERATION_PERCENTILE_MIN_SAMPLES: ${MODERATION_PERCENTILE_MIN_SAMPLES:-10}`, add `MODERATION_INCIDENT_MAX_AGE_S: ${MODERATION_INCIDENT_MAX_AGE_S:-86400}` to `ai-control`, and add the same key with the same default to the block that already passes `MODERATION_*` keys to the Python services (research **Finding 2**, operator item 3 — approved)
- [X] T004 [P] Make `apps/ai-control/config/moderation.php` blank-safe: both `percentile_min_samples` (default 10) and a new `incident_max_age_s` (default 86400) read as `filled($v) ? (int) $v : $default`, so a set-but-empty environment variable reads the default (`control-panel-incidents.md` §6 P19)
- [X] T005 [P] `apps/ai-control/tests/Feature/ModerationConfigTest.php` — with each variable set to the empty string, `config()` returns the default (10, 86400); with a real value, that value. ⚠ **Finding 2**: the running panel reads `0` today; a test that only sets real values passes against the broken code
- [X] T006 [P] `apps/ai-api/tests/moderation/incidents/test_config_incident.py` — default `86400`; `0` and negative rejected with a message naming the key
- [X] T007 [P] Create `apps/ai-api/tests/moderation/incidents/__init__.py` and `conftest.py` — an async session factory against `injaz_ai_test` following `tests/moderation/attention/conftest.py`; reuse TG-M2's chat / user / moderator / assignment factories and TG-M3's direct `telegram_messages` builder (explicit `sent_at`, `is_from_moderator`, `reply_to_message_id`, `sender_chat_id`); add `insert_incident(...)` and `insert_action(...)` builders that write rows **directly** (so US2/US3/US6 tests do not depend on US1's code), a `captured_update(kind, body)` builder for `chat_member` / `message_reaction` payloads shaped exactly per research Finding 4's reference quotes, and `read_state(incident_id)` / `read_evidence(incident_id)` helpers that **only** `SELECT` from the two views

**Checkpoint**: the setting validates; the panel can no longer read a blank key as 0; tests can build
incidents, evidence and captured events at chosen instants.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The two tables, the two views, their invariants, the readers, the lock, and the two panel
models every story needs.

**⚠ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T008 Append `moderation_incidents` and `moderation_actions` to `apps/ai-api/app/infrastructure/models_moderation.py` on the shared `metadata`, exactly per `data-model.md` §1–§2 — every column, both unique constraints (`uq_incident_anchor` on **`(telegram_chat_id, telegram_message_id)`**, not the message id alone — TG-M3's Finding 2; `uq_moderation_actions_source_update`), the composite `fk_incident_message`, and **all** CHECK constraints (`ck_incident_*` ×5, `ck_actions_*` ×7), plus the six indexes, three of them partial. **No `status` column** on incidents (D-TG-104). The membership kind is `expulsion`, never `removal` (D-TG-126)
- [X] T009 In the same file, declare the two views as lightweight read-only `sa.table("moderation_incident_evidence", sa.column(...), ...)` and `sa.table("moderation_incident_state", ...)` clauses — **not** `sa.Table(..., metadata)`, so no `metadata.create_all()` can ever create a table named like a view. Columns exactly as `data-model.md` §3's `SELECT` lists
- [X] T010 Create `apps/ai-api/alembic/versions/0006_moderation_incidents.py`, down-revision `0005`. `upgrade()`: create `moderation_incidents`, then `moderation_actions`, then the six indexes (partial ones via `postgresql_where=sa.text(...)` per `0005`), then `op.execute()` the **two `CREATE VIEW` statements verbatim from `data-model.md` §3.1 and §3.2** (evidence first — state reads it). `downgrade()`: drop the state view, the evidence view, then the tables in dependency order. **No `GRANT`** (probe 6), no FK to `message_classifications`, no alter of any existing table. Module docstring cites Findings 3 and TG-M3's Finding 2, as `0005`'s does. The views are the single definition of the four states, of linkage, and of "first" — no state changes on time, absence or deletion (FR-039, FR-042, FR-044)
- [X] T011 [P] `apps/ai-api/tests/moderation/incidents/test_migration_0006.py` — upgrade to `0006`, assert both tables, both views and the six indexes exist; downgrade to `0005`, assert all gone; upgrade again. Column types not asserted (exempt)
- [X] T012 [P] `apps/ai-api/tests/moderation/incidents/test_db_invariants.py` — attempt each violation **directly in SQL**: a duplicate anchor; an incident on a message that was never stored; a `category`/`severity` outside the vocabulary; `source='operator'` with no opener, or with a `message_classification_id`; a `reaction` with a strength other than acknowledgement, or with no `actor_moderator_id`; a `reversal` or `panel_false_positive` with any strength; a `panel_resolve` with an empty note; a panel kind with no incident or with a `source_update_id`; a captured kind with no `source_update_id`; a membership kind with no subject; a second row for the same `source_update_id`. Each must raise
- [X] T013 [P] Add `incident_lock(session)` to `apps/ai-api/app/application/moderation/locks.py` — `SELECT pg_advisory_xact_lock(hashtext('moderation:incidents'))`, the exact literal of lifecycle contract H4, as a module-level constant with a comment naming the PHP side as its twin (D-TG-114). Transaction-scoped, like `chat_lock`
- [X] T014 [P] Create `apps/ai-api/app/application/moderation/incidents.py` with `incident_state(session, incident_id)` and `incident_evidence(session, incident_id)` — plain `SELECT`s from the two views (evidence ordered `occurred_at, source_rank, evidence_id`). Module docstring: this module **reads** the lifecycle and never computes it (lifecycle contract N6)
- [X] T015 [P] Create `apps/ai-api/app/domain/moderation/incident.py` with the label vocabularies only for now: `CATEGORIES = ("SPAM_OR_AD", "ABUSE", "OTHER")`, `SEVERITIES = ("low", "medium", "high")` — D-TG-08's spelling (D-TG-101). Pure module; the classifier (US3) and reaction delta (US2) are added by their stories
- [X] T016 [P] Create `apps/ai-control/app/Models/ModerationIncident.php` — `$table = 'moderation_incidents'`, `$timestamps = false`, `$fillable` for the insert fields only, casts, relations `chat()` and `responsibleModerator()`, `anchorMessage()` (composite lookup, as `AttentionItem::anchorMessage()`), `state(): ?object` reading one row of `moderation_incident_state`, and `evidence(): Collection` reading `moderation_incident_evidence` in the contract order. Header comment: Alembic owns the schema; **state is derived by the views and never computed here**
- [X] T017 [P] Create `apps/ai-control/app/Models/ModerationAction.php` — `$table = 'moderation_actions'`, `$timestamps = false`, `detail` cast to array; `booted()` registers `updating` and `deleting` listeners that throw a `LogicException` ("moderation_actions is append-only"), so the invariant holds from `tinker` (D-TG-113)
- [X] T018 [P] `apps/ai-control/tests/Feature/ModerationActionImmutabilityTest.php` — creating a panel action succeeds; `update()` and `delete()` on it throw and leave the row unchanged (FR-018)

**Checkpoint**: `make migrate` reaches `0006` and rolls back cleanly; every invariant of `data-model.md`
is enforced by the database; both applications can read an incident's derived state; evidence cannot be
altered from the panel.

---

## Phase 3: User Story 1 — An operator flags an offending message, dated both when it was posted and when it was flagged (Priority: P1) 🎯 MVP

**Goal**: An operator opens exactly one incident on a stored message — from the Incidents list or from a
Live Attention Queue row — with required labels, both moments, the opener, and the owner at detection.
Messages sent on behalf of a channel can now be stored and flagged.

**Independent Test**: With a controlled clock and no network, open incidents against an ordinary
message, the same message twice, two chats' identically-numbered messages, a service announcement, a
bot's message, a channel's message, and messages in groups with no owner or with a later handover.
One incident per anchor, both moments right, refusals where required, attribution unmoved.

### Tests for User Story 1

- [X] T019 [P] [US1] `apps/ai-api/tests/moderation/incidents/test_anchor_unique.py` — two chats, each with its own message `#2`, both flagged → **two** incidents; the same anchor opened twice → one incident, the second attempt returns `None` without error (FR-002, SC-006)
- [X] T020 [P] [US1] `apps/ai-api/tests/moderation/incidents/test_open_incident.py` — `opened_at` equals the message's `sent_at`; `detected_at` is the insert time; `source='operator'` and the opener recorded; labels stored exactly; a service message is refused; a bot account's message is accepted; a message that anchors an attention item is accepted and the item is byte-identical afterwards; `read_state` returns `open` immediately (FR-001…FR-009, SC-025)
- [X] T021 [P] [US1] `apps/ai-api/tests/moderation/incidents/test_attribution.py` — `responsible_moderator_id` is the owner at **`detected_at`**, not `opened_at`: a handover between posting and flagging attributes to the incoming owner; a reassignment after flagging leaves it unmoved; no primary at detection → NULL; `valid_from` inclusive / `valid_to` exclusive at the detection instant (FR-046…FR-048, SC-012)
- [X] T022 [P] [US1] `apps/ai-api/tests/moderation/actors/test_sender_chat_payload.py` — a `message` whose payload carries **both** a fake `from` (`{"id": 1087968824, "is_bot": true, "username": "GroupAnonymousBot"}`, and separately a channel's placeholder) **and** `sender_chat` → the row is stored with `telegram_user_id` NULL and `sender_chat_id` set, no `telegram_users` row is created for the placeholder, `is_from_moderator` is false, and no attention judgement is scheduled. An ordinary message is unchanged. ⚠ **Finding 1**: TG-M2's test omits `from`, a shape the platform never sends; with the real shape the unfixed code raises `ck_telegram_messages_sender`
- [X] T023 [P] [US1] `apps/ai-control/tests/Feature/IncidentOpenTest.php` — the picker lists no service message and no already-anchored message (composite exclusion; seed two chats sharing a message number); category and severity are required and accept only the vocabulary; a submitted form writes `opened_at` = `sent_at`, `detected_at` ≈ now, `opened_by_user_id`, and the owner from `responsibleAt` at `detected_at`; a stale duplicate is rejected by the validation rule; the Live Attention Queue's **Open incident** row action opens against the item's anchor and leaves the item untouched

### Implementation for User Story 1

- [X] T024 [US1] In `apps/ai-api/app/application/moderation/messages.py` `derive_message`: when `body.get("sender_chat")` is a dict, treat `from` as the platform's compatibility placeholder — do not call `upsert_identity`, leave `telegram_user_id` NULL and `is_from_moderator` False. Comment quotes the Bot API's `sender_chat` sentence (research **Finding 1**, D-TG-99, operator item 2 — approved). No schema change; `ck_telegram_messages_sender` stays exactly as it is
- [X] T025 [US1] Add `open_incident(session_factory, *, telegram_chat_id, telegram_message_id, category, severity, opened_by_user_id, source="operator") -> int | None` to `apps/ai-api/app/application/moderation/incidents.py` — refuses a service message (`ValueError`), validates labels against `domain.incident`'s vocabularies, inserts with `opened_at` from the message's `sent_at`, `detected_at = sa.func.now()`, and `responsible_moderator_id` from TG-M2's `assignments.responsible_at(chat, t=now)` resolved in the **same** transaction, `ON CONFLICT ON CONSTRAINT uq_incident_anchor DO NOTHING RETURNING id`. Logs `incident_id` and `message_id` only (FR-081). Used by tests today and by TG-M5 tomorrow; the panel is the production opener
- [X] T026 [US1] Add `ModerationIncident::openOn(TelegramMessage $message, string $category, string $severity, User $by): ?self` to `apps/ai-control/app/Models/ModerationIncident.php` — refuses a service message; sets `detected_at` from one `now()` value bound once, `opened_at` from the message's `sent_at`, and `responsible_moderator_id` via `ModeratorGroupAssignment::query()->responsibleAt($chatId, $detectedAt)` (TG-M2's scope, not a second definition); inserts identity fields only and touches no attention item (`control-panel-incidents.md` §2 P9)
- [X] T027 [US1] Create `apps/ai-control/app/Filament/Resources/Incidents/Actions/OpenIncidentAction.php` — one reusable action: when given no message, a searchable picker of recent messages in measured groups excluding service messages and already-anchored ones by the composite key (P7); required `category` and `severity` selects with exactly the vocabulary (P8); a validation rule re-checking both exclusions at submit; calls `openOn`
- [X] T028 [US1] Create `apps/ai-control/app/Filament/Resources/Incidents/IncidentResource.php`, `Pages/ListIncidents.php` and `Tables/IncidentsTable.php` — navigation group `Moderation Intelligence`, no create/edit/delete pages (`canCreate`/`canEdit`/`canDelete` false); columns Group, Message (truncated, "Text removed" when purged), Category, Severity, Status (**read from `moderation_incident_state`** via a join or `state()`), Responsible (**Unassigned** badge when NULL), Posted, Flagged — each Arabic field `dir="auto"`; default sort `detected_at DESC`; header action `OpenIncidentAction`; **no bulk action**
- [X] T029 [US1] In `apps/ai-control/app/Filament/Pages/LiveAttentionQueue.php`, add **one** row action, `OpenIncidentAction` bound to the item's anchor message (`$record->anchorMessage()`), and change nothing else on the page (FR-072, D-TG-125)

**Checkpoint**: flag a message in the dev group from either screen — one incident, posted and flagged
both shown, the right owner, status **open**. A channel's post can be stored and flagged.

---

## Phase 4: User Story 2 — A moderator's reply or reaction records that the message was seen, and never that it was dealt with (Priority: P2)

**Goal**: A moderator's reaction (recorded from `message_reaction`) or direct reply (read in place) moves
an incident to acknowledged — and nothing that is acknowledgement ever resolves it.

**Independent Test**: With a controlled clock, script reactions and replies against incidents built by
`conftest.py`: moderator and non-moderator reactions, anonymous reactions, removals, the sender's own
reaction, a plain moderator message, evidence before posting and before flagging, and twenty
acknowledgements in a row. Confirm which incidents are acknowledged, the recorded moment and actor, and
that none is ever resolved.

**Depends on**: Phase 2 only (incidents are built directly by `conftest.py`).

### Tests for User Story 2

- [X] T030 [P] [US2] `apps/ai-api/tests/moderation/incidents/test_reaction_delta.py` — pure: an added emoji; a removed one (→ empty); a swap (→ the new one only); identical lists (→ empty); `custom_emoji` and `paid` reactions compared by identity; order within a list ignored (lifecycle contract V7)
- [X] T031 [P] [US2] `apps/ai-api/tests/moderation/incidents/test_reaction_evidence.py` — via `process_update_row` on a captured `message_reaction`: a declared moderator adding ✅ → one `reaction` row with `actor_moderator_id`, `target_message_id`, `occurred_at` = the event's `date`, emoji in `detail`; a non-moderator → no row; `actor_chat` with no `user` → no row; removal only → no row; an unmeasured chat → no row; the same event processed three times → one row; making the reactor a moderator afterwards changes nothing already recorded; `processed_at` set in every case (FR-011, FR-013, FR-015, FR-019)
- [X] T032 [P] [US2] `apps/ai-api/tests/moderation/incidents/test_acknowledgement.py` — reading `read_state` only: a moderator's direct reply → **acknowledged**, kind `reply`, actor the moderator; a moderator's reaction → acknowledged, kind `reaction`; a moderator's plain message → still open; a non-moderator's reply or reaction → still open; the sender's own reaction (sender is a moderator) → still open; evidence at or before `opened_at` → still open; two acknowledgements inserted latest-first → `first_acknowledgement_at` is the earlier platform timestamp; a reaction dated **after posting but before flagging** → acknowledged at the reaction's moment (FR-012, FR-016, FR-021…FR-025, the first clarification)
- [X] T033 [P] [US2] `apps/ai-api/tests/moderation/incidents/test_ack_never_resolves.py` — for every combination of up to four rows drawn from {moderator reply, moderator reaction, `panel_acknowledge`}, plus one incident with twenty of them, the status is `acknowledged` and never `resolved`; `resolved_at` is NULL (FR-023, SC-002 — **the milestone's acceptance**)

### Implementation for User Story 2

- [X] T034 [US2] Add `added_reactions(old: Sequence[Mapping], new: Sequence[Mapping]) -> tuple[Mapping, ...]` to `apps/ai-api/app/domain/moderation/incident.py` — identity by `(type, emoji | custom_emoji_id | "paid")`, order-insensitive, pure (D-TG-110)
- [X] T035 [US2] Create `apps/ai-api/app/application/moderation/evidence.py` with `derive_reaction_evidence(session_factory, *, update_row_id) -> int | None` — resolves the captured payload like `messages.derive_message`; gated on `is_monitored`; returns without a row when `user` is absent, when `added_reactions` is empty, or when the user is not a declared moderator (TG-M2's `_is_declared_moderator`, reused — move it to a shared helper only if the boundary check requires; do not restate it); upserts the reactor through `upsert_identity`; inserts `action_type='reaction'`, `action_strength='acknowledgement'` with `ON CONFLICT ON CONSTRAINT uq_moderation_actions_source_update DO NOTHING`. **No lock** (lifecycle contract H4). Logs `update_id` and `chat_id` only
- [X] T036 [US2] In `apps/ai-api/app/workers/tasks/moderation/process_update.py`, dispatch `message_reaction` to `derive_reaction_evidence` before `processed_at` is set; update the module docstring's kind list (D-TG-112). Direct replies need **no** code: view branch (b) reads them in place (D-TG-111)

**Checkpoint**: react ✅ to a flagged message in the dev group — the incident is **acknowledged**, dated
by the reaction, credited to you, and ten more reactions do not resolve it.

---

## Phase 5: User Story 3 — Removing or restricting the sender resolves the incident, attributed to whoever the platform says did it (Priority: P3)

**Goal**: A ban, expulsion or restriction of the sender — recorded from `chat_member` — resolves every
open or acknowledged incident on that member's messages in that group, including across a promotion,
crediting a moderator only when the platform names one.

**Independent Test**: Script membership changes against incidents built by `conftest.py`: the sender
banned, expelled, restricted, unbanned, leaving voluntarily; a different member; a different group; the
promoted successor chat; performers who are a moderator, a non-owner moderator, an unmapped admin, a bot
and the anonymous-administrator account; one ban with three open incidents; and the same evidence in
three orders.

**Depends on**: Phase 2 only. ⚠ Shares `domain/incident.py`, `evidence.py` and `process_update.py` with
US2 — run after US2's T034–T036, or accept one merge in each file.

### Tests for User Story 3

- [X] T037 [P] [US3] `apps/ai-api/tests/moderation/incidents/test_membership_classifier.py` — pure, table-driven over **every** row of lifecycle contract V3 plus: performed by the member themselves (every pair → nothing); `left → member` (join → nothing); `member → administrator` and back (→ nothing); `restricted (is_member false) → left` (→ reversal); `left → kicked` (ban after leaving → ban); `restricted → restricted` (→ restriction); first-match order asserted where rows overlap
- [X] T038 [P] [US3] ⚠ This task is the **Finding 4** proof: in the same file, one case per status transition built from a full `ChatMemberUpdated` dict shaped exactly as the Bot API 10.3 reference quoted in research Finding 4 (`from`, `date`, `old_chat_member`, `new_chat_member` with `status`, `user`, `is_member`, `until_date`) and fed through the payload-reading wrapper, not only the bare classifier — no live event of this kind has ever been captured, so this is the only evidence the shapes are read correctly
- [X] T039 [P] [US3] `apps/ai-api/tests/moderation/incidents/test_membership_evidence.py` — via `process_update_row` on a captured `chat_member`: a ban → one `ban`/`enforcement` row with performer and subject identities upserted, `occurred_at` = `date`, both statuses and `until_date` in `detail`, `actor_moderator_id` set only when the performer is a declared moderator; a voluntary leave → no row; an unmeasured chat → no row; performer `GroupAnonymousBot` → `actor_is_anonymous = true`; the same event three times → one row (FR-010, FR-013, FR-014, FR-019)
- [X] T040 [P] [US3] `apps/ai-api/tests/moderation/incidents/test_linkage.py` — via `read_state`/`read_evidence`: a ban of the sender with no prior evidence → **resolved** directly, `resolution_kind='ban'`, no acknowledgement (SC-004); a restriction after an acknowledgement → resolved, acknowledgement still recorded; **one ban → three incidents resolved** (SC-008); a ban of a different member, a ban in a different group, a ban dated at or before `opened_at` → unchanged (SC-007); a ban by a non-owner moderator → that moderator is the actor and the responsible moderator is unchanged; by an unmapped admin, a bot, or anonymously → resolved, `resolved_by_moderator_id` NULL, performer identity present (SC-015); an unban afterwards → listed with NULL strength, still resolved; an anchor sent on behalf of a chat → no membership evidence ever links (FR-026…FR-033, FR-049)
- [X] T041 [P] [US3] `apps/ai-api/tests/moderation/incidents/test_lineage.py` — an incident on a message in a chat later promoted (old row's `migrated_to_chat_id` set, successor row present), and the sender's ban recorded in the **successor** chat → resolved; a ban in an unrelated chat → unchanged; the incident's own row is never re-pointed. ⚠ A single-chat test cannot see this (FR-082, SC-018, probe 8)
- [X] T042 [P] [US3] `apps/ai-api/tests/moderation/incidents/test_order_independence.py` — one incident; evidence {reaction 10:07, ban 10:12, `panel_resolve` 10:20} inserted in three different orders into three fresh transactions → the `moderation_incident_state` row is identical every time, including `first_acknowledgement_at`, `first_enforcement_at`, `first_confirmation_at`, `resolved_at` and `resolution_kind`; a reaction inserted *after* the ban still sets `first_acknowledgement_at` (FR-045, SC-005)
- [X] T043 [P] [US3] `apps/ai-api/tests/moderation/incidents/test_pre_flag_evidence.py` — a ban dated after posting but **before** `detected_at` → the incident reads **resolved** from the moment it exists, crediting the performer; a ban dated before posting → still open (the first clarification, FR-043, SC-023 state half; the figure half is in T058)

### Implementation for User Story 3

- [X] T044 [US3] Add `classify_membership_change(old: Mapping, new: Mapping, *, performed_by_subject: bool) -> tuple[str, str | None] | None` and `is_anonymous_performer(user: Mapping) -> bool` (the platform's `GroupAnonymousBot` account, by username on a bot user) to `apps/ai-api/app/domain/moderation/incident.py` — lifecycle contract V1–V3 top-to-bottom, first match wins, returns `(kind, strength)` or `None`. Pure (D-TG-108, D-TG-109)
- [X] T045 [US3] Add `derive_membership_evidence(session_factory, *, update_row_id) -> int | None` to `apps/ai-api/app/application/moderation/evidence.py` — gated on `is_monitored`; reads `from`, `new_chat_member.user`, both statuses and `date`; classifies with `performed_by_subject = from.id == subject.id`; upserts performer and subject through `upsert_identity`; resolves `actor_moderator_id` by TG-M2's rule; sets `actor_is_anonymous`; takes `incident_lock` **before** the insert (lifecycle contract H4); inserts with `ON CONFLICT ON CONSTRAINT uq_moderation_actions_source_update DO NOTHING`. Logs `update_id` and `chat_id` only
- [X] T046 [US3] In `apps/ai-api/app/workers/tasks/moderation/process_update.py`, dispatch `chat_member` to `derive_membership_evidence` before `processed_at` is set (D-TG-112)
- [X] T047 [US3] In `apps/ai-api/app/application/moderation/assignments.py`, extend `repoint_for_migration`'s docstring with one paragraph: incidents, like attention items, are **not** re-pointed (the composite FK onto a per-chat message number); the evidence view follows the group through one promotion hop instead (D-TG-107). Code unchanged

**Checkpoint**: restrict the disposable account in the dev group — every incident on its messages reads
**resolved**, by your name, dated by the restriction; unbanning it changes nothing.

---

## Phase 6: User Story 4 — An operator can confirm what the platform cannot see, and can withdraw a false accusation (Priority: P4)

**Goal**: Acknowledge, resolve-with-note and not-a-violation, each a guarded insert under the shared
lock; nothing leaves a terminal state.

**Independent Test**: From the panel, attempt every act in every state, submit twice, act on a page
made stale by evidence landing underneath, and let evidence arrive after a terminal state. Confirm the
recorded account, moment, note and reason, the refusals, and that no terminal state moves.

**Depends on**: US1 (the list the actions live on). The Python test T048 depends on Phase 2 only.

### Tests for User Story 4

- [X] T048 [P] [US4] `apps/ai-api/tests/moderation/incidents/test_closure_precedence.py` — view-level, rows inserted directly: a `panel_false_positive` on an open incident → `closed_false_positive` with reason and account; a ban recorded **after** that closure → still closed, the ban listed in the evidence; a `panel_resolve` → resolved by confirmation, no moderator credited (H7); and — documenting probe 8 — a closure row inserted over a **resolved** incident *without* the guard → status changes, with the test's docstring stating that this is why `ModerationIncident`'s guard is load-bearing (FR-037, FR-041)
- [X] T049 [P] [US4] `apps/ai-control/tests/Feature/IncidentActionsTest.php` — `acknowledge` succeeds only from open; `resolve` and `closeAsFalsePositive` only from open or acknowledged; each requires its note/reason; each records `panel_user_id` and its incident; a second identical call inserts nothing and returns false; a ban row inserted between page load and submit makes a subsequent `closeAsFalsePositive` insert nothing; on a resolved or closed incident no act is offered in the table; each act issues the advisory-lock statement with the literal `moderation:incidents` (asserted via `DB::listen`) — together with T040 and T048 this covers the full transition table (FR-040, FR-041, SC-003)

### Implementation for User Story 4

- [X] T050 [US4] Add `acknowledge(User $by): bool`, `resolve(User $by, string $note): bool` and `closeAsFalsePositive(User $by, string $reason): bool` to `apps/ai-control/app/Models/ModerationIncident.php` — each one `DB::transaction`: `SELECT pg_advisory_xact_lock(hashtext('moderation:incidents'))` (a class constant, commented as the twin of `locks.py`'s), read the status from `moderation_incident_state`, insert a `ModerationAction` (`panel_acknowledge` / `panel_resolve` with note / `panel_false_positive` with reason; `occurred_at` = the transaction's `now()`) only if lifecycle contract H1 allows it, return whether a row was inserted — each act is itself evidence carrying the account and moment (FR-017, FR-040, D-TG-114, D-TG-115)
- [X] T051 [US4] Create `apps/ai-control/app/Filament/Resources/Incidents/Actions/{AcknowledgeIncidentAction,ResolveIncidentAction,CloseFalsePositiveAction}.php` and attach them as row actions in `Tables/IncidentsTable.php`, each visible only when the incident's current status allows it; Resolve's required note carries the helper text of `control-panel-incidents.md` §3; Not a violation's reason is required; no bulk action anywhere (FR-034…FR-038)

**Checkpoint**: resolve an incident on a moderator's word — it reads **resolved by confirmation**, as
your statement; close another as not a violation — it leaves every figure; neither can be acted on
again.

---

## Phase 7: User Story 5 — One screen answers the six questions about any incident (Priority: P5)

**Goal**: A view page answering what, when, why, who, how long and corrected — with the evidence trail,
the standing sentence, and the notices — and a list that filters and shows age.

**Independent Test**: Seed incidents in every state with known evidence — none, pre-flag, every kind, a
purged text, a group where the bot is not an administrator, a channel-sent anchor, an unmapped performer
— and confirm each question is answered, absences read as absences, and no wording implies a deletion.

**Depends on**: US1 (the resource). Reuses US4's action classes on the view page when present.

### Tests for User Story 5

- [X] T052 [P] [US5] `apps/ai-control/tests/Feature/IncidentResourceTest.php` — list: filters by status, category, severity, group, responsible moderator and detection date each narrow correctly; **Unassigned** badge; "Age / took" shows a human duration while open and "acted before flagging" for a pre-flag resolution; view: all six sections present; the trail lists every piece of evidence in `(occurred_at, source_rank, evidence_id)` order with the fixed kind labels, actors (moderator name / platform name / "anonymous administrator" / panel account) and captured-event ids; a missing timing reads "no evidence", never `0`; a purged anchor shows "Text removed" with moments, trail and timings intact; the bot-not-administrator notice appears only when `bot_status <> 'administrator'`; the channel-sender notice appears only for an anchor with `sender_chat_id` and no user; "No model classification — arrives with TG-M5" is present; Arabic fields carry `dir="auto"` (FR-067…FR-077, SC-017)
- [X] T053 [P] [US5] `apps/ai-control/tests/Feature/IncidentWordingTest.php` — render the list and the view page of an incident carrying **every** evidence kind; assert the standing sentence *"Telegram does not report message deletion in groups; no removal evidence is available."* is present on both; remove that sentence and "Text removed", then assert no case-insensitive `delet` or `remov` substring remains (FR-020, FR-070, SC-013, D-TG-126)

### Implementation for User Story 5

- [X] T054 [US5] Create `apps/ai-control/app/Filament/Resources/Incidents/Pages/ViewIncident.php` and `Schemas/IncidentInfolist.php` — the six sections of `control-panel-incidents.md` §1.2, every moment in `Asia/Riyadh` and every duration in human units (FR-075); timings from the incident's `state()` row, rendered as a duration, "acted before flagging" when negative, or "no evidence" when NULL (M19); the outcome against `config('moderation.incident_max_age_s')`; header actions reuse US4's three action classes; register the view page on `IncidentResource`
- [X] T055 [US5] Render the evidence trail in `IncidentInfolist.php` from `evidence()` with the fixed kind labels of `control-panel-incidents.md` §5 P17 (`expulsion` → "Expelled from the group (not banned)", `reversal` → "Unban / restriction lifted — no effect", …), actor resolution per lifecycle contract A3, affected member for membership kinds, and `source_update_id` or "panel"; notes and reasons shown as the operator's words
- [X] T056 [US5] Create `apps/ai-control/resources/views/filament/resources/incidents/standing-notices.blade.php` — the standing sentence (P4, verbatim from `live-attention-queue.blade.php`), the bot-not-administrator notice (P5) and the channel-sender notice (P6) — and include it on the view page and beneath the list (FR-033, FR-070, FR-071, D-TG-127)
- [X] T057 [US5] In `Tables/IncidentsTable.php`, add the filters (status from the view, category, severity, group, responsible moderator, detection date range) and the "Age / took" column (`now() − detected_at` while open or acknowledged, `resolved_at − detected_at` once resolved, "acted before flagging" when negative), computed server-side (FR-067)

**Checkpoint**: open any incident and read, on one screen, what was posted, when each step happened, who
did what, how long each step took, and whether it was withdrawn — beneath the sentence that Telegram does
not report deletion.

---

## Phase 8: User Story 6 — Three timings, separately named, and handled versus missed, all reproducible by hand (Priority: P6)

**Goal**: Per group and per moderator for a period: outcomes, handled share, the three timings with their
samples and "acted before flagging", and detection latency as a system figure — all from the quoted SQL.

**Independent Test**: Load a fixed fixture — one, two and three kinds of evidence, pre-flag evidence, a
late resolution, a false positive, an unassigned incident, a group below the floor — and compare every
figure against hand computation.

**Depends on**: Phase 2 for the Python arithmetic; US1 for the page the table renders on.

### Tests for User Story 6

- [X] T058 [P] [US6] `apps/ai-api/tests/moderation/incidents/test_metrics.py` — incidents built directly with `detected_at` placed relative to the database's real `now()` (the SQL reads `now()`; place "settled" incidents days in the past and "within window" ones minutes ago); assert against hand-computed values: `handled + missed + within_window + false_positive = flagged`; a resolution thirty hours after flagging under a 24 h ceiling is **missed** while its state is resolved, and recomputing yields the same counts (SC-024); resolution evidence *dated* inside the window but inserted afterwards → handled (M10); `acknowledged_not_handled` counts only unhandled incidents acknowledged by the ceiling; handled share excludes within-window and false positives; each timing's median/p90/max and `*_samples`; pre-flag evidence lands in `*_before_flagging` and in no percentile, with no negative value anywhere (SC-023); p90 withheld per timing on its **own** sample count below 10; false positives absent from outcomes and timings but present in detection latency; the latency function takes no moderator argument; zero rows → NULL, never 0; selection by `detected_at`, boundary inclusive/exclusive; per-moderator figures follow `responsible_moderator_id`, never the actor (FR-050, FR-051…FR-066, SC-009…SC-011)
- [X] T059 [P] [US6] `apps/ai-control/tests/Feature/IncidentMetricsTest.php` — the figures table renders the same numbers as the Python statements over the same seed; the suppression reason renders as *"Fewer than N samples (n=k)"*; NULL renders "no data"; a zero denominator renders the handled share as "—"; moderator rows have no detection-latency column; the rendered page contains none of `average`, `avg`, `score` (FR-063, FR-065, SC-014)

### Implementation for User Story 6

- [X] T060 [US6] Add `incident_outcome_stats`, `incident_timing_stats` and `detection_latency_stats` to `apps/ai-api/app/application/moderation/metrics.py` — the three statements of `contracts/incident-metrics.md` §2–§4 **quoted verbatim** as `sa.text` constants with typed bind params, explicit keyword arguments (`period_from`, `period_to`, `max_age_s`, `min_samples`, `moderator_id`, `chat_id` — and **no** `moderator_id` on the latency function), p90 suppression applied per timing on its own count, handled share computed from the outcome row. No `avg(` anywhere (D-TG-118…D-TG-121)
- [X] T061 [US6] Create `apps/ai-control/app/Filament/Resources/Incidents/Concerns/IncidentMetrics.php` — the same three statements quoted once, with the same parameters, the ceiling from `config('moderation.incident_max_age_s')` and the floor from `config('moderation.percentile_min_samples')`; display helpers for durations, suppression and shares mirroring `AttentionMetrics`
- [X] T062 [US6] Add the figures table to `Pages/ListIncidents.php` with a view under `resources/views/filament/resources/incidents/` — a period filter in `Asia/Riyadh` calendar days converted once to a half-open UTC bound (TG-M3's `periodBounds()` pattern); one row per group and one per responsible moderator with any incident flagged in the period, plus a total detection-latency row; columns per `control-panel-incidents.md` §4; moderator rows omit detection latency (D-TG-124)

**Checkpoint**: the operator's hand-computed figures and the screen agree — for all three timings, the
outcomes, and the latency — and nothing on the page is an average.

---

## Phase 9: Polish & Cross-Cutting Concerns

- [X] T063 [P] `apps/ai-api/tests/moderation/incidents/test_rederive_evidence.py` — captured `chat_member` and `message_reaction` events for a chat, marked processed before this milestone's code ran: ordinary processing does not revisit them (FR-083); `rederive_chat_evidence` records their evidence and reports `recorded` and `incidents_changed` from the state view before/after; a second run reports zeros and changes nothing; no incident, label or panel act is created, altered or removed (FR-084, FR-085, SC-019)
- [X] T064 Add `rederive_chat_evidence(session_factory, *, chat_id, since, until)` and the `--with-evidence` flag (default off) to `apps/ai-api/app/scripts/rederive_chat.py` — walks the chat's captured `chat_member` and `message_reaction` events in `update_id` order through the **same** `derive_membership_evidence` / `derive_reaction_evidence` `process_update` calls; skips purged payloads; prints `evidence: recorded=<n> incidents_changed=<n>`; refuses an unmeasured chat as the existing command does (D-TG-128, lifecycle contract R3–R5)
- [X] T065 [P] `apps/ai-api/tests/moderation/incidents/test_attention_unaffected.py` — over one seeded traffic set, every TG-M3 figure (`first_response_time_stats`, `unanswered_stats`, `oldest_waiting`, `accuracy_by_rule_version`) is identical before and after this milestone's evidence and incidents are added; a moderator's reaction on a waiting question still closes nothing; opening an incident on an item's anchor leaves the item byte-identical (FR-086, SC-016)
- [X] T066 [P] Extend `apps/ai-api/tests/moderation/ingest/test_no_outbound.py`'s `_FORBIDDEN_METHODS` with `unbanChatMember`, `banChatSenderChat` and `unbanChatSenderChat`, and confirm the scan still covers `apps/ai-control/app` and its views, so the Incidents resource is inside it (FR-078, FR-079, SC-022)
- [X] T067 [P] Extend `apps/ai-api/tests/moderation/test_boundary_checks.py` — `app/domain/moderation/incident.py` imports nothing outside the domain layer and the standard library; no Telegram-client or model import appears in `evidence.py`, `incidents.py` or the new metrics functions (FR-080)
- [X] T068 [P] Run `scripts/check.sh` check 4 against the new and edited modules and confirm no `logger.*()` line mentions a text column; confirm `open_incident` and the evidence derivations log only whitelisted keys (`incident_id`, `message_id`, `update_id`, `chat_id`) (FR-081, SC-021)
- [X] T069 Add two additive correction notes to `docs/plan/telegram/telegram-moderation-intelligence.md`, in the same form as §17's existing "**Correction (TG-M2, research Finding 1).**" paragraph: under §10.8 — "**Correction (TG-M4, research Finding 3).**" the `status` and `acknowledged_*` / `resolved_*` / `closed_*` fields are columns of the `moderation_incident_state` view derived from `moderation_actions`, not table columns, and the anchor is `UNIQUE (telegram_chat_id, telegram_message_id)`; under §10.9 — `unban` is recorded as `reversal` with no strength, `dismiss_false_positive` carries no strength, and the member-removal kind is named `expulsion`. **Operator item 1 — approved.** Change no other text in the plan
- [X] T070 Update `docs/runbooks/tg-operator-prerequisites.md` §C's TG-M4 row only if its smoke-test wording has drifted from `quickstart.md` §4–§5 — in particular, add "first confirm a `chat_member` and a `message_reaction` row landed" (research Finding 4). Leave it unedited if it already matches. SC-001 is the operator's own run of that smoke test (quickstart §5), not an automated task
- [X] T071 Run `make check` from the repository root with **Ollama quit and no `TELEGRAM_BOT_TOKEN` set** and confirm it passes offline (FR-087, SC-020)

---

## Dependencies & Execution Order

### Phase Dependencies

```
Phase 1 (Setup)
   └─▶ Phase 2 (Foundational)  ── BLOCKING ──┐
                                             │
        ┌──────────────────┬─────────────────┼──────────────────┐
        ▼                  ▼                 ▼                  ▼
   Phase 3 — US1 🎯    Phase 4 — US2    Phase 5 — US3      (Python halves of
   (open; panel)       (acknowledge)    (enforce)           US4 T048, US6 T058/T060)
        │                  └──── shared files: run US2 before US3 ────┘
        ├──▶ Phase 6 — US4  (actions live on US1's list)
        │         │
        ├──▶ Phase 7 — US5  (US1's resource; reuses US4's actions)
        │
        └──▶ Phase 8 — US6  (US1's page for the table)
                                   │
                                   └──▶ Phase 9 (Polish)
```

### User Story Dependencies

- **US1** depends only on Phase 2. It is the MVP.
- **US2** and **US3** depend only on Phase 2 — their tests build incidents directly through `conftest.py`
  — but they edit the same three files (`domain/incident.py`, `evidence.py`, `process_update.py`), so run
  US2's T034–T036 before US3's T044–T046, or accept one merge per file.
- **US4** depends on US1 for its panel half; its Python test (T048) needs Phase 2 only.
- **US5** depends on US1 and reuses US4's action classes.
- **US6**'s arithmetic (T058, T060) needs Phase 2 only; its panel half (T059, T061, T062) needs US1.

### Within Each Story

Tests first, then the pure domain function, then the application layer, then the dispatch, then the
panel. Panel tasks follow the Python side within a story.

### Parallel Opportunities

- **Phase 1**: T001–T007 are all `[P]`.
- **Phase 2**: T011–T018 are `[P]` once T008–T010 land.
- **Every story's test block is fully parallel** — separate files, fixtures only in `conftest.py`.
- **US1's panel work and US2's Python work are parallel** once Phase 2 is done; so are US6's arithmetic
  (T058, T060) and anything on the panel side.
- **Phase 9**: T063, T065–T068 are `[P]`; T064 follows T063's red; T069–T071 are last and sequential.

## Parallel Example: Foundational

```
After T008–T010 (schema, views, migration — in sequence):
  T011  test_migration_0006.py
  T012  test_db_invariants.py
  T013  incident_lock in locks.py
  T014  incidents.py readers
  T015  domain/incident.py vocabularies
  T016  ModerationIncident.php
  T017  ModerationAction.php
  T018  ModerationActionImmutabilityTest.php
        — eight files, no shared edits
```

## Parallel Example: after Phase 2

```
  Agent A → Phase 3 (US1)   messages.py fix, open_incident, the panel resource + queue row action
  Agent B → Phase 4 (US2), then Phase 5 (US3)   domain/incident.py, evidence.py, process_update.py
  Agent C → US6 arithmetic  test_metrics.py (T058) + metrics.py (T060) — reads the views only

  ⚠ A touches messages.py; B touches process_update.py and evidence.py. No file is shared between A and B.
     C touches metrics.py only.
```

## Implementation Strategy

### MVP first (US1 only)

Phases 1–3 deliver a real slice: an operator flags a message from either screen, and the incident
exists with both moments, its labels and the owner at the flag — and channel spam can finally be stored.
The status reads **open** and nothing moves it yet, but the subject of every later measurement is
correct, unique per message across groups, and immune to later reassignment. **Stop here and the
milestone is still worth having.**

### Incremental delivery

1. **Phases 1–3** → incidents open correctly. Demo: flag a message; see it on the list.
2. **+ Phase 4** → a ✅ is recorded and never resolves. Demo: runbook smoke step 3.
3. **+ Phase 5** → enforcement resolves, across a promotion. Demo: runbook smoke step 4 — the
   milestone's core claim, provable from here.
4. **+ Phase 6** → the operator can confirm a silent deletion on a moderator's word and withdraw a false
   flag.
5. **+ Phase 7** → the six questions on one screen, with the standing sentence.
6. **+ Phase 8** → the acceptance: hand-computed timings match the screen.
7. **+ Phase 9** → re-derivation, TG-M3 untouched, silence and boundary guarantees, the plan's
   corrections.

### Suggested MVP scope

**Phases 1, 2 and 3** — 29 tasks. The checkpoint is real: flag a message in the dev group and confirm
one incident with `opened_at` equal to the message's own send time, `detected_at` equal to the flag, and
the moderator who owned the group at the flag.

## Notes

- **Tests are required here**, per Principle I and `plan.md`'s enumeration. Five of them — **T005,
  T022, T038, T041, T048** — exist because a finding or probe proved the obvious test passes while the
  code is broken. Those are the ones not to skip when time runs short.
- **Tests read the views; they never compute a state.** An expectation computed by test code is a second
  definition of the lifecycle and will drift with it (lifecycle contract N6).
- **The clock never enters a stored moment except `detected_at` and panel acts.** Every other moment is
  the platform's `date` or `sent_at`. The figure SQL reads the database's `now()` for "missed" and
  "within window" only; tests place incidents relative to it rather than faking it.
- **Operator step, not a task:** add `MODERATION_PERCENTILE_MIN_SAMPLES=10` and
  `MODERATION_INCIDENT_MAX_AGE_S=86400` to `.env` (quickstart §2). `.env` is the operator's file.
- **No Git action appears in any task** (Principle IV). The branch exists; committing, merging and
  tagging are the operator's.
- **The TG-M3 hand-open lookback gap** (`plan.md`, "Recorded, not fixed") has **no** task here — it is a
  TG-M3 follow-up, out of this milestone's scope (Principle V).
- **Nothing here reads or writes `injazedu/`** (Principle III), and no test touches a database whose name
  lacks `_test` (Principle II).
