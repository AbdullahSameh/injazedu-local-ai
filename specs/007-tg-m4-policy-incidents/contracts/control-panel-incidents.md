# Contract: Control Panel — Incidents

**Feature**: `specs/007-tg-m4-policy-incidents` · **Status**: durable from TG-M4 onwards

One new resource in the existing **Moderation Intelligence** navigation group, beside TG-M2's Telegram
Groups and Moderators and TG-M3's Live Attention Queue — plus one row action on that queue. Filament
v5.7.8, Laravel 12.69.1.

---

## §1 — The resource

`IncidentResource` with a **List** page and a **View** page. No create, edit or delete page: an incident
is opened by an action, its labels are never edited, and it is never deleted (D-TG-123).

### §1.1 List

| Column | Source | Notes |
|---|---|---|
| Group | `telegram_chats.title` | `dir="auto"` |
| Message | anchor's `original_text`, truncated | `dir="auto"`; "Text removed" when purged |
| Category · Severity | `moderation_incidents` | operator-assigned |
| Status | `moderation_incident_state.status` | read from the view — the panel computes no state |
| Responsible | `moderators.display_name` | **Unassigned** badge when NULL — never blank |
| Posted · Flagged | `opened_at`, `detected_at` | `Asia/Riyadh`, human format |
| Age / took | `now() − detected_at` while open or acknowledged; `resolved_at − detected_at` once resolved | server-side, human units; "acted before flagging" when negative |

- **P1.** Default order `detected_at DESC`. Filters: status, category, severity, group, responsible
  moderator, detection date range (FR-067).
- **P2.** Header action **Open incident** (§2). **No bulk action anywhere** (FR-038).
- **P3.** Beneath the table, the figures (§4).

### §1.2 View — the six questions (FR-068)

| Question | Content |
|---|---|
| What was posted | anchor text (`dir="auto"`) or "Text removed"; `media_kind`; `entity_flags` |
| When | posted · flagged · first acknowledgement · resolved or closed — each "—" when absent |
| Why flagged | opened by (panel account) · category · severity · "operator-assigned" · **"No model classification — arrives with TG-M5"** (FR-077) |
| Who handled it | the evidence trail (§1.3) and the resolution's actor per A3 of the lifecycle contract |
| How long | acknowledgement time · handling-confirmation time · observed-enforcement time — each a duration, "acted before flagging", or "no evidence"; and detection latency, labelled as a system figure |
| Corrected? | false-positive closure: when, by whom, the reason — or "not closed as a false positive". Label review arrives with TG-M8 |

Plus the outcome (handled / missed / within window / false positive) against the ceiling.

### §1.3 The evidence trail (FR-069)

Every row of `moderation_incident_evidence` for this incident, ordered `(occurred_at, source_rank,
evidence_id)`: kind · strength (or "no effect" for a reversal) · actor (moderator name, the platform's
name for an unmapped performer, "anonymous administrator", or the panel account) · affected member for
membership kinds · moment · captured event id (`source_update_id`) or "panel". Notes and reasons are
shown as the operator's words.

### §1.4 Standing notices

- **P4.** Always, on the view page and beneath the list: *"Telegram does not report message deletion in
  groups; no removal evidence is available."* — the exact sentence TG-M3's queue already carries
  (FR-070).
- **P5.** When `telegram_chats.bot_status <> 'administrator'`: *"The bot is not currently an
  administrator in this group, so reactions and membership changes there cannot be observed."*
  (FR-071, D-TG-127).
- **P6.** When the anchor has `sender_chat_id` and no `telegram_user_id`: *"This message was sent on
  behalf of a channel or the group itself. No membership evidence can arrive for it; it can only be
  resolved by confirmation."* (FR-033).

---

## §2 — Opening an incident

Two entry points, one method: `ModerationIncident::openOn(TelegramMessage $message, string $category,
string $severity, User $by)`.

| Entry | Form |
|---|---|
| Incidents list → header action **Open incident** | message picker + category + severity |
| Live Attention Queue → row action **Open incident** (FR-072) | category + severity; the message is the item's anchor |

- **P7.** The picker lists recent messages in measured groups that are **not** service messages and do
  **not** already anchor an incident — excluded by the composite `(telegram_chat_id, message_id)`, never
  `message_id` alone. A validation rule re-checks both at submit; `uq_incident_anchor` is the backstop.
- **P8.** Category and severity are required selects with exactly the values of `ck_incident_category`
  and `ck_incident_severity`.
- **P9.** `openOn` writes `opened_at` from the message's `sent_at`, `detected_at` as the database's
  `now()`, `source = 'operator'`, `opened_by_user_id`, and `responsible_moderator_id` from TG-M2's
  `responsibleAt` scope **at `detected_at`**. It writes nothing else and touches no attention item.

