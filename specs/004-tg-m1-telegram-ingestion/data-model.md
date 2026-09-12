# Phase 1 Data Model: TG-M1 — Telegram Event Ingestion

**Feature**: `specs/004-tg-m1-telegram-ingestion` · **Date**: 2026-09-09
**Revision**: `0003_moderation_ingest` — the first of the block `0003`–`0009` reserved for this domain
**Conventions inherited from `0002_model_gateway`**: SQLAlchemy Core `Table` objects on the same
`metadata`, `BIGINT` identity primary keys, `TIMESTAMPTZ` with `server_default=now()`, hand-written
Alembic revisions, explicit `uq_` / `ck_` / `ix_` names, invariants pushed into the database rather
than remembered by a caller.

Four tables. `payload_purged_at` and the retention shape are here so TG-M10 can purge without a
migration; nothing in TG-M1 purges anything.

---

## 0. Where the tables live, and why that matters

`apps/ai-api/app/infrastructure/models_moderation.py`, importing `metadata` from
`app/infrastructure/models.py` — the source plan's §23 "new sibling on the same metadata".

`app/infrastructure/` is **not** inside the boundary gate's reverse-check scope (which covers
`app/domain`, `app/application`, `app/providers`, `app/api`), and `app.infrastructure` is one of the
seven prefixes a moderation module is permitted to import. So this file is shared infrastructure by
both the gate's definition and the contract's — the same status `models.py` already has. Probe 4
confirmed the corollary: a module under `app/application/probes/` reading these tables **fails the
gate**, which is what drives D-TG-31.

---

## 1. `telegram_updates` — the append-only spine

Everything the domain will ever report is a function of this table. Written once; the only fields
that ever change afterwards are the three marked **mutable**.

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | `BIGINT` identity PK | no | |
| `bot_id` | `BIGINT` | no | Telegram's numeric bot id, from `getMe` (D-TG-42). Scopes everything, so a second bot is possible later without reinterpreting stored rows |
| `update_id` | `BIGINT` | no | Telegram's own, monotonic per bot — **except after a reset**, see §2 and D-TG-33 |
| `update_type` | `VARCHAR(40)` | no | `message` \| `edited_message` \| `my_chat_member` \| `chat_member` \| `message_reaction` \| `callback_query` \| `unknown` |
| `chat_id` | `BIGINT` | **yes** | Extracted for routing only. NULL for updates carrying no chat (FR-012) |
| `payload` | `JSONB` | no | The complete update. Semantically complete, **not byte-identical** — D-TG-35 |
| `received_at` | `TIMESTAMPTZ` | no | `server_default=now()`. When *we* stored it — never used for ordering or measurement (FR-013) |
| `processed_at` | `TIMESTAMPTZ` | yes | **mutable.** NULL = pending. The only marker TG-M1's interpreting step writes |
| `process_error` | `TEXT` | yes | **mutable.** Last failure reason; no message text |
| `payload_purged_at` | `TIMESTAMPTZ` | yes | **mutable.** Set by TG-M10's purge when `payload` is nulled. Shape only in TG-M1 |

**Constraints and indexes**

| Name | Definition | Why |
|---|---|---|
| `uq_telegram_updates_bot_update` | `UNIQUE (bot_id, update_id)` | The idempotency key. FR-045 makes this the database's job, not the application's. Probe 1 |
| `ck_telegram_updates_type` | `CHECK (update_type IN (…7 values…))` | A typo becomes an error, not a silently unroutable row |
| `ix_telegram_updates_pending` | `(received_at) WHERE processed_at IS NULL` | The work queue for FR-020's drain. Probe 8 confirms the index is used and stays tiny — it indexes only the backlog |
| `ix_telegram_updates_chat_received` | `(chat_id, received_at DESC)` | The operator's `make psql` question: "what happened in this group?" |

**Idempotency.** One statement per batch:
`INSERT … VALUES (…),(…) ON CONFLICT (bot_id, update_id) DO NOTHING RETURNING id, update_id`.
Interpretation is scheduled only for returned rows, after commit (D-TG-30, D-TG-36).

**Append-only, enforced by convention plus review.** No trigger blocks an `UPDATE` of `payload`;
adding one was considered and left out as unearned — the contract states the rule, the code has one
write path, and Principle I does not spend a trigger on a rule with a single call site.

⚠ **Known limitation (D-TG-34).** After an identifier reset, a genuinely new event whose random
`update_id` collides with a stored one is silently dropped by `ON CONFLICT`. Accepted deliberately;
every reset writes a gap row so the exposure window is visible.

---

## 2. `ingestion_state` — one row per bot

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | `BIGINT` identity PK | no | |
| `bot_id` | `BIGINT` | no | `UNIQUE` — one row per bot |
| `bot_username` | `VARCHAR(100)` | yes | From `getMe`; operator-facing only |
| `last_update_id` | `BIGINT` | yes | The confirmed position. NULL before the first event |
| `last_poll_at` | `TIMESTAMPTZ` | yes | Every poll, success or not |
| `last_success_at` | `TIMESTAMPTZ` | yes | Successful polls only — the input to downtime detection |
| `last_event_at` | `TIMESTAMPTZ` | yes | Last time a poll actually **returned** an event. Distinct from `last_success_at`, and the input to the §0 stall detector |
| `consecutive_failures` | `INTEGER` | no | `server_default 0`. Any poll failure |
| `consecutive_conflicts` | `INTEGER` | no | `server_default 0`. `409` only; reset by any successful poll (FR-004b) |
| `stood_down_at` | `TIMESTAMPTZ` | yes | Non-NULL = stopped polling after the conflict threshold (FR-004a). Cleared only by an explicit restart |
| `allowed_updates` | `JSONB` | no | The subscription set as last asserted (FR-006) |
| `updated_at` | `TIMESTAMPTZ` | no | `server_default=now()` |

**Why `last_event_at` is separate from `last_success_at`.** A poll that succeeds and returns nothing
is the normal case; a *week* of them is the reset condition (D-TG-33). Collapsing the two would make
the stall undetectable — the exact silent failure Finding 1 describes.

**The position, stated as an invariant.** `last_update_id` is advanced only after the batch's insert
has committed, and only as far as the highest **successfully stored** identifier (FR-016). It moves
backwards in exactly one case: an identifier reset, recorded as a gap row first (FR-019's one
documented exception).

---

## 3. `ingestion_gaps` — why the reports can be honest

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | `BIGINT` identity PK | no | |
| `bot_id` | `BIGINT` | no | |
| `gap_start_at` | `TIMESTAMPTZ` | no | |
| `gap_end_at` | `TIMESTAMPTZ` | yes | NULL while still open |
| `reason` | `VARCHAR(30)` | no | see below |
| `unrecoverable` | `BOOLEAN` | no | `server_default false`. True once the window exceeds the platform's 24 h retention (FR-023) |
| `detected_at` | `TIMESTAMPTZ` | no | `server_default=now()` |
| `note` | `TEXT` | yes | Operator-readable; no message text |

**`ck_ingestion_gaps_reason`** — `CHECK (reason IN ('downtime', 'update_id_jump', 'conflict_409', 'unrecoverable_24h', 'update_id_reset'))`

Five reasons, one more than the source plan's four. **`update_id_reset` is not a loss** (D-TG-33):
Telegram renumbered after a week of silence and nothing went missing. It is recorded because the
operator needs to see when it happened — and, given D-TG-34, when the collision-exposure window
opened — but a report overlapping it must **not** be marked incomplete. That distinction is the
column `unrecoverable` plus the reason, and it is a contract test.

| Reason | Written when | `unrecoverable` |
|---|---|---|
| `downtime` | Restart, and the silence since `last_success_at` exceeded the 5-minute minimum (FR-025) | only if > 24 h |
| `update_id_jump` | Next identifier exceeds `last_update_id + 1` **and** the silence was under a week | yes — those events are gone |
| `conflict_409` | The stand-down threshold was reached (FR-004a) | only if > 24 h |
| `unrecoverable_24h` | Any window longer than the platform's retention | always |
| `update_id_reset` | Stall detected, re-synced with no offset (D-TG-33) | **never** — nothing was lost |

**Index.** `ix_ingestion_gaps_window (bot_id, gap_start_at DESC)` — TG-M7 asks "does this report's
window overlap a gap?", which is a range scan per bot.

**Never silently deleted or merged** (FR-021). Two adjacent downtime windows stay two rows.

---