---

## §3 — Acting on an incident

View-page actions, shown only when the lifecycle contract's H1 allows them for the incident's current
status:

| Action | Method | Form |
|---|---|---|
| Acknowledge | `ModerationIncident::acknowledge(User)` | confirmation |
| Resolve | `ModerationIncident::resolve(User, string $note)` | required note — helper text: *"Record what you were told or saw. This is recorded as your confirmation, not as something Telegram reported."* |
| Not a violation | `ModerationIncident::closeAsFalsePositive(User, string $reason)` | required reason |

- **P10.** Each method is the guarded insert of the lifecycle contract §5: lock, read status from the
  view, insert or do nothing. A stale page or a double click inserts nothing.
- **P11.** `ModerationAction` refuses `update()` and `delete()` from its model events (D-TG-113).
- **P12.** No action posts, bans, restricts, deletes, reacts, calls a model, or runs a bulk job
  (FR-073).

---

## §4 — The figures

A table on the list page, per group and per moderator, for a period filter in `Asia/Riyadh` calendar
days converted once to a half-open UTC bound (TG-M3's `periodBounds()` pattern).

| Column | Statement |
|---|---|
| Flagged · Handled · Missed · Within window · False positive | `incident-metrics.md` §2 |
| Acknowledged, not handled | §2 M8 |
| Handled share | §2 M9 — "—" when the denominator is zero |
| For each of the three timings: median · p90 (or the suppression reason) · max · samples · acted before flagging | §3 |
| Detection latency (group rows and total only) | §4 |

- **P13.** Every number is the quoted SQL; the panel defines no arithmetic of its own (FR-066).
- **P14.** NULL renders "no data", never "0s"; p90 below the floor renders
  *"Fewer than N samples (n=k)"*.
- **P15.** The moderator rows have **no** detection-latency column (FR-054).
- **P16.** Not a second navigation entry — TG-M7 owns the dashboard (D-TG-124).

---

## §5 — Wording (FR-020, SC-013)

- **P17.** No label, column, action, helper text, badge or figure on these screens contains a word that
  implies a deletion was observed. `IncidentWordingTest` renders the list and a view page, removes the
  standing sentence (P4) and the retention marker "Text removed", and asserts that no `delet` or `remov`
  substring remains, case-insensitively (D-TG-126). Kind labels are fixed: `ban` → "Banned",
  `expulsion` → "Expelled from the group (not banned)", `restriction` → "Restricted", `reversal` →
  "Unban / restriction lifted — no effect", `reaction` → "Reaction", `reply` → "Direct reply",
  `panel_*` → "Acknowledged / Resolved / Not a violation (panel)". The membership kind is named
  `expulsion`, not `removal`, precisely so that this test can stay strict.
- **P18.** No average and no composite score: `IncidentMetricsTest` asserts `average`, `avg` and
  `score` are absent from the rendered page, mirroring TG-M3's D-TG-92.

---

## §6 — Configuration

| Key | `config/moderation.php` | Compose (`ai-control`) |
|---|---|---|
| `MODERATION_PERCENTILE_MIN_SAMPLES` | `percentile_min_samples`, **blank-safe**, default 10 | `${MODERATION_PERCENTILE_MIN_SAMPLES:-10}` |
| `MODERATION_INCIDENT_MAX_AGE_S` | `incident_max_age_s`, blank-safe, default 86400 | `${MODERATION_INCIDENT_MAX_AGE_S:-86400}` |

- **P19.** "Blank-safe" means an empty string reads as unset: `filled($v) ? (int) $v : $default`.
  `ModerationConfigTest` pins the empty-string case for both keys (research Finding 2).

---

## §7 — What the panel may not do

- **No migration.** Alembic owns the schema (`0006`); the panel owns none of it.
- **No state computation.** Status, moments and timings are read from the two views; a PHP `match` over
  evidence rows would be a second definition (lifecycle contract N6).
- **No model call, no Telegram call, no outbound message.**
- **No bulk action, no backfill control.** Re-derivation stays on the operator's command line.
- **No write to `moderation_actions` except through the three guarded methods**, and never an update or
  delete.
- **No write to any TG-M2 or TG-M3 column**, and no change to the queue beyond the one row action.
- **No `RefreshDatabase`, `DatabaseMigrations` or `migrate:fresh`** in any test — `DatabaseTransactions`
  against `injaz_ai_test`.

---

## §8 — Access

**P20.** `ai_control` reaches both tables and both views with no `GRANT` (research probe 6) and may take
the advisory lock (probe 7).