## 4. `telegram_chats` — discovered, then deliberately opted in

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | `BIGINT` identity PK | no | |
| `chat_id` | `BIGINT` | no | `UNIQUE`. Negative for groups and supergroups (probe 2c) |
| `chat_type` | `VARCHAR(20)` | no | `group` \| `supergroup` \| `channel` \| `private` \| `unknown` |
| `title` | `VARCHAR(300)` | yes | |
| `username` | `VARCHAR(100)` | yes | |
| `is_monitored` | `BOOLEAN` | no | `server_default false` — **the opt-in switch** (FR-030) |
| `bot_status` | `VARCHAR(20)` | no | `server_default 'unknown'`. `member` \| `administrator` \| `left` \| `kicked` \| `restricted` \| `unknown` |
| `bot_status_at` | `TIMESTAMPTZ` | yes | When the standing was last observed |
| `bot_can_delete` | `BOOLEAN` | yes | Observed only, never exercised (FR-027) |
| `migrated_to_chat_id` | `BIGINT` | yes | |
| `migrated_from_chat_id` | `BIGINT` | yes | |
| `injaz_course_id` | `BIGINT` | yes | Manual, **no FK** — MySQL is on another host. Unused until TG-M2 |
| `last_event_at` | `TIMESTAMPTZ` | yes | Feeds the health block's "silent over 6 h" count |
| `notes` | `TEXT` | yes | |
| `created_at` / `updated_at` | `TIMESTAMPTZ` | no | `server_default=now()` |

**Constraints and indexes**

| Name | Definition | Why |
|---|---|---|
| `uq_telegram_chats_chat_id` | `UNIQUE (chat_id)` | The upsert key |
| `ck_telegram_chats_bot_status` | `CHECK (bot_status IN (…6 values…))` | `unknown` is a first-class value, not a NULL — D-TG-43 |
| `ix_telegram_chats_monitored` | `(is_monitored, last_event_at)` | The health block's two questions in one index |

**Two write paths, deliberately different (D-TG-43).** Any chat-bearing update upserts identity
fields and `last_event_at`. **Only `my_chat_member`** writes `bot_status`, `bot_status_at` and
`bot_can_delete`. A chat first seen through an ordinary message therefore records
`bot_status = 'unknown'` — never a guess, because guessing `administrator` would hide precisely the
coverage failure §20.2 calls "the failure most likely to go unnoticed".

**`is_monitored` defaults false and TG-M1 ships no screen for it.** The operator flips it with one
`UPDATE` in `make psql`; the Filament resource arrives in TG-M2. Updates for un-monitored chats are
still stored (FR-031), which is what makes opting a group in retroactive within the retention window.

**Migration.** `migrate_to_chat_id` / `migrate_from_chat_id` are written on **both** rows so the pair
is navigable from either side. TG-M1 re-points no derived state because none exists (D-TG-44).

---

## 5. Value shapes that are not tables

| Shape | Where | Notes |
|---|---|---|
| `TelegramUpdate` | `app/providers/telegram/models.py` | A Pydantic model over the fields the poller must read to route a row — `update_id`, the kind, the chat id. Everything else stays in `payload`; the provider does **not** model the whole Bot API |
| `BotIdentity` | same | `bot_id`, `username` — the `getMe` result (D-TG-42) |
| `PollResult` | same | The batch plus whether the subscription set was accepted |
| `IngestionHealth` | `app/application/moderation/ingestion_probe.py` | The health block's eight fields (`contracts/health-ingestion.md` §1) |
| Redis `ai:tg:poll:lease` | Redis | A **lock, never a fact** (§7.3). Fencing-token pattern reused from `gateway/lanes.py` |

---

## 6. Retention shape (consumed by TG-M10, not here)

| Data | Retention | After |
|---|---|---|
| `telegram_updates.payload` | 90 days (`MODERATION_TEXT_RETENTION_DAYS`) | nulled, `payload_purged_at` set. `update_id`, type and timestamps kept forever |
| `telegram_updates` identity/timing columns | forever | the event *history* survives when the *content* does not |
| `ingestion_state`, `ingestion_gaps` | forever | small, and a gap is a permanent fact about a reporting window |
| `telegram_chats` | forever | operator-managed |

TG-M1 writes `payload_purged_at` nowhere. Its only obligation is that nulling `payload` later must
leave every other column meaningful — which the table shape above satisfies (FR-014).

---

## 7. Requirement coverage

| Requirement | Where |
|---|---|
| FR-008, FR-012, FR-013 | §1 columns; `chat_id` nullable; `received_at` separate from the platform's own timestamp |
| FR-009, FR-014 | §1 mutable-field list; §6 |
| FR-010, FR-011, FR-045 | `uq_telegram_updates_bot_update` + the `RETURNING` insert (probe 1) |
| FR-015, FR-016, FR-017, FR-018 | §2, and the position invariant |
| FR-019 | §2's one documented exception + §3's `update_id_reset` |
| FR-020 | `ix_telegram_updates_pending` (probe 8) |
| FR-021…FR-025 | §3 in full |
| FR-026…FR-031 | §4 in full |
| FR-032, FR-033 | `processed_at` is the only field TG-M1's interpreting step writes; setting it twice is the same result |
| FR-044 | Revision `0003`, head confirmed free by probe 10 |
