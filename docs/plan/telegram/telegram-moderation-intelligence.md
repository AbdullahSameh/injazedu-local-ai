# Telegram Moderation Intelligence — Implementation Plan

**Status**: planning only — no code, no migrations, no branches, no changes to existing specs.
**Repo**: `/Users/abdullah/Projects/injazedu-local-ai` @ `182bfb1` (clean, M0 + M1 merged)
**Date**: 2026-09-08

---

## Context

InjazEdu runs student communities on Telegram. Roughly five moderators each own several groups.
Nobody can currently answer, with evidence, *how long a student waited for an answer* or *how long a
policy-violating message stayed visible*. The existing Local AI platform (M0 foundation + M1 model
gateway) already provides everything a measurement system needs — Postgres, Redis, a Dramatiq worker,
a provider-isolated model gateway, and a Filament control panel — but nothing in it touches Telegram.

This plan adds **Moderation Intelligence** as a second bounded domain beside the existing
**Assessment Intelligence** domain, sharing infrastructure and sharing nothing else. It is built
deterministically first: response and reaction times are computed from Telegram facts and database
state, never from an LLM. The LLM is added later and only for *semantic* judgements — "is this a
question", "is this an advert" — which is the only place it has an advantage.

The plan is deliberately sequenced so the first shippable slice contains **no AI at all**.

---

## 1. Executive Summary

**What we build.** A silent Telegram bot feeds an append-only event log in the AI Postgres. A
deterministic worker turns those raw facts into *attention items* (a student message that needs a
reply) and *incidents* (a message that needs moderator action), tracks who was responsible at the
time, and measures how long each took to resolve. Filament gets a new **Moderation Intelligence**
navigation group. Local AI classifies messages only after the deterministic spine is proven.

**The eight decisions that shape everything else:**

| #          | Decision                                                                                                                                                                                                                          | Short reason                                                                                                                                            |
| ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| D‑TG‑01    | **Ingestion is a dedicated `ai-telegram` long-polling process** inside `apps/ai-api`, not n8n, not a webhook                                                                                                                      | The AI box is behind NAT and architecture rule §5.1‑5 says outbound-only. `getUpdates` is outbound. A webhook needs a public HTTPS host we do not have. |
| D‑TG‑02    | Raw updates are **append-only and immutable**; all derived state is rebuildable from them                                                                                                                                         | Makes reprocessing after a taxonomy or model change possible without destroying history.                                                                |
| D‑TG‑03    | v1 model is **message → attention item**, with a cheap *burst* grouping rule. No `conversations` table in v1                                                                                                                      | Conversation modelling is the biggest over-engineering risk; a 90-second same-sender burst covers the observed case.                                    |
| D‑TG‑05    | "Needs response" is **deterministic in v1** (operator/rule-marked), AI-proposed from TG‑M5                                                                                                                                        | Proves the metric before adding a source of error to it.                                                                                                |
| D‑TG‑07    | Telegram **cannot** report message deletions or who deleted them. Moderation completion is detected from **ban/restrict `chat_member` updates (attributable), moderator replies, moderator ✅ reactions, and Filament resolution** | Verified against the official Bot API; see §5.                                                                                                          |
| D‑TG‑09    | Alerts go to a **private moderators' Telegram group** via n8n, plus a Filament queue. Never into a student group                                                                                                                  | Preserves the "operationally silent" requirement.                                                                                                       |
| D‑TG‑12/13 | **No pgvector, no RAG** in this domain in v1                                                                                                                                                                                      | Classification of a 200-character message needs neither.                                                                                                |
| D‑TG‑14    | **A new `role='moderation'` model profile**, added to the existing `model_profiles` table                                                                                                                                         | The table already supports it; only the `role` CHECK constraint widens. No new abstraction.                                                             |

**Sequencing.** Eleven milestones, TG‑M0 … TG‑M10. The first vertical slice is TG‑M0 → TG‑M3:
one group, one moderator, real events stored, a correct first-response time visible in Filament,
**with no model involved**. AI arrives at TG‑M5.

**What this is not.** Not surveillance scoring (no composite "Ahmed = 87/100" in v1), not automatic
moderation (the bot never deletes or replies in v1 — doing so would destroy the very metric we are
building), and not a second authority over InjazEdu business data.

---

## 2. Repository Findings

### 2.1 What exists today

`apps/ai-api` (FastAPI + Dramatiq, Python 3.12, `uv`) with a clean hexagonal layering that this plan
must follow exactly:

```
app/domain/          pure frozen dataclasses, zero deps, mypy strict
app/application/     orchestration, mypy strict
app/providers/       the ONLY place httpx/ollama/openai may be imported
app/infrastructure/  config.py, db.py, models.py (SQLAlchemy Core), queue.py, redis.py, logging.py
app/api/v1/          FastAPI routers
app/workers/tasks/   Dramatiq actors
app/scripts/         operator CLIs, `python -m app.scripts.<x>`
```

Concrete facts that constrain the design:

- **Tables that exist:** `users`, `model_profiles`, `model_runs`. Alembic revisions `0001_baseline`,
  `0002_model_gateway`. Nothing else — no documents, chunks, embeddings, jobs, or prompt_versions.
- **Schema style:** SQLAlchemy **Core `Table`** objects on a bare `MetaData()` in
  `app/infrastructure/models.py` — no declarative base, no ORM classes, no mixins. `BIGINT` identity
  PKs everywhere (no UUIDs). All timestamps `TIMESTAMPTZ` with `server_default=now()`. Constraint
  names spelled explicitly (`uq_`, `ck_`, `ix_`). Migrations are **hand-written**;
  `target_metadata = None`, autogenerate is not wired.
- **Model gateway** (`app/application/gateway/`): `Gateway.generate_structured()` takes a Pydantic
  `schema_model`, sends it as OpenAI `response_format.json_schema` with `strict: true`, checks
  `finish_reason == "stop"` **before** parsing, and raises from a closed 10-class taxonomy whose base
  carries `retryable: bool`. Execution is: resolve active profile (30 s cache) → circuit breaker →
  **machine-wide Redis lease lane** (`ai:gw:lane:llm:lease`, `SET … PX … NX`, 30 s TTL, 10 s
  watchdog renew, fencing by holder id) → up to 3 attempts with full-jitter backoff → always release
  → write a `model_runs` row on its own session, failures swallowed.
- **`model_profiles`** enforces `role IN ('llm','embedding')` by CHECK and *exactly one active
  profile per role* by the partial unique index `uq_model_profiles_one_active_per_role`.
- **Worker:** Dramatiq + `RedisBroker`, two processes × four threads. Exactly **one** actor exists
  (`ping`). **No retry policy is configured anywhere. No scheduler/cron exists.**
- **API:** four routes (`/health/live`, `/health`, `/v1/diagnostics/ping`, `…/{nonce}`).
  **No authentication of any kind, no CORS, no rate limiting, no exception handlers.**
- **Logging:** stdlib `JsonFormatter` emitting exactly four keys. **`extra={}` is silently dropped**
  and there are **no correlation IDs**. No metrics, no OpenTelemetry, no `/metrics`.
- **Architecture gate:** `scripts/check.sh` greps for `import httpx|ollama|openai` outside
  `apps/ai-api/app/providers/` with a three-file allowlist, and for embedding prefix literals. This
  is the mechanical enforcement referenced by `CLAUDE.md`.
- **Testing:** pytest with `asyncio_mode=auto` and `addopts="-m 'not llm'"`. `tests/conftest.py`
  aborts the whole session unless `TEST_DATABASE_URL` names a `_test`, local, non-`DATABASE_URL`
  database (`app/infrastructure/test_safety.py`). 99 test functions. `scripts/test_db_reset.sh` has
  its own independent `*_test*` guard.
- **`apps/ai-control`:** **Laravel 12.69 + Filament 5.7** (the master plan's "Laravel 11" is stale),
  PHP 8.2, PHPUnit 11 (not Pest). It reads the **same Postgres database and schema** as `ai-api` via
  plain Eloquent with the `ai_control` role (DML, no DDL); it makes **zero HTTP calls** to FastAPI.
  `database/migrations/` is empty by design and `DB::prohibitDestructiveCommands()` is on outside
  testing. Feature tests use `DatabaseTransactions`, never `RefreshDatabase`. Exactly **one**
  resource exists (`ModelProfileResource`) and **no navigation groups are defined**.
- **Infra:** one compose file, `infra/docker-compose.yml`: `pgvector/pgvector:pg16` (2 databases —
  `injaz_ai`, `injaz_ai_test`; 3 roles — `ai_migrator`/`ai_app`/`ai_control`), `redis:7-alpine`,
  `ai-api`, `ai-worker`, `ai-control`, `migrate` (profile `tools`), `n8n` (profile `automation`).
  Ollama runs natively on the host.

### 2.2 What is planned but does not exist

Everything Telegram- or moderation-related. `n8n` is a **bare stub**: `image: n8nio/n8n:latest`,
`mem_limit: 768m`, `depends_on: postgres` — **no ports, no volume, no environment, no encryption
key, no healthcheck**, and **zero workflow JSON files anywhere in the repo**. The master plan's
M11–M13 (Telegram notifications, scheduled drafts, customer support) are prose only.

The Filament panel has no `ar` locale, no RTL, no widgets, and none of the 18 pages in the master
plan's §14.

### 2.3 Reusable vs. accidentally coupled

| Asset                                                                                   | Verdict                                                                                                                                                                |
| --------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Gateway`, `ProfileRegistry`, lane, breaker, `AccountingWriter`, `model_runs`           | **Reuse as-is.** This is the single most valuable asset for this domain.                                                                                               |
| `FakeLLMProvider` (synthesises a schema-valid instance from the caller's model)         | **Reuse.** It is what makes AI classification testable with no Ollama.                                                                                                 |
| `app/infrastructure/{config,db,redis,queue,logging}.py`                                 | **Reuse**, with two additions (§21).                                                                                                                                   |
| SQLAlchemy Core + hand-written Alembic conventions                                      | **Reuse the convention**, new revision `0003_moderation_foundation` onwards.                                                                                           |
| Filament panel shell, `ai_control` role, `DatabaseTransactions` test pattern            | **Reuse.**                                                                                                                                                             |
| `scripts/check.sh` architecture gate                                                    | **Extend** with a Telegram-client import rule.                                                                                                                         |
| Arabic normalisation                                                                    | **Does not exist yet.** Do **not** block on M4; this domain needs a much smaller normaliser (§15.4) and should own it, then M4 can adopt or supersede it.              |
| pgvector, chunking, retrieval, `document_version_id` scoping, prompt/evidence machinery | **Do not reuse.** These are Assessment-domain concepts; importing them here is the main coupling risk.                                                                 |
| `model_runs.job_id` / `prompt_version_id` (nullable, no FK)                             | **Reuse the columns**, but do not add FKs to moderation tables — they are reserved for the assessment pipeline. Correlate via a moderation-owned column instead (§10). |

### 2.4 Conflicts and gaps this plan must resolve

1. **No inbound network path exists, and rule §5.1‑5 forbids requiring one.** Telegram webhooks need
   a public HTTPS endpoint. → drives D‑TG‑01.
2. **No scheduler exists.** SLA breach checks, escalation and daily rollups all need one. → TG‑M6
   introduces a single periodic tick (§7.4), not a general cron framework.
3. **No auth on the FastAPI surface.** The moderation domain adds the first endpoints anything
   external (n8n) will call. → a shared-secret header, defined in TG‑M7.
4. **Logging drops `extra`, so there are no correlation IDs.** Ingestion debugging is impossible
   without one. → a small, contained fix in TG‑M0 (§21).
5. **No Dramatiq retry policy.** Classification and alert delivery need one. → set per-actor in
   TG‑M5/TG‑M7, not globally.
6. **`courses.telegram_*` in InjazEdu are `VARCHAR(255)` links/usernames, not numeric chat ids.**
   A bot cannot resolve an invite link to a `chat_id`. → mapping is established when the bot joins
   (§12), and InjazEdu linkage is a later, optional, *manual* association.

---

## 3. Business Problem Restatement

For every Telegram message that requires attention: **when did it appear, was it handled, by whom,
how long did it take, and was anything missed?**

Two failure classes:

- **Slow response** — a student asks (`متى تبدأ المحاضرة؟`, `الكتاب مش ظاهر عندي`,
  `دفعت ولكن الدورة لم تظهر`) and waits. We must measure the wait objectively.
- **Unhandled violation** — spam, competitor adverts, abuse. We must measure how long it stayed
  visible and whether the responsible moderator acted.

The system is **observability plus assistance**, not a scoreboard. Its second job is to stop
moderators missing things, which is why the live attention queue and the private alert channel are
first-class and the composite score is explicitly deferred (§18.6).

---

## 4. Scope

### v1 (TG‑M0 … TG‑M8)

- Silent bot; long-poll ingestion; append-only raw event log; idempotent by `update_id`.
- Group registry, moderator registry, **time-versioned** group→moderator assignment.
- Deterministic attention items and first-response measurement.
- Policy incidents with a lifecycle, opened manually or by AI, closed by observable moderator action.
- Configurable SLA thresholds per group (with a global default); breach alerts to a private
  moderators' group and to Filament.
- Local-AI classification through the existing gateway, with a versioned prompt, a stored confidence,
  and a human-correction record that never overwrites the prediction.
- Filament: Overview, Live Attention Queue, Incidents, Groups, Moderators & Assignments,
  Classification Review, Alert Rules.
- Metrics: median / P90 / max first response, unanswered count and oldest age, moderation reaction
  time, handled vs missed — all computed in SQL from stored facts.

### Later (post-v1)

- Reprocessing UI for bulk re-classification; model A/B on moderation classification.
- Materialised daily aggregates once live SQL becomes slow (§31 — not before).
- Edited-message handling beyond storing the edit; forum-topic (`message_thread_id`) grouping;
  media/voice-note captions.
- InjazEdu course/category linkage for group-level reporting (needs an InjazEdu-side change, §24).
- WhatsApp. Any auto-moderation.

### Non-goals (explicit)

- The bot **never** posts, replies, reacts, warns, or deletes in a student group. Not in v1, not as
  a "high-confidence" exception.
- No composite employee score.
- No pgvector, no embeddings, no RAG in this domain.
- No production MySQL access, ever (constitution + §5.1‑1).
- No student-facing AI. The M13 "customer support" feature stays a separate, later track.
- No modification of `injazedu/`, and no change to the meaning of existing milestones M0–M13.

---

## 5. Telegram API Capability Review

Verified against the official Bot API reference and the bot-features page (checked 2026‑09‑08;
current version is Bot API 10.3, 2026‑08‑24). **This section is the load-bearing research: several
requested metrics are not directly obtainable and are redesigned below rather than assumed.**

### 5.1 Verified capabilities

| Capability                       | Detail                                                                                                                                                                                                                                                                                                          | Why it matters here                                                                                                                                        |
| -------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Receive every group message      | Privacy mode is on by default and limits a bot to commands and replies aimed at it — **but "bots that were added to a group as admins always receive all messages"**. Disabling privacy via BotFather instead requires re-adding the bot to every existing group.                                               | **The bot must be a group administrator.** This is an operational prerequisite, not a code decision.                                                       |
| `Message` reply metadata         | `message_id`, `date` (Unix), `edit_date`, `from`, `sender_chat`, `reply_to_message`, `external_reply`, `quote`, `message_thread_id`, `is_topic_message`, `media_group_id`                                                                                                                                       | Reply correlation is a **first-class Telegram fact**, not an inference.                                                                                    |
| `chat_member` updates            | Requires the bot to be an **administrator** *and* `"chat_member"` explicitly in `allowed_updates` (it is **not** sent by default). `ChatMemberUpdated.from` is documented as **"Performer of the action, which resulted in the change"**.                                                                       | Bans, kicks and restrictions **are attributable to a named moderator with a timestamp**. This is the strongest moderation-action signal Telegram gives us. |
| `my_chat_member` updates         | Sent without admin rights; fires when the bot is added, promoted, demoted or removed.                                                                                                                                                                                                                           | Group auto-discovery and coverage-loss detection.                                                                                                          |
| `message_reaction` updates       | Requires admin **and** explicit `allowed_updates`. Carries the reacting user. **Reactions set by bots are not delivered.**                                                                                                                                                                                      | A human moderator's ✅ becomes a clean, timestamped, attributable "handled" signal — and a bot could never forge it.                                        |
| `message_reaction_count`         | Anonymous-reaction aggregate; **grouped and delayed up to a few minutes**.                                                                                                                                                                                                                                      | Not usable for timing. Ignore.                                                                                                                             |
| Service messages                 | `new_chat_members`, `left_chat_member`, `pinned_message`, `migrate_to_chat_id`, `migrate_from_chat_id`, `group_chat_created`, `supergroup_chat_created`                                                                                                                                                         | Membership context and, critically, **supergroup migration** handling.                                                                                     |
| `update_id` semantics            | "Update identifiers start from a certain positive number and increase sequentially… allows you to ignore repeated updates or to restore the correct update sequence, should they get out of order."                                                                                                             | Gives us a natural idempotency key **and** an ordering key.                                                                                                |
| `getUpdates`                     | Long polling; `offset` confirms consumption ("an update is considered confirmed as soon as `getUpdates` is called with an offset higher than its `update_id`"); **"will not work if an outgoing webhook is set up"**; a second concurrent consumer gets `409 Conflict: terminated by other getUpdates request`. | **Outbound-only ingestion with server-enforced single-consumer semantics.**                                                                                |
| Webhook                          | HTTPS only, ports 443/80/88/8443, `secret_token` → `X-Telegram-Bot-Api-Secret-Token` header, `max_connections`, `drop_pending_updates`; Telegram repeats on non-2xx; updates retained **at most 24 hours**.                                                                                                     | The alternative transport, if a tunnel ever exists.                                                                                                        |
| Admin actions the bot could take | `deleteMessage` (needs `can_delete_messages`; only recent messages — a ~48 h limit applies to others' messages), `banChatMember`, `restrictChatMember`, `setMessageReaction`                                                                                                                                    | Deliberately **unused in v1** (§23).                                                                                                                       |

### 5.2 Verified limitations — and how each is handled

| Desired                                        | Telegram reality                                                                                                                                                     | Redesign                                                                                                                                                                                                                                                              |
| ---------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| "A message was deleted" event in a group       | **No such update exists.** The only deletion update is `deleted_business_messages`, scoped exclusively to connected *business accounts* — not groups or supergroups. | Never claim deletion detection. Moderation completion is derived from other signals (§14.3). Optionally, a **forward-probe** can *confirm* absence (§14.4) — flagged as opt-in and privacy-costly.                                                                    |
| "Who deleted the message"                      | Not exposed. Telegram's admin log is an **MTProto** feature; the Bot API has no method to read it, and a bot cannot be an MTProto client.                            | Attribute only what Telegram attributes: bans/restrictions (`chat_member.from`), replies (`message.from`), reactions (`message_reaction.user`), Filament actions (our own audit).                                                                                     |
| Read message history / backfill after downtime | **No `getChatHistory` / `getMessages` exists.** Undelivered updates are kept at most **24 hours**.                                                                   | Ingestion gaps beyond 24 h are **permanently unrecoverable**. Therefore: the ingester's uptime is a monitored SLO, and the domain records an explicit `ingestion_gap` marker so reports can say "this window is incomplete" rather than silently under-count (§20.3). |
| Know a message's current visibility            | No API.                                                                                                                                                              | Attention items age until closed by an observable event or by an operator (§13.5).                                                                                                                                                                                    |
| Two consumers of the same bot token            | Impossible — webhook and `getUpdates` are mutually exclusive; two pollers give `409`.                                                                                | **One bot token = one ingester.** n8n therefore cannot also receive updates from the same bot. This is decisive for D‑TG‑01 and D‑TG‑10.                                                                                                                              |

### 5.3 Operational prerequisites this creates

1. One bot, created via BotFather, added as **administrator** to every monitored group.
2. `allowed_updates` must explicitly list `message`, `edited_message`, `my_chat_member`,
   `chat_member`, `message_reaction` — the last two are **not** delivered by default.
3. Moderators must be *members* of the groups they own (so `chat_member`/reaction events name them)
   and their Telegram user id must be mapped once in Filament.
4. Group→supergroup migration changes `chat.id`. The ingester must follow `migrate_to_chat_id` and
   re-point the group record, preserving history (§20.2).

---

## 6. Proposed Bounded Context

```
InjazEdu Local AI
├── Assessment Intelligence            (existing — M2…M13, unchanged)
│     source_document · document_version · document_node · chunk · embedding
│     book_question · question_draft · quiz_draft · review · publication
│
└── Moderation Intelligence            (NEW — TG-M0…TG-M10)
      └── Telegram Moderation
            telegram_update · telegram_chat · telegram_user · telegram_message
            moderator · moderator_group_assignment
            attention_item · moderation_incident · moderation_action
            message_classification · classification_review
            alert_rule · alert
```

**The boundary rule, stated so it can be checked:** no module under `app/*/moderation/` may import
from an assessment module, and no assessment module may import from moderation. The only permitted
shared imports are `app.application.gateway`, `app.infrastructure.*`, and `app.domain.model_profile`.
This is a grep, and TG-M0 adds it to `scripts/check.sh` next to the existing `httpx` rule.

**Shared infrastructure** (deliberately shared, no duplication): Postgres instance and schema,
Redis, Dramatiq broker, the Model Gateway with its lane/breaker/accounting, `model_profiles` /
`model_runs`, the Filament panel shell, `.env` + `Settings`, `make check`, the `_test` guard.

**Deliberately not shared:** pgvector, chunking, retrieval, `document_version_id` scoping, prompt
evidence/citation machinery, the human-approval-before-publish workflow (moderation has no publish
step), and the InjazEdu internal API client (moderation needs nothing from InjazEdu in v1).

---

## 7. Target Architecture

```
      ┌──────────────── Telegram (cloud) ────────────────┐
      │  student groups  ·  private moderators' group    │
      └───────▲──────────────────────────┬───────────────┘
              │ outbound only            │ outbound only
   sendMessage│(alerts, private chat)    │getUpdates (long poll 30 s)
              │                          ▼
┌─────────────┴──────────────────────────────────────────── Mac M1 Pro ─────────┐
│                                                                                │
│  ai-telegram  (NEW container, singleton)                                       │
│    ├ poller     : getUpdates(offset) ─▶ INSERT telegram_updates (append-only)  │
│    │                                    ─▶ enqueue process_update              │
│    └ ticker     : every 30 s  ─▶ enqueue evaluate_alert_rules                   │
│                   daily 02:00 ─▶ enqueue purge_expired_text, close_stale       │
│                   (guarded by Redis lease ai:tg:tick:lease)                     │
│                                                                                │
│  ai-worker  (existing Dramatiq)                                                │
│    process_update ─▶ upsert chat/user/message ─▶ enqueue evaluate_attention(90s)│
│                   ─▶ record moderation_action  (reply | reaction | ban | cb)   │
│    evaluate_attention ─▶ burst-group ─▶ open/attach attention_item             │
│                       ─▶ enqueue classify_message         (TG-M5+)             │
│    classify_message   ─▶ redact ─▶ Gateway.generate_structured(role=moderation)│
│    evaluate_alert_rules ─▶ INSERT alerts ON CONFLICT (dedupe_key) DO NOTHING   │
│    deliver_alert      ─▶ Telegram provider ─▶ private moderators' group        │
│                                                                                │
│  ai-api (FastAPI)     read models + n8n-facing endpoints (TG-M9)               │
│  ai-control (Filament) Moderation Intelligence navigation group                │
│                                                                                │
│  Postgres 16  ── durable source of truth for every fact and every derived state│
│  Redis        ── Dramatiq queues, poll/tick leases, gateway lane & breaker      │
│  Model Gateway ─▶ Ollama (host)  ─▶ vLLM later, same interface                  │
│  n8n (profile: automation, optional) ── scheduled digests, external glue only   │
└────────────────────────────────────────────────────────────────────────────────┘
```

### 7.1 The ingestion flow, end to end

```
getUpdates(offset=N+1, timeout=30, allowed_updates=[…])
   └─ for each update, in update_id order:
        INSERT INTO telegram_updates (bot_id, update_id, type, chat_id, payload)
        ON CONFLICT (bot_id, update_id) DO NOTHING          ← idempotency, layer 1
        └─ if inserted: process_update.send(row_id)
   └─ UPDATE ingestion_state SET last_update_id = max(update_id), last_success_at = now()
   └─ next poll uses offset = last_update_id + 1            ← confirms consumption
```

The poller does exactly two things: durably store, and advance the offset. **All interpretation
happens in the worker**, so a bug in interpretation is replayable by re-enqueuing rows — the whole
point of D‑TG‑02.

### 7.2 The response-tracking flow

```
student message stored (sent_at = Telegram `date`)
   └─ evaluate_attention scheduled for sent_at + 90 s        ← the burst settle window
        └─ collect this sender's messages in this chat within the burst
        └─ if any matches the needs-response rule set and none is an ack-stopword:
             INSERT attention_item(opened_at = FIRST message of the burst)
             responsible_moderator_id = assignment covering opened_at

moderator message stored
   └─ close matching open attention_items in that chat  (§13.2)
   └─ record moderation_action(strength='acknowledgement') against any open incident it replies to
```

### 7.3 Component responsibilities

| Component                 | Owns                                                                                                         | Must never                                                                       |
| ------------------------- | ------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------- |
| `ai-telegram`             | Long-poll loop, offset durability, raw insert, gap detection, the 30 s tick                                  | Interpret an update, call a model, write derived state                           |
| `ai-worker`               | All derivation: messages, attention items, incidents, actions, classification, alert evaluation and delivery | Serve HTTP; hold Telegram's offset                                               |
| `app/providers/telegram/` | Every Telegram HTTP call (`getUpdates`, `sendMessage`, `answerCallbackQuery`), retry/429 handling            | Contain a business rule or an SLA threshold                                      |
| Model Gateway             | Provider choice, lane, breaker, retries, token accounting                                                    | Know what a "violation" is                                                       |
| Postgres                  | Every fact and every derived state, including alert dedupe                                                   | —                                                                                |
| Redis                     | Dramatiq queues; the poll and tick leases; the gateway lane/breaker                                          | **Hold business state.** Every Redis key here is a lock or a queue, never a fact |
| `ai-control` (Filament)   | All human UI, assignments, thresholds, review, resolution                                                    | Run migrations; call a model; call Telegram                                      |
| n8n                       | Scheduled digests, external glue, future WhatsApp                                                            | Receive Telegram updates; compute a metric; hold a prompt; own incident state    |

---

## 8. n8n vs FastAPI vs Worker vs Filament

The decisive constraint is from §5.2: **one bot token has exactly one update consumer.** If n8n
holds the webhook, our ingester cannot poll. Combined with n8n today being an unconfigured stub with
no volume and no encryption key, making it the front door for raw event capture would put
irrecoverable data (24 h retention, no backfill) behind the least-provisioned component in the stack.

So the boundary is:

| Responsibility                                              | Owner                                                     | Why not n8n                                                                                                                   |
| ----------------------------------------------------------- | --------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| Receiving Telegram updates                                  | `ai-telegram`                                             | Single-consumer constraint; data loss is permanent                                                                            |
| Reply correlation, response time, P90                       | worker + SQL                                              | A metric definition in a visual node is untestable and unversioned                                                            |
| Conversation/burst grouping                                 | worker                                                    | Same                                                                                                                          |
| Incident state machine                                      | worker + Postgres                                         | State in a workflow engine has no audit trail                                                                                 |
| Moderator assignment lookup                                 | Postgres (time-versioned)                                 | Same                                                                                                                          |
| Classification taxonomy and prompt                          | `app/application/moderation/` + `app/prompts/moderation/` | Existing rule §5.1‑7: n8n never holds prompt text                                                                             |
| SLA thresholds                                              | `alert_rules` table, edited in Filament                   | Management must change them without touching a workflow                                                                       |
| Alert **delivery** with an actionable button                | worker → Telegram provider                                | The `callback_query` for the button comes back through **our** poller — routing it out to n8n and back adds a hop for no gain |
| Daily/weekly digest to the moderators' group                | **n8n** (optional)                                        | Genuine scheduling + formatting glue, no business logic. Calls `GET /v1/moderation/summary`                                   |
| Future cross-system notifications (email, WhatsApp, Sheets) | **n8n**                                                   | Its actual strength                                                                                                           |

**n8n stays optional in v1.** Nothing in TG-M0…TG-M8 fails if the container is never started. TG-M9
is the milestone that gives it a real, bounded job, and it also configures the container properly
(volume, `N8N_ENCRYPTION_KEY`, port) — which is work that does not exist today.

---

## 9. Event Model

`allowed_updates` is set explicitly to exactly these — three of them are **not delivered by default**:

| Update             | Default?                                     | What we take from it                                                                         |
| ------------------ | -------------------------------------------- | -------------------------------------------------------------------------------------------- |
| `message`          | yes                                          | The message itself; service messages; `migrate_to_chat_id`; new/left members                 |
| `edited_message`   | yes                                          | `edit_date` + new text (stored as a new version of the text, never overwriting the original) |
| `my_chat_member`   | yes                                          | Bot added/promoted/demoted/removed → chat discovery and coverage loss                        |
| `chat_member`      | **NO — must be listed, and needs bot admin** | Ban / restrict / unban, **with the performing moderator in `from`**                          |
| `message_reaction` | **NO — must be listed, and needs bot admin** | A moderator's ✅ on a message, attributable and timestamped                                   |
| `callback_query`   | yes                                          | The "Handled" / "Not an issue" buttons on private alert messages                             |

Everything else is stored raw and ignored. `message_reaction_count` is **not** requested — it is
anonymous and delayed by minutes, so it is useless for timing.

**Fact vs derived, drawn explicitly:**

| Raw Telegram fact (immutable)                            | Derived moderation state (rebuildable)                              |
| -------------------------------------------------------- | ------------------------------------------------------------------- |
| message received, its `date`, `from`, `reply_to_message` | `attention_item` exists, its `opened_at`, its responsible moderator |
| reaction added, by whom, when                            | `moderation_action(strength='acknowledgement')`                     |
| member banned/restricted, by whom, when                  | `moderation_action(strength='enforcement')`, incident `resolved_at` |
| bot promoted/removed                                     | `telegram_chats.bot_status`, coverage alerts                        |
| — *(deletion: Telegram provides nothing)*                | — *(never inferred, never claimed)*                                 |
| —                                                        | `category`, `needs_response`, `severity`, `confidence`              |
| —                                                        | `first_response_at`, median/P90, unanswered counts                  |

---

## 10. Data Model

Conventions inherited exactly from `0002_model_gateway`: SQLAlchemy **Core `Table`** objects in a new
`app/infrastructure/models_moderation.py` on the same `metadata`; `BIGINT` identity PKs; `TIMESTAMPTZ`
with `server_default=now()`; hand-written Alembic revisions; explicit `uq_` / `ck_` / `ix_` names;
partial unique indexes to make invariants the database's problem rather than a rule someone must
remember.

Fifteen tables, introduced across seven revisions. Each is listed with purpose, key fields,
relationships, indexes, idempotency and retention.

### 10.1 `telegram_updates` — the append-only spine *(rev 0003)*

**Purpose.** Everything else in the domain is a function of this table. It is written once, never
updated except for `processed_at`, and is what makes reprocessing possible (D‑TG‑02, D‑TG‑15).

| Column              | Type                 | Notes                                                                                                                     |
| ------------------- | -------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `id`                | BIGINT PK            |                                                                                                                           |
| `bot_id`            | BIGINT NOT NULL      | Telegram's numeric bot id; future-proofs a second bot                                                                     |
| `update_id`         | BIGINT NOT NULL      | Telegram's, monotonic per bot                                                                                             |
| `update_type`       | VARCHAR(40) NOT NULL | `message` \| `edited_message` \| `my_chat_member` \| `chat_member` \| `message_reaction` \| `callback_query` \| `unknown` |
| `chat_id`           | BIGINT NULL          | Extracted for routing; NULL for updates with no chat                                                                      |
| `payload`           | JSONB NOT NULL       | The complete update, verbatim                                                                                             |
| `received_at`       | TIMESTAMPTZ NOT NULL | when we stored it                                                                                                         |
| `processed_at`      | TIMESTAMPTZ NULL     | NULL = pending                                                                                                            |
| `process_error`     | TEXT NULL            | last failure reason                                                                                                       |
| `payload_purged_at` | TIMESTAMPTZ NULL     | set by the retention job                                                                                                  |

**Indexes.** `uq_telegram_updates_bot_update UNIQUE (bot_id, update_id)` — the idempotency key;
`ix_telegram_updates_pending (received_at) WHERE processed_at IS NULL` — a cheap work queue;
`ix_telegram_updates_chat_received (chat_id, received_at DESC)`.

**Idempotency.** `INSERT … ON CONFLICT (bot_id, update_id) DO NOTHING`, and only enqueue work when a
row was actually inserted. Telegram's own guidance is that `update_id` exists precisely to "ignore
repeated updates or restore the correct update sequence".

**Retention.** `payload` is nulled at 90 days (it contains message text). `update_id`, type and
timestamps are kept forever so the event *history* survives even when the *content* does not.

### 10.2 `ingestion_state` and `ingestion_gaps` *(rev 0003)*

`ingestion_state`: one row per bot — `bot_id UNIQUE`, `last_update_id`, `last_poll_at`,
`last_success_at`, `consecutive_failures`, `allowed_updates JSONB`. Durable offset lets us detect a
`update_id` jump, which Telegram makes possible after a week of silence.

`ingestion_gaps`: `bot_id`, `gap_start_at`, `gap_end_at`, `reason` (`downtime` \| `update_id_jump` \|
`conflict_409` \| `unrecoverable_24h`), `detected_at`, `note`. **This table is why the reports can be
honest.** Any report whose window overlaps a gap is rendered with an explicit "incomplete data"
marker rather than silently under-counting. Given Telegram's 24 h retention and the absence of any
history API, a gap longer than 24 h is permanently unrecoverable and must be visible.

### 10.3 `telegram_chats` *(rev 0003)*

`chat_id BIGINT UNIQUE`, `chat_type`, `title`, `username`, `is_monitored BOOLEAN DEFAULT false`,
`bot_status` (`member`\|`administrator`\|`left`\|`kicked`), `bot_status_at`, `bot_can_delete BOOLEAN`,
`migrated_to_chat_id`, `migrated_from_chat_id`, `injaz_course_id BIGINT NULL` *(manual, no FK — MySQL
lives on another host)*, `last_event_at`, `notes`.

`is_monitored` is the **opt-in switch**: the bot may be in a chat we do not measure. Updates for
un-monitored chats are still stored raw (cheap, and makes enabling a group retroactive within the
retention window) but produce no derived state.

Indexes: `uq_telegram_chats_chat_id`, `ix_telegram_chats_monitored (is_monitored, last_event_at)`.

### 10.4 `telegram_users` *(rev 0004)*

`tg_user_id BIGINT UNIQUE`, `username`, `display_name`, `is_bot`, `first_seen_at`, `last_seen_at`,
`identity_purged_at`. **Retention nuance:** `tg_user_id` is a pseudonym and is kept forever so
historical aggregates stay joinable; `username` and `display_name` are personal data and are nulled
at 90 days **except for users linked to a `moderators` row**, whose names the reports need.

### 10.5 `moderators` and `moderator_group_assignments` *(rev 0004)*

`moderators`: `telegram_user_id BIGINT FK → telegram_users.id UNIQUE`, `display_name NOT NULL`
(operator-set and stable, independent of a Telegram profile rename), `injaz_user_id BIGINT NULL`,
`is_active`, `notes`.

`moderator_group_assignments` — the answer to D‑TG‑04:

| Column             | Type                            | Notes                                   |
| ------------------ | ------------------------------- | --------------------------------------- |
| `telegram_chat_id` | BIGINT FK → `telegram_chats.id` |                                         |
| `moderator_id`     | BIGINT FK → `moderators.id`     |                                         |
| `assignment_role`  | VARCHAR(20)                     | `primary` \| `backup`                   |
| `valid_from`       | TIMESTAMPTZ NOT NULL            |                                         |
| `valid_to`         | TIMESTAMPTZ NULL                | NULL = current                          |
| `note`             | TEXT                            | e.g. "covering while Ahmed is on leave" |

**Constraint that carries the design:**
`uq_assignment_one_current_primary UNIQUE (telegram_chat_id) WHERE assignment_role='primary' AND valid_to IS NULL`
— a partial unique index, exactly the pattern `uq_model_profiles_one_active_per_role` already uses.
Filament's reassign action must close the incumbent row and open the new one **in one transaction**.

*Rejected:* a `tstzrange` `EXCLUDE` constraint preventing all historical overlap. It is stricter and
correct, but requires enabling `btree_gist` — an `initdb` change to a shipped database. The partial
index plus a transactional reassign action buys the invariant that matters (one current owner) at no
infrastructure cost. Historical overlap is additionally covered by a test.

**Lookup rule, used everywhere:** the moderator responsible for chat *C* at instant *T* is the
`primary` row with `valid_from <= T AND (valid_to IS NULL OR valid_to > T)`. Reports therefore
reflect who was responsible **at the time of the event**, never the current owner. Index:
`ix_assignment_chat_from (telegram_chat_id, valid_from DESC)`.

### 10.6 `telegram_messages` *(rev 0004)*

One row per message in a monitored chat.

`telegram_chat_id FK`, `message_id BIGINT` (Telegram's), `telegram_user_id FK NULL`,
`sender_chat_id BIGINT NULL` (anonymous admin / channel posts), `sent_at TIMESTAMPTZ NOT NULL`
(Telegram `date` — **never** `received_at`), `edited_at`, `reply_to_message_id BIGINT NULL`
(Telegram's id, deliberately **not** a FK: the replied-to message may predate monitoring),
`message_thread_id`, `is_service BOOLEAN`, `is_from_moderator BOOLEAN NOT NULL`,
`original_text TEXT NULL`, `normalized_text TEXT NULL`, `text_purged_at`, `media_kind VARCHAR(20)`,
`entity_flags JSONB` (has_url, has_phone, has_mention, forwarded), `source_update_id FK`,
`attention_item_id BIGINT NULL FK` *(added by rev 0005)*.

`is_from_moderator` is **denormalised on purpose**: it is the truth *at the time of the message*, so
promoting someone to moderator next month does not retroactively rewrite last month's response times.

**Indexes.** `uq_telegram_messages_chat_msg UNIQUE (telegram_chat_id, message_id)` — idempotent
replay; `ix_messages_chat_sent (telegram_chat_id, sent_at DESC)`;
`ix_messages_chat_moderator_sent (telegram_chat_id, is_from_moderator, sent_at)` — the index the
response scan lives on; `ix_messages_reply (telegram_chat_id, reply_to_message_id)`.

**Retention.** `original_text`, `normalized_text` nulled at 90 days; `text_purged_at` set.

### 10.7 `attention_items` *(rev 0005)*

| Column                                                                    | Notes                                                              |
| ------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| `telegram_chat_id`, `telegram_message_id`                                 | the **first** message of the burst; `UNIQUE (telegram_message_id)` |
| `opened_at`                                                               | = that first message's `sent_at`, **not** detection time           |
| `source`                                                                  | `rule` \| `ai` \| `operator`                                       |
| `rule_version`                                                            | SMALLINT NULL — which rule set opened it                           |
| `message_classification_id`                                               | FK NULL (TG-M5+)                                                   |
| `responsible_moderator_id`                                                | FK NULL — snapshotted from the assignment covering `opened_at`     |
| `status`                                                                  | `open` \| `answered` \| `dismissed` \| `expired`                   |
| `first_response_message_id`                                               | FK NULL                                                            |
| `first_response_at`, `first_response_moderator_id`, `first_response_kind` | `direct_reply` \| `group_message`                                  |
| `closed_at`, `closed_by_user_id`, `close_reason`                          | operator dismissal / expiry                                        |

Indexes: `ix_attention_open (opened_at) WHERE status='open'` — the live queue and the SLA scan;
`ix_attention_chat (telegram_chat_id, opened_at DESC)`;
`ix_attention_moderator (responsible_moderator_id, opened_at DESC)`.

### 10.8 `moderation_incidents` *(rev 0006)*

| Column                                                                | Notes                                                                                    |
| --------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `telegram_chat_id`, `telegram_message_id`                             | `UNIQUE (telegram_message_id)`                                                           |
| `opened_at`                                                           | when the offending message was **posted**                                                |
| `detected_at`                                                         | when **we** flagged it — kept separate so a slow classifier is not billed to a moderator |
| `source`                                                              | `ai` \| `operator` \| `rule`                                                             |
| `message_classification_id`                                           | FK NULL                                                                                  |
| `category`, `severity`                                                | snapshotted from the classification at open time                                         |
| `responsible_moderator_id`                                            | assignment covering `detected_at`                                                        |
| `status`                                                              | `open` \| `acknowledged` \| `resolved` \| `closed_false_positive`                        |
| `acknowledged_at`, `acknowledged_by_moderator_id`, `acknowledged_via` |                                                                                          |
| `resolved_at`, `resolved_by_moderator_id`, `resolved_via`             |                                                                                          |
| `closed_at`, `closed_by_user_id`, `close_note`                        |                                                                                          |

Indexes: `ix_incidents_open (detected_at) WHERE status IN ('open','acknowledged')`;
`ix_incidents_chat (telegram_chat_id, detected_at DESC)`;
`ix_incidents_moderator (responsible_moderator_id, detected_at DESC)`.

**State machine (as directed):**

```
                  reply | ✅ reaction            ban/restrict | alert "Handled" | Filament resolve
   OPEN ─────────────────────────────▶ ACKNOWLEDGED ─────────────────────────────────▶ RESOLVED
     │                                        │                                            ▲
     │  ban/restrict | "Handled" | Filament resolve  ─────────────────────────────────────┘
     │
     └──── operator marks not-a-violation ────▶ CLOSED_FALSE_POSITIVE

   OPEN or ACKNOWLEDGED, untouched past incident_max_age ──▶ stays open, counted as MISSED
```

Acknowledgement is **not** resolution: a reply or a reaction proves the moderator *saw* it, not that
they *acted*. Resolution requires enforcement or an explicit human confirmation. **No transition is
ever driven by an inferred deletion**, because Telegram exposes none.

### 10.9 `moderation_actions` *(rev 0006)* — append-only

`moderation_incident_id FK NULL`, `telegram_chat_id FK`, `actor_moderator_id FK NULL`,
`actor_telegram_user_id BIGINT NULL`, `action_type`, **`action_strength`**, `occurred_at`,
`evidence_update_id FK NULL`, `detail JSONB`.

| `action_type`                | `action_strength` | Evidence                                                         |
| ---------------------------- | ----------------- | ---------------------------------------------------------------- |
| `reply`                      | `acknowledgement` | `message.reply_to_message` from a moderator                      |
| `reaction`                   | `acknowledgement` | `message_reaction` update, reacting user is a moderator          |
| `ban` / `restrict` / `unban` | `enforcement`     | `chat_member` update; actor = `from` ("performer of the action") |
| `alert_button_handled`       | `confirmation`    | `callback_query` on the private alert message                    |
| `filament_acknowledge`       | `acknowledgement` | panel action                                                     |
| `filament_resolve`           | `confirmation`    | panel action                                                     |
| `dismiss_false_positive`     | `confirmation`    | panel or alert button                                            |

Rows are never updated. This table **is** the audit trail, and the three timing metrics in §18 are
each a `MIN(occurred_at)` over one `action_strength`.

### 10.10 `message_classifications` *(rev 0007)* — immutable predictions

`telegram_message_id FK`, `model_profile_id FK → model_profiles.id ON DELETE RESTRICT`,
`model_run_id BIGINT NULL FK → model_runs.id ON DELETE SET NULL`, `prompt_version VARCHAR(40)`,
`taxonomy_version SMALLINT`, `category`, `needs_response`, `needs_moderation`, `severity`,
`confidence NUMERIC(4,3)`, `is_current BOOLEAN NOT NULL DEFAULT true`, `created_at`.

`uq_classification_current UNIQUE (telegram_message_id) WHERE is_current` — one current prediction
per message, enforced by the database, same pattern as the model roster. Reprocessing **inserts** a
new row and flips the flag in one transaction; the old prediction survives, which is what makes
"did the new model change this label?" answerable (D‑TG‑15).

`prompt_version` is a plain string, **not** a FK — `prompt_versions` does not exist yet and is owned
by assessment milestone M5. Mirrors the existing `model_runs.prompt_version_id` precedent of not
adding a FK to a table that has not been designed.

### 10.11 `classification_reviews` *(rev 0008)* — append-only corrections

`message_classification_id FK` (the exact prediction being judged), `reviewer_user_id FK → users.id`,
`verdict` (`confirmed` \| `corrected` \| `rejected`), `corrected_category NULL`,
`corrected_needs_response NULL`, `corrected_needs_moderation NULL`, `corrected_severity NULL`,
`note`, `created_at`.

**The prediction row is never mutated.** The effective label is a view:
`COALESCE(latest review's correction, prediction)`. That preserves, for every message: the original
AI prediction, the model profile, the prompt version, the confidence, the human correction, the
reviewer and the timestamp — exactly what the existing platform does for `model_runs`.

### 10.12 `alert_rules` and `alerts` *(rev 0009)*

`alert_rules`: `name UNIQUE`, `scope` (`global`\|`chat`), `telegram_chat_id FK NULL`, `trigger`
(`attention_item_age` \| `incident_age` \| `incident_opened` \| `group_silent`),
`threshold_seconds`, `severity_at_least`, `category_in JSONB`, `quiet_hours JSONB`,
`destination` (`moderator_group`\|`filament_only`), `destination_chat_id`,
`repeat_every_seconds`, `max_repeats`, `is_enabled`.
Constraints: `ck_alert_rules_scope` (`(scope='chat') = (telegram_chat_id IS NOT NULL)`);
`uq_alert_rule_global UNIQUE (trigger) WHERE scope='global'`;
`uq_alert_rule_chat UNIQUE (trigger, telegram_chat_id) WHERE scope='chat'`.
A chat rule overrides the global rule for that trigger. **No threshold is hard-coded anywhere in
code** — the seed inserts defaults as *data*, exactly as `make seed-profiles` does.

`alerts`: `alert_rule_id FK`, `subject_type`/`subject_id`, `repeat_index SMALLINT`,
`dedupe_key VARCHAR(160) NOT NULL`, `fired_at`, `delivery_status`
(`pending`\|`sent`\|`failed`\|`suppressed`), `delivered_at`, `delivery_error`, `attempts`,
`sent_chat_id`, `sent_message_id` *(so a button callback finds its alert)*.
`uq_alerts_dedupe UNIQUE (dedupe_key)` — **Postgres, not a Redis TTL, is what makes alerting
idempotent.** `dedupe_key = "{rule_id}:{subject_type}:{subject_id}:{repeat_index}"`.

---

## 11. Message / Conversation / Attention Model

**D‑TG‑03: three concepts in v1, not five.** `telegram_message` (fact), `attention_item` (derived
unit of work), `moderation_incident` (derived unit of enforcement). **No `conversations` table.**

The conversation problem is real — the prompt's own example is three messages that are one question —
but a full thread model is the largest over-engineering risk in this domain. The cheap rule that
covers the observed case:

> **Burst rule.** Consecutive messages from the same sender in the same chat (and same
> `message_thread_id`) with a gap ≤ `MODERATION_BURST_GAP_S` (default 90 s) form one burst.
> A burst opens **at most one** attention item. `opened_at` is the **first** message of the burst.

```
10:03:10  السلام عليكم                 ┐
10:03:44  أنا مشترك في الدورة           ├─ one burst → one attention_item
10:04:20  ولكن المحاضرة مش ظاهرة        ┘   opened_at = 10:03:10   (what the student actually waited)
```

Implementation: `evaluate_attention` is a **delayed** Dramatiq message scheduled for
`sent_at + burst_gap`. It re-reads the burst, applies the rule set to the *whole burst*, and opens
one item if any message matches. This is deterministic, unit-testable with a fake clock, and needs no
look-ahead heuristics. A 90 s decision delay is irrelevant against SLA thresholds measured in
minutes, and it does **not** delay the clock: `opened_at` is Telegram's timestamp.

`reply_to_message` is stored as a fact from day one and used for correlation, but **no thread tree is
built** in v1. Forum topics (`message_thread_id`) are stored and used to scope the burst, not to
model a hierarchy.

**Deferred to post-v1:** an explicit `conversations` table, cross-sender threading, and treating a
different student's follow-up as part of the same conversation.

---

## 12. Moderator Assignment Model

```
Moderator A ──primary──▶ Group 1, Group 2, Group 3
Moderator B ──primary──▶ Group 4, Group 5
Moderator A ──backup───▶ Group 4                    (valid_from … valid_to)
```

**In v1:** primary owner, optional backups, and **time-versioned history**. History is *not* deferred,
even though it looks like complexity, because without it every report silently attributes last
month's misses to this month's owner — and re-deriving it later is impossible once the current-owner
column has been overwritten. It costs two columns and one partial unique index.

**Attribution rules:**
- An attention item's `responsible_moderator_id` = primary at `opened_at`.
- An incident's `responsible_moderator_id` = primary at `detected_at`.
- **Any** moderator's response closes the item (the student's wait ends regardless of who answered),
  but `first_response_moderator_id` is recorded separately so "covered by a colleague" is visible.
  SLA credit stays with the responsible moderator; a "responses given outside your own groups" figure
  is a per-moderator column, not a penalty.
- A chat with no primary assignment still collects items and incidents, with
  `responsible_moderator_id = NULL`, and appears in Filament as **Unassigned** — a coverage problem
  the dashboard must surface rather than hide.

**Bootstrapping** (there is no source of truth to import): the bot's `chat_member` history reveals who
the chat's administrators are, and Filament proposes them as assignment candidates. The operator
confirms. `telegram_user_id → moderator` mapping is a one-time manual step per person.

---

## 13. Response Tracking Rules

These are the definitions the whole product rests on. Every one is deterministic and testable.

### 13.1 What opens an attention item (v1, AI-free) — D‑TG‑05

`source='rule'`, `rule_version=1`. A burst opens an item when **all** hold:

1. the sender is **not** a moderator, not a bot, and not the group itself (`sender_chat`);
2. no message in the burst is a service message;
3. the burst is **not** purely an acknowledgement — every message matches the ack stoplist
   (`شكرا`, `شكراً`, `تمام`, `تسلم`, `جزاك الله خير`, `ok`, `okay`, `👍`, `❤️`, `🌹`, bare emoji, ≤ 2 chars);

and **at least one** message carries a question signal:

4. contains `?` or `؟`; **or**
5. matches a small Arabic/English interrogative or support pattern —
   `متى`, `أين`/`وين`, `كيف`/`ازاي`/`كيفية`, `ليش`/`ليه`/`لماذا`, `هل`, `ايش`/`إيش`/`ايه`, `مين`/`من`,
   `كم`, `ممكن`, `محتاج`/`عايز`/`أبغى`/`ابي`, `مشكلة`, `ما ظهر`/`مش ظاهر`/`لم تظهر`, `ما يفتح`/`مش شغال`,
   `دفعت`, `ما وصل`/`لم يصل`, `متأخر`, plus `how`, `when`, `where`, `why`, `can i`, `not working`;
   **or**
6. it @-mentions a moderator, or directly replies to a moderator's message.

> The rule set is deliberately **not** anchored on a trailing question mark — most real Arabic
> questions in these groups carry none.

Matching runs on `normalized_text` (§15.4). The rule set lives in one module, is versioned by an
integer, and every opened item records the version that opened it. **Operators can dismiss a false
positive and add a missed item** in Filament; both are recorded as `source='operator'` and both are
the raw material for measuring the rule set's precision and recall (§18.7) — which is exactly the
evidence needed to justify replacing it with the model at TG-M5.

### 13.2 What counts as a response — D‑TG‑06

A `telegram_message` *R* closes an open attention item *I* when:

- `R.telegram_chat_id = I.telegram_chat_id`;
- `R.is_from_moderator = true` (any moderator, per §12);
- `R.sent_at > I.opened_at` — strictly after, so an out-of-order arrival can never close it;
- and either
  - **(a) direct reply** — `R.reply_to_message_id` is one of the burst's message ids
    → `first_response_kind='direct_reply'`; or
  - **(b) group message** — `R` is the first moderator message in the chat after `I.opened_at`
    in the same thread (`message_thread_id` equal, or both NULL)
    → `first_response_kind='group_message'`.

Rule (a) wins over (b) when both could apply, and rule (a) can close an item **out of order** (a
moderator answering the older of two open questions). Rule (b) closes **only the oldest** open item in
that chat/thread — one message cannot be credited with clearing a backlog.

**A reaction does NOT close an attention item.** A ✅ on a question is not an answer. Reactions are
acknowledgement evidence for *incidents* only.

**A bot message never counts**, including our own — which is moot, since our bot never posts in a
student group.

### 13.3 Deleted student messages

Undetectable (§5.2). The item ages normally. If the student's question genuinely vanished, an
operator dismisses the item with `close_reason='message_removed'` — a human judgement, recorded as
such, never presented as a Telegram fact.

### 13.4 Edited messages

`edit_date` is recorded and the new text stored, but `opened_at` and the response clock keep using the
original `sent_at`. An edit that *adds* a question to a previously-unqualifying burst opens a **new**
item with `opened_at = edit_date` — the moderator could not have answered before the words existed.

### 13.5 When ageing stops

An item ages until it is `answered` or `dismissed`, or until
`opened_at + MODERATION_ITEM_MAX_AGE_S` (default 24 h), at which point a daily job sets it to
`expired`. Expired items are **permanently counted as unanswered** but are excluded from the
response-time distributions (they have no response) and from "oldest unanswered", so one abandoned
item cannot dominate today's dashboard.

---

## 14. Policy Violation / Incident Tracking

### 14.1 Opening

v1: an operator opens an incident from any message in Filament (`source='operator'`). From TG-M5, a
classification with `needs_moderation=true` and `confidence ≥ MODERATION_INCIDENT_CONFIDENCE`
(default 0.85) opens one automatically (`source='ai'`). Below that floor it goes to the
**Classification Review** queue instead of alerting anyone — a low-confidence false accusation is
worse than a delay.

`opened_at` = the offending message's `sent_at`. `detected_at` = now. Both are stored, because
`detected_at − opened_at` measures **our** latency and must never be charged to a moderator.

### 14.2 Acknowledgement

First `moderation_action` with `action_strength='acknowledgement'`:
a moderator reply to the offending message, a moderator reaction on it, or a Filament acknowledge.
Sets `status='acknowledged'`, `acknowledged_at`, `acknowledged_by_moderator_id`, `acknowledged_via`.

### 14.3 Resolution — D‑TG‑07

Only stronger evidence resolves an incident:

| Signal                                               | Source                                  | Strength       |
| ---------------------------------------------------- | --------------------------------------- | -------------- |
| Sender banned, kicked or restricted in that chat     | `chat_member` update; actor from `from` | `enforcement`  |
| Moderator presses **✅ Handled** on the private alert | `callback_query`                        | `confirmation` |
| Operator resolves in Filament                        | panel                                   | `confirmation` |

Sets `status='resolved'`, `resolved_at`, `resolved_by_moderator_id`, `resolved_via`. An incident may
go `OPEN → RESOLVED` directly (a ban with no prior reply).

**Nothing here is called a deletion.** The Bot API exposes no deletion update for groups and no way
to learn who deleted a message; the platform therefore never records, displays, or implies that it
observed one. Where the UI would naturally want to say "removed", it says
*"no removal evidence — Telegram does not report message deletion"*.

### 14.4 False positives

`status='closed_false_positive'` with a reason, from Filament or the **🚫 Not an issue** alert
button. These rows are the labelled negative set for §15.6, and they are excluded from every
"missed" count.

### 14.5 The deletion probe — deliberately not in v1

A `forwardMessage` into a private log chat would fail if the message no longer exists, giving
*absence* evidence (never an actor, never an exact time). It is **out of scope for v1** by decision,
and if ever revisited it is **secondary corroborating evidence only** — it would copy student content
into a second chat and add an API call per open incident per tick. Recorded here so the option is not
rediscovered as a novelty later.

---

## 15. AI Classification Design

### 15.1 Taxonomy v1 — D‑TG‑08

Seven categories, two booleans, one severity. Deliberately smaller than the prompt's draft list.

| Category          | Covers                                                                                                      | Typical flags                              |
| ----------------- | ----------------------------------------------------------------------------------------------------------- | ------------------------------------------ |
| `QUESTION_COURSE` | schedule, lecture links, content, exam dates — *"متى تبدأ المحاضرة؟"*, *"أين رابط المحاضرة؟"*               | `needs_response=true`                      |
| `QUESTION_ACCESS` | payment made / course or book not appearing / login — *"الكتاب مش ظاهر عندي"*, *"دفعت ولكن الدورة لم تظهر"* | `needs_response=true`, severity ≥ `medium` |
| `COMPLAINT`       | dissatisfaction, escalation risk, public criticism                                                          | `needs_response=true`                      |
| `CHITCHAT`        | greetings, thanks, emoji, social                                                                            | `needs_response=false`                     |
| `SPAM_OR_AD`      | spam **and** competitor promotion                                                                           | `needs_moderation=true`                    |
| `ABUSE`           | insults, harassment, inappropriate content                                                                  | `needs_moderation=true`, severity ≥ `high` |
| `OTHER`           | none of the above                                                                                           | —                                          |

**Why `SPAM_OR_AD` is one label in v1:** the operational response is identical (remove and warn), the
distinction is genuinely hard for a 4 B local model in dialect Arabic, and a wrong split produces two
unreliable numbers instead of one reliable one. Splitting `COMPETITOR_AD` out is a `taxonomy_version`
bump at v2, done **after** the review queue has produced real labelled examples — and because
predictions are immutable and re-runnable (§10.10), the split is retroactive within retention.

Merging technical/payment into `QUESTION_ACCESS` is the same reasoning: the moderator does the same
thing, and it is the bucket management cares most about.

### 15.2 Structured output

```python
# app/application/moderation/classification.py
class MessageClassificationResult(BaseModel):
    category: Literal["QUESTION_COURSE", "QUESTION_ACCESS", "COMPLAINT",
                      "CHITCHAT", "SPAM_OR_AD", "ABUSE", "OTHER"]
    needs_response: bool
    needs_moderation: bool
    severity: Literal["none", "low", "medium", "high"]
    confidence: float          # 0.0–1.0, range-checked in application code
```

Called through the existing gateway, which already sends
`response_format.json_schema` with `strict: true`, checks `finish_reason == "stop"` **before**
parsing, and raises `ModelTruncatedError` / `StructuredOutputInvalidError` from the closed taxonomy.
Nothing new is needed. `max_output_tokens` is set low (≈128) because the output is tiny — and because
truncation is a real, measured failure mode in this stack (`content: ""` with HTTP 200).

### 15.3 Model profile — D‑TG‑14

**Add `role='moderation'`** to `model_profiles`. This requires exactly three small changes:

1. widen `ck_model_profiles_role` to `role IN ('llm','embedding','moderation')` (Alembic rev 0007);
2. widen `Role` in `app/domain/model_profile.py`;
3. add an additive, backwards-compatible `role: Role = "llm"` keyword to
   `Gateway.generate_text` / `generate_structured` so a caller can select the profile.
   **This is the only extension to M1's contract, and no existing caller changes.**

The partial unique index then gives, for free, exactly one active moderation model, swappable in
Filament without touching the assessment generator — and `model_runs` slices per profile, so
"how much does moderation classification cost us" is answerable on day one. Seed:
`ollama-gemma4-e2b-moderation` (same model, `temperature: 0`, `num_predict: 128`, `num_ctx: 2048`).

The **lane stays `llm`** — it exists to stop three concurrent generations on a 16 GB machine, and a
moderation call is still a generation. Lane selection is by operation, not by role; no change needed.

*Rejected:* reusing `role='llm'`. It would force moderation and MCQ generation onto the same model
forever, and swapping the generator to `qwen3:8b` for quality would silently make every Telegram
message 8 B-expensive.

### 15.4 Arabic handling

**Do not block on assessment milestone M4** — no normaliser exists yet, and M4's is designed for
book text. This domain owns a small one at `app/application/moderation/text.py`:

NFKC · strip tashkeel and tatweel · `أ إ آ ٱ → ا` · `ة → ه` · `ى → ي` · Arabic-Indic digits `٠-٩` and
Eastern `۰-۹` → ASCII · collapse whitespace and repeated characters (`تماااام → تمام`) · keep emoji
(they are signal) · **keep Latin script and code-switching intact** — "STEP", "zoom link", "الـ link"
must survive.

**`original_text` is never modified.** `normalized_text` is a separate column used for rule matching
and for the LLM. When M4 lands its own normaliser, this one is either adopted by it or left as the
moderation-specific variant — a note in TG-M0's docs, not a dependency.

### 15.5 Redaction before the model — this is the important one

The classifier sends **redacted `normalized_text` only**. Never a name, a username, a Telegram id, a
chat title, or a course name. Before the gateway call:

```
phone / long digit runs      → «رقم»
email                        → «بريد»
URL                          → «رابط»
@username                    → «مستخدم»
```

Redacting **before** the gateway (not after) is deliberate: the gateway's existing
`GATEWAY_CAPTURE_PAYLOADS` debug flag writes `request_payload` into `model_runs`, and if it is ever
switched on, only already-redacted text can land there. Payload capture must not be a privacy
regression waiting to be toggled.

The prompt template lives in `app/prompts/moderation/classify_v1.md`, is versioned by filename, and
its version string is stored on every prediction. **No prompt text ever goes near n8n** (rule §5.1‑7).

### 15.6 Confidence and human correction

- `confidence` is the model's **self-report** and is weakly calibrated. It is used as a **routing
  hint**, never as a probability, and the dashboard labels it as such.
- `< MODERATION_CONFIDENCE_FLOOR` (0.60) → prediction stored, **no** item or incident opened, message
  queued for review.
- `0.60 … 0.85` → attention item may open; an incident opens flagged `low_confidence` with severity
  capped at `medium`, and its alert says "possible".
- `≥ 0.85` → normal.
- Every prediction, correction, model profile, prompt version and reviewer is preserved (§10.10,
  §10.11). **The AI result is never overwritten.**

### 15.7 Reprocessing — D‑TG‑15

A reprocess run is: select messages by chat/date/category within retention → for each, insert a new
`message_classifications` row (new `taxonomy_version` / `prompt_version` / `model_profile_id`) and
flip `is_current` in the same transaction. Derived state is **not** silently rewritten: a reprocess
produces a diff report ("142 messages changed label; 9 would now open an incident") that an operator
applies or discards. Historical reports remain reproducible because every incident and item stores
the classification id it was opened from, and that row is immutable.

---

## 16. Alerting Architecture

```
tick (30 s)
  └─ evaluate_alert_rules
       for each enabled rule, resolved chat-override-first:
         attention_item_age  : open items where now() - opened_at   > threshold
         incident_age        : open/ack incidents where now() - detected_at > threshold
         incident_opened     : incidents created since the last tick, severity ≥ rule floor
         group_silent        : monitored chats with last_event_at older than threshold
       → dedupe_key = "{rule}:{subject_type}:{subject_id}:{repeat_index}"
       → INSERT INTO alerts … ON CONFLICT (dedupe_key) DO NOTHING
       → for rows actually inserted: deliver_alert.send(alert_id)

deliver_alert
  └─ suppressed if inside the rule's quiet_hours (recorded as 'suppressed', not dropped)
  └─ Telegram provider → sendMessage to the PRIVATE moderators' group
       inline keyboard: [ ✅ تم التعامل ]  [ 🚫 ليست مخالفة ]  [ 🔗 فتح في لوحة التحكم ]
  └─ store sent_chat_id / sent_message_id; on failure: status='failed', Dramatiq retries with backoff

callback_query (arrives through the SAME poller — one bot, one consumer)
  └─ look up the alert by sent_message_id → its incident
  └─ INSERT moderation_action(strength = confirmation)  → incident RESOLVED / CLOSED_FALSE_POSITIVE
  └─ answerCallbackQuery + edit the private alert message to show who handled it and when
```

Example bodies (Arabic, private group only):

```
⚠️ سؤال بانتظار رد منذ ١٥ دقيقة
المجموعة: الرخصة المهنية
المشرف المسؤول: أحمد
«الكتاب مش ظاهر عندي»
```
```
🚨 اشتباه بإعلان لجهة منافسة  (ثقة ٠٫٧٢ — مبدئي)
المجموعة: STEP  ·  منذ ٣ دقائق  ·  المشرف المسؤول: محمد
```

**Guarantees.** Thresholds are **data** (`alert_rules`), seeded as defaults and edited in Filament —
no SLA number appears in code. Dedupe is a Postgres unique index, not a Redis TTL. `max_repeats` and
`quiet_hours` bound alert fatigue. Delivery failure never blocks incident state. And the student
group is never a destination — `destination` has no value that resolves to a monitored chat, and a
test asserts it.

---

## 17. Dashboard / Filament UX

A new navigation group **Moderation Intelligence**. Note the panel currently defines *no* navigation
groups at all, so this introduces the first — `ModelProfileResource` gains
`$navigationGroup = 'Platform'` in the same change so it is not left orphaned at the root. That is a
one-line edit and the only modification to existing Filament code.

**v1 navigation — five entries, then three more as their milestones land:**

| Entry                   | Type                                    | Milestone |
| ----------------------- | --------------------------------------- | --------- |
| Overview                | Dashboard page + widgets                | TG-M7     |
| Live Attention Queue    | Custom page, 15 s poll                  | TG-M3     |
| Incidents               | Resource                                | TG-M4     |
| Telegram Groups         | Resource                                | TG-M2     |
| Moderators              | Resource + Assignments relation manager | TG-M2     |
| *Alert Rules*           | Resource                                | TG-M6     |
| *Team Performance*      | Page                                    | TG-M7     |
| *Classification Review* | Page                                    | TG-M8     |

**Overview.** Groups monitored · messages today · attention items opened / answered / open ·
incidents open / acknowledged / resolved / missed · **ingestion health banner** (last update
received, pending backlog, any gap overlapping today) · unassigned groups.

**Live Attention Queue.** Group · first message (truncated, RTL) · category + confidence ·
**waiting time, live** · severity · responsible moderator · status. Row actions: *Dismiss (false
positive)* · *Open incident* · *Reassign*. Sorted oldest-first, because that is the working order.

**Incidents.** Filter by status / severity / category / group / moderator / date. Detail page must
answer the six required questions on one screen:

```
what happened   original message (RTL) + entity flags
when            posted 10:03  ·  detected 10:05  ·  ack 10:07  ·  resolved 10:12
why this label  category · confidence · model profile · prompt version · taxonomy version
                → "Review this classification" (records a correction, never overwrites)
who handled it  action timeline from moderation_actions, each with its evidence update id
how long        acknowledgement 2m · handling confirmation 7m · observed enforcement 7m
corrected?      full review history
```
A standing footnote on this page: *"Telegram does not report message deletion in groups; no removal
evidence is available."*

**Group performance.** Volume · attention items · median/P90 first response · open items ·
incidents and outcomes · coverage gaps (bot not admin, no primary assignment, silent periods).

**Moderator performance.** Groups owned (at the selected period, from assignment history) · items
requiring response / answered / unanswered · median, P90, max first response · oldest unanswered ·
incidents · acknowledged / resolved / missed · median acknowledgement and handling-confirmation time.
**No composite score** (§18.6).

RTL: the panel has no `ar` locale today. v1 sets `direction: rtl` and Arabic labels for this
navigation group only; a full panel localisation is not in scope.

**Correction (TG-M2, research Finding 1).** Filament v5.7.8 writes `dir` once onto `<html>` from a
single locale-driven translation key, panel-wide — there is no per-navigation-group direction to set.
TG-M2 implements this instead as `dir="auto"` on each Arabic-content field, with the panel locale and
chrome left English/LTR throughout.

---

## 18. Metrics — exact definitions

All times are UTC in the database and rendered in `Asia/Riyadh`. All durations are seconds.
"In window" always means `opened_at`/`detected_at` inside the window, never `created_at`.

### 18.1 First Response Time (FRT)

```
FRT(item) = first_response_at - opened_at        -- only where status = 'answered'
```
Items that are `open`, `expired` or `dismissed` contribute **no** FRT value. This matters: including
unanswered items as "infinite" would corrupt the median, and dropping them silently would flatter it —
so they are reported separately and always alongside it (§18.3).

```sql
SELECT
  percentile_cont(0.5) WITHIN GROUP (ORDER BY frt) AS median_frt,
  percentile_cont(0.9) WITHIN GROUP (ORDER BY frt) AS p90_frt,
  max(frt)                                        AS max_frt,
  count(*)                                        AS answered
FROM (
  SELECT extract(epoch FROM (first_response_at - opened_at)) AS frt
  FROM attention_items
  WHERE status = 'answered'
    AND opened_at >= :from AND opened_at < :to
    AND responsible_moderator_id = :moderator      -- or telegram_chat_id = :chat
) s;
```

`percentile_cont` (interpolating) for median and P90. With ~5 moderators the sample is small, so the
dashboard **shows `answered` next to every percentile** and suppresses P90 below 10 samples rather
than printing a number built from four points. Averages are not displayed at all.

### 18.2 Unanswered count

`count(*)` of items in window with `status IN ('open','expired')`. Reported as a count **and** as a
share of `opened`, never as a bare number.

### 18.3 Oldest Unanswered Age

`max(now() - opened_at)` over `status='open'` only. `expired` items are excluded (§13.5) so one
abandoned item cannot pin the dashboard at 3 days forever; the expired count is shown beside it.

### 18.4 The three incident timings — named as directed

| Metric                       | Definition                                                                 | Evidence                                         |
| ---------------------------- | -------------------------------------------------------------------------- | ------------------------------------------------ |
| `acknowledgement_time`       | `MIN(occurred_at) WHERE action_strength='acknowledgement'` − `detected_at` | moderator reply or reaction                      |
| `handling_confirmation_time` | `MIN(occurred_at) WHERE action_strength='confirmation'` − `detected_at`    | alert button, Filament resolve                   |
| `observed_enforcement_time`  | `MIN(occurred_at) WHERE action_strength='enforcement'` − `detected_at`     | ban / restrict `chat_member`                     |
| `detection_latency`          | `detected_at − opened_at`                                                  | **system** metric — never charged to a moderator |

There is **no `deletion_time`**, and there will not be one unless Telegram exposes the evidence.
Each of the three is reported with median / P90 / max and its own sample count, since an incident may
have one, two or all three.

### 18.5 Handled vs missed

- **Handled** — `status IN ('resolved')` (`acknowledged` is *not* handled; it is shown separately).
- **Missed** — `status IN ('open','acknowledged')` and `detected_at + incident_max_age < now()`.
- **False positive** — `closed_false_positive`; excluded from both numerator and denominator.
- **Handled ratio** = resolved ÷ (resolved + missed).

### 18.6 No composite score in v1 — D‑TG‑16

A single number would be built from a small sample (≈5 people), a rule set with unmeasured precision,
and an unresolvable attribution gap (a moderator who deletes spam instantly and silently scores worse
than one who bans slowly, because Telegram reports the ban and not the deletion). The predictable
failure modes are: gaming by reacting ✅ without acting; avoiding hard groups; and management
treating a metric artefact as performance. If a composite is ever wanted, it needs (a) a measured
false-positive rate from §18.7, (b) volume normalisation per group, and (c) an explicit statement of
what it cannot see. Until then: observable operational metrics only.

### 18.7 Metrics about the system itself

Rule/AI precision and recall, computed from operator dismissals and manual additions:
`precision = 1 − dismissed ÷ opened`, `recall ≈ opened ÷ (opened + operator_added)`.
Plus: ingestion lag, classification queue depth, alert delivery success, gap minutes per day.
These decide when the rule set is ready to be replaced by the model — and whether the model is
actually better.

---

## 19. Privacy / Retention / Security — D‑TG‑11

### 19.1 The two identity planes

```
Operational identity                     Classification input
─────────────────────                    ────────────────────
tg_user_id, username, display_name       redacted normalized_text ONLY
chat title, course mapping        ──✗──▶ (no name, no id, no chat, no course)
moderator names, assignments             §15.5
```
The model never needs to know *who* asked; it needs to know *what kind of thing* was said.

### 19.2 What is stored, and for how long

| Data                                                           | Retention      | After                                              |
| -------------------------------------------------------------- | -------------- | -------------------------------------------------- |
| `telegram_updates.payload`                                     | 90 days        | nulled; `update_id`, type, timestamps kept forever |
| `telegram_messages.original_text` / `normalized_text`          | 90 days        | nulled, `text_purged_at` set                       |
| `telegram_users.username` / `display_name` (non-moderators)    | 90 days        | nulled; `tg_user_id` (a pseudonym) kept            |
| Moderator names                                                | while employed | operator-managed                                   |
| Classifications, reviews, incidents, actions, items, durations | **forever**    | this is what the reports need                      |
| `model_runs` for moderation calls                              | forever        | already digest-only unless capture is on           |

Configurable via `MODERATION_TEXT_RETENTION_DAYS=90`. A nightly `purge_expired_text` actor does the
work in bounded batches and logs a count. **The purge is a hard delete of columns, not a soft flag.**

Consequence, stated plainly: **reclassification of messages older than the retention window is
impossible.** That is the accepted cost of not keeping a permanent archive of students' payment
problems.

### 19.3 Security

- The bot token lives in `.env` as `TELEGRAM_BOT_TOKEN` and is never written to a table, a log, or a
  spec. `scripts/scan_secrets.sh` already fails on credential-shaped values in tracked files; TG-M0
  adds the token's shape (`\d{8,10}:[A-Za-z0-9_-]{35}`) to it.
- No inbound port, no tunnel, no public DNS (D‑TG‑01).
- The FastAPI moderation endpoints (TG-M9, for n8n) require a shared secret header
  (`X-Moderation-Token`) and bind to the compose network — this is the **first** authentication on
  the FastAPI surface and must not be skipped just because the existing routes have none.
- Logs never carry message text. The stdlib formatter drops `extra` today, which accidentally helps,
  but TG-M0 makes it a rule with a grep in `scripts/check.sh` and a test.
- `GATEWAY_CAPTURE_PAYLOADS` stays `false`; and because redaction happens **before** the gateway,
  turning it on is not a privacy regression (§15.5).
- Backups: the nightly `pg_dump` in the master plan's §18 has no milestone; this domain adds student
  PII to the database, which strengthens the case. Flagged in §27 as a risk, not silently assumed.

---

## 20. Reliability / Idempotency / Failure Recovery

### 20.1 Idempotency, at three layers

1. **Ingest** — `UNIQUE (bot_id, update_id)`; work is enqueued only when a row is actually inserted.
2. **Derive** — `UNIQUE (telegram_chat_id, message_id)` on messages, `UNIQUE (telegram_message_id)`
   on items and incidents. Every derivation is an upsert, so replaying an update is a no-op.
3. **Alert** — `UNIQUE (dedupe_key)` on `alerts`, in Postgres.

Therefore: **reprocessing the whole `telegram_updates` table from row 1 must converge to the same
derived state.** That is a test (§22), not an aspiration.

### 20.2 Failure scenarios

| Scenario                                     | Behaviour                                                                                                                                                                         | Recovery                                                                                                                                         |
| -------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Same update delivered twice**              | `ON CONFLICT DO NOTHING`; no second job                                                                                                                                           | automatic                                                                                                                                        |
| **Updates out of order**                     | Derivation is keyed on Telegram's `date`, not arrival order. A moderator reply that arrives before the question cannot close it (`sent_at > opened_at` is strict)                 | automatic                                                                                                                                        |
| **Ingester down < 24 h**                     | Telegram buffers; on restart `getUpdates(offset=last+1)` drains the backlog                                                                                                       | automatic; a gap row is written for the window                                                                                                   |
| **Ingester down > 24 h**                     | **Data is permanently lost — Telegram discards updates after 24 h and offers no history API**                                                                                     | `ingestion_gaps` row with `reason='unrecoverable_24h'`; every report overlapping it is flagged incomplete                                        |
| **Two ingesters race**                       | Telegram returns `409 Conflict`; additionally a Redis lease `ai:tg:poll:lease` admits one                                                                                         | the loser backs off and logs; a gap row only if both stop                                                                                        |
| **Worker down**                              | Updates keep landing (poller and worker are separate processes); `processed_at IS NULL` backlog grows                                                                             | on restart, a `drain_pending_updates` job re-enqueues the backlog in `update_id` order                                                           |
| **Postgres down**                            | Poller does **not** advance the offset — it retries the insert. Telegram redelivers                                                                                               | no loss under 24 h                                                                                                                               |
| **Ollama down / slow**                       | `ProviderUnreachableError` (retryable) → gateway retries → breaker opens after 5. Classification jobs retry with backoff                                                          | **Deterministic tracking is unaffected.** Items still open by rule and still measure response time. Classification backfills                     |
| **Classification slower than the moderator** | The moderator replies first; the item is already `answered` when the label lands. The label attaches; no incident opens if the message was already handled and is not a violation | by design — the clock is Telegram's, not ours                                                                                                    |
| **Message deleted before classification**    | Undetectable. The label is produced from stored text                                                                                                                              | acceptable; §14.3                                                                                                                                |
| **Bot loses admin rights**                   | `my_chat_member` → `bot_status` updated; `message_reaction` and `chat_member` stop arriving silently                                                                              | a `group_silent` alert plus a Filament coverage warning; **this is the failure most likely to go unnoticed**, so it gets its own dashboard badge |
| **Bot removed from a group**                 | `my_chat_member` → `kicked`/`left`; `is_monitored` left true so the gap is visible                                                                                                | operator decides                                                                                                                                 |
| **Group → supergroup migration**             | `migrate_to_chat_id` service message; the ingester writes `migrated_to_chat_id`, creates/links the new chat row, and **re-points assignments and open items**                     | automatic, transactional, and tested — this is the classic Telegram footgun                                                                      |
| **Model changed / taxonomy bumped**          | New immutable prediction rows, `is_current` flipped; reprocess emits a diff for approval                                                                                          | §15.7                                                                                                                                            |
| **n8n down**                                 | Digests stop                                                                                                                                                                      | nothing else is affected; n8n owns no state                                                                                                      |
| **Alert delivery fails**                     | `alerts.delivery_status='failed'`, Dramatiq retries with backoff; incident state is unchanged                                                                                     | the Filament queue is always the fallback channel                                                                                                |
| **Telegram 429 rate limit**                  | The provider honours `retry_after` from the response body                                                                                                                         | bounded, in `app/providers/telegram/`                                                                                                            |

### 20.3 What the platform will not pretend

It cannot say a message was deleted, who deleted it, or what happened during an ingestion gap longer
than 24 h. Each of those is surfaced as an explicit absence in the UI, not smoothed over.

---

## 21. Observability

Extend the **existing** health report rather than adding a stack. `GET /health` gains a
`telegram_ingestion` component, `REQUIRED = false` (informational, exactly like `model_runtime`, so a
stopped bot does not fail readiness):

```json
"telegram_ingestion": {
  "status": "ok", "required": false, "latency_ms": 4,
  "detail": "last update 12s ago",
  "ingestion": {
    "last_update_at": "2026-09-08T13:04:11Z",
    "seconds_since_last_poll": 12,
    "pending_updates": 0,
    "consecutive_failures": 0,
    "monitored_chats": 7,
    "chats_silent_over_6h": 1,
    "open_gaps": 0,
    "bot_not_admin_in": ["الرخصة المهنية — مسائي"]
  }
}
```

That single block answers all of: is ingestion healthy · when was the last update · are events being
dropped · is the queue delayed · which groups stopped receiving events · has the bot lost rights.

**Plus:**
- **Correlation ids.** The logging formatter currently drops `extra` entirely, so nothing is
  traceable. TG-M0 makes `JsonFormatter` emit a whitelist of extra keys (`update_id`, `chat_id`,
  `message_id`, `incident_id`, `alert_id`, `actor`) and nothing else — a contained fix that keeps the
  "no message text in logs" rule intact. This is the smallest change that makes ingestion debuggable.
- **`make tg-doctor`** — one command reporting: token present, `getMe`, webhook **not** set,
  `allowed_updates` as configured, per-chat bot status and `can_delete_messages`, unmapped
  administrators, chats with no primary assignment.
- **Counters in Postgres, not a metrics server.** Updates/day, classification latency, alert delivery
  outcomes are all rows we already store; the Overview page reads them with SQL. No Prometheus.

---

## 22. Testing Strategy

Follows Principle I — tests protect contracts, idempotency, business rules and metric arithmetic, and
are *not* written for CRUD or framework behaviour. All DB tests use `injaz_ai_test` through
`TEST_DATABASE_URL`; the session guard in `tests/conftest.py` already aborts otherwise. Laravel
continues to use `DatabaseTransactions` — never `RefreshDatabase`, `DatabaseMigrations`, or
`migrate:fresh`.

**New:** `apps/ai-api/tests/moderation/` and a `FakeTelegramTransport` (an `httpx.MockTransport`
scripting `getUpdates` responses), mirroring how the gateway tests already inject transports.

| Area                             | Test                                                                                         | Why it earns one                            |
| -------------------------------- | -------------------------------------------------------------------------------------------- | ------------------------------------------- |
| Update idempotency               | the same `update_id` twice → one row, one job                                                | Principle I: idempotency and retry safety   |
| Out-of-order arrival             | reply stored before its question → does **not** close the item                               | the metric would be silently wrong          |
| Full replay convergence          | replay all updates from row 1 → byte-identical derived state                                 | the whole D‑TG‑02 premise                   |
| Reply correlation                | direct reply vs next-group-message vs wrong thread vs another chat                           | core business rule                          |
| Burst grouping                   | 3 messages in 90 s → one item, `opened_at` = the first                                       | the §11 rule                                |
| Needs-response rules             | Arabic fixtures with and without `؟`, dialect forms, ack stoplist, emoji-only                | rule precision is the v1 product            |
| Assignment history               | event at T attributes to the owner at T, not the current owner                               | the reports' integrity                      |
| One current primary              | second concurrent primary insert → `IntegrityError`                                          | the partial unique index                    |
| FRT / median / P90               | fixed dataset with a known answer, including the "fewer than 10 samples" suppression         | metric arithmetic is business logic         |
| Ageing and expiry                | item at `max_age` → `expired`, excluded from FRT, counted unanswered                         | §13.5                                       |
| Incident state machine           | every legal transition, and that reaction/reply gives `acknowledged` **not** `resolved`      | the operator's explicit rule                |
| Enforcement attribution          | `chat_member` ban → action with `strength='enforcement'`, actor = `from`                     | the only attributable action Telegram gives |
| Alert dedupe                     | same rule + subject + repeat twice → one `alerts` row                                        | `ON CONFLICT` correctness                   |
| Alert destination safety         | no rule can resolve to a monitored student chat                                              | **the silence guarantee**                   |
| Classification structured output | `FakeLLMProvider` scripted valid / truncated / invalid-JSON                                  | gateway contract at this boundary           |
| Redaction                        | phone, email, URL, @username never reach the gateway payload                                 | privacy, and it is greppable                |
| Confidence routing               | below floor → review queue, no incident, no alert                                            | avoids false public accusations             |
| Reprocessing                     | new prediction → old preserved, `is_current` flipped, exactly one current                    | D‑TG‑15                                     |
| Correction                       | review never mutates the prediction row                                                      | §16 of the brief                            |
| Retention purge                  | past-window rows nulled, metrics intact, moderator names kept                                | GDPR-shaped behaviour                       |
| Supergroup migration             | `migrate_to_chat_id` → chat re-pointed, assignments and open items follow                    | the classic Telegram footgun                |
| Architecture boundary            | no telegram client import outside `app/providers/telegram/`; no moderation↔assessment import | mirrors the existing `httpx` gate           |
| n8n contract                     | `GET /v1/moderation/summary` shape + auth rejection                                          | contract test                               |

**Explicitly exempt (Principle I):** Filament resource CRUD, Eloquent model wiring, migration
column-type assertions, the poller's sleep loop, JSON serialisation of the health block.

**Real Ollama** stays behind `@pytest.mark.llm` (excluded by `addopts` today) plus one
`make smoke-moderation` script — matching D‑40. `make check` must keep passing **offline with Ollama
quit and with no Telegram token set**.

---

## 23. Integration With Existing InjazEdu Local AI

| Touchpoint                      | Change                                                                                      | Risk                                                  |
| ------------------------------- | ------------------------------------------------------------------------------------------- | ----------------------------------------------------- |
| `model_profiles.role`           | widen CHECK to include `moderation`; widen the `Role` literal                               | low — additive, one migration                         |
| `Gateway.generate_*`            | add `role: Role = "llm"` keyword                                                            | low — additive, default preserves every existing call |
| `app/infrastructure/models.py`  | new sibling `models_moderation.py` on the same metadata                                     | none                                                  |
| `app/infrastructure/logging.py` | whitelist a few `extra` keys                                                                | low, contained, tested                                |
| `app/infrastructure/config.py`  | ~12 new `MODERATION_*` / `TELEGRAM_*` settings, all optional with defaults except the token | none — mirrors the M1 gateway settings block          |
| `scripts/check.sh`              | two new architecture greps                                                                  | none                                                  |
| `scripts/scan_secrets.sh`       | bot-token shape                                                                             | none                                                  |
| `infra/docker-compose.yml`      | one new `ai-telegram` service, `mem_limit: 256m`                                            | low — measured stack is 0.27 GiB against a 5 GB cap   |
| `apps/ai-control`               | new navigation group + resources; `ModelProfileResource` gains `Platform`                   | low                                                   |
| `alembic/versions/`             | revisions `0003`…`0009`                                                                     | none — assessment milestones continue from `0010`     |
| Assessment domain               | **untouched**                                                                               | —                                                     |

**Alembic numbering.** Moderation takes `0003`…`0009`. If assessment M2 lands first it takes the next
free number; Alembic's `down_revision` chain is linear, so whichever ships first wins and the other
rebases its `down_revision`. Worth stating in the spec so two tracks do not both write `0003`.

---

## 24. Required InjazEdu-side Changes

**For v1: none. Nothing in TG-M0…TG-M10 requires a change inside `injazedu/`.** The domain is
self-contained in the AI Postgres.

Findings that shaped that conclusion:
- `courses.telegram_group` / `telegram_private` / `telegram_channel` exist, but they hold **invite
  URLs** (`nullable|url|max:255`), not numeric chat ids or usernames. **A bot cannot resolve an invite
  link to a `chat_id`.** So they cannot be used for automatic mapping.
- No Telegram bot integration exists in InjazEdu — zero matches for `chat_id`, `bot_token`, or any
  Telegram SDK.
- No Telegram user id is stored for any InjazEdu user.
- A `moderator` role **is** seeded (`RolesPermissionsSeeder.php:27`) but is referenced nowhere and has
  no permissions — effectively an unclaimed name.
- There is no internal/machine-to-machine API; that is master-plan M6 work.

Therefore group→course mapping in v1 is a **manual field in Filament** (`telegram_chats.injaz_course_id`,
no FK). With ~5 moderators and a few dozen groups this is minutes of work, once.

**Optional, post-v1 — write up as "Required InjazEdu Team Change" if the operator wants automatic
mapping and course-level moderation reporting:**

1. Add `courses.telegram_chat_id BIGINT NULL` (the numeric id, obtained once from our bot) — a
   nullable column and a migration.
2. Expose it on the M6 internal API: `GET /internal/ai/courses` returns `telegram_chat_id`.
3. Optionally add `users.telegram_user_id BIGINT NULL` so moderators map automatically.

All three are InjazEdu-team work under Principle III and are **not** prerequisites for anything in
this plan.

---

## 25. Milestones

Each is sized to be an independent Spec Kit feature. Every one is done only when: implementation
exists · tests exist and pass · docs/config updated · manual smoke test succeeds · no unrelated scope
added · known limitations written down.

---

### TG-M0 — Domain foundation *(~1 day)*

**Goal.** Create the moderation package boundary, configuration and guardrails — with no Telegram
call and no table.
**Why it exists.** Every later milestone depends on the boundary being mechanically enforced from the
start; retrofitting a package split after five milestones is how domains bleed into each other.
**Dependencies.** None (M0, M1 already merged).
**Repo areas.** `app/domain/moderation/`, `app/application/moderation/`, `app/providers/telegram/`
(skeleton), `app/workers/tasks/moderation/`, `app/infrastructure/{config,logging}.py`,
`scripts/check.sh`, `scripts/scan_secrets.sh`, `docs/plan/telegram/`.
**Database.** None.
**Backend.** Package skeleton; `Settings` gains `TELEGRAM_BOT_TOKEN` (optional — absent means the
poller does not start), `TELEGRAM_ALLOWED_UPDATES`, `MODERATION_BURST_GAP_S=90`,
`MODERATION_ITEM_MAX_AGE_S=86400`, `MODERATION_TEXT_RETENTION_DAYS=90`; `JsonFormatter` extra-key
whitelist; Arabic normaliser (`app/application/moderation/text.py`) + redactor.
**Filament.** None.
**n8n.** None.
**AI/model.** None.
**Tests.** Normaliser and redactor unit tests (Arabic fixtures); config validation; the two new
`check.sh` greps fail on a planted violation.
**Smoke.** `make check` passes with no token set.
**Acceptance.** A file importing a Telegram client outside `app/providers/telegram/`, or importing
assessment code from moderation, fails `make check`. Logs emit whitelisted extras and never text.
**Non-goals.** No Telegram network call, no table, no UI.

---

### TG-M1 — Telegram event ingestion *(~2–3 days)*

**Goal.** A silent bot's updates land durably, idempotently and in order.
**Why it exists.** Telegram keeps updates for 24 h and offers no history API. Until capture is
reliable, everything downstream is measuring a lossy stream.
**Dependencies.** TG-M0.
**Repo areas.** `app/providers/telegram/{client,models}.py`, `app/application/moderation/ingest.py`,
new `apps/ai-api/app/telegram_main.py` entrypoint, `infra/docker-compose.yml`, `Makefile`,
`alembic/versions/0003_moderation_ingest.py`.
**Database.** `telegram_updates`, `telegram_chats`, `ingestion_state`, `ingestion_gaps`.
**Backend.** Long-poll loop with `offset` durability, Redis lease `ai:tg:poll:lease`, 409/429/backoff
handling, gap detection, `process_update` actor stub that only marks `processed_at`; `/health` gains
`telegram_ingestion`; `make tg-doctor`.
**Filament.** None.
**n8n.** None.
**AI/model.** None.
**Tests.** Duplicate `update_id`; `update_id` jump → gap row; 409 handling; offset advance after a
partial batch failure; `my_chat_member` → chat row and `bot_status`; supergroup migration; health
block shape.
**Smoke.** Add the bot to one test group, post a message, `make psql` shows the raw row within
seconds; stop the container for 5 minutes, restart, the backlog drains.
**Acceptance.** 100 % of updates delivered while the ingester runs are stored exactly once; no
inbound port is opened; no message is ever sent to a student group.
**Non-goals.** No message parsing, no attention items, no UI.

---

### TG-M2 — Groups, users, messages and moderator ownership *(~3 days)*

**Goal.** Raw updates become typed messages; groups are opted in; moderators own groups over time.
**Why it exists.** Nothing can be attributed until "who was responsible when" is a stored fact.
**Dependencies.** TG-M1.
**Repo areas.** `app/application/moderation/{messages,assignments}.py`,
`app/workers/tasks/moderation/process_update.py`, `alembic/versions/0004_moderation_actors.py`,
`apps/ai-control/app/Filament/Resources/{TelegramChats,Moderators}/`.
**Database.** `telegram_users`, `telegram_messages`, `moderators`, `moderator_group_assignments`
(with the partial unique index).
**Backend.** Full `process_update` derivation for `message`, `edited_message`, `my_chat_member`;
`is_from_moderator` resolved at write time; `normalized_text` populated; assignment lookup
`responsible_at(chat, t)`; `drain_pending_updates`.
**Filament.** **Telegram Groups** resource (toggle `is_monitored`, bot status, last event, optional
`injaz_course_id`); **Moderators** resource with an Assignments relation manager whose reassign action
closes the incumbent row and opens the new one in one transaction; admin candidates proposed from
observed `chat_member` data.
**n8n.** None.
**AI/model.** None.
**Tests.** Message upsert idempotency; `is_from_moderator` snapshot survives a later promotion;
`responsible_at` at boundaries (`valid_from` inclusive, `valid_to` exclusive); two concurrent primaries
→ `IntegrityError`; un-monitored chats produce no messages; supergroup migration re-points assignments.
**Smoke.** Mark a group monitored, map yourself as its moderator, post as a student and as a
moderator, see both rows with the correct `is_from_moderator`.
**Acceptance.** For any event timestamp, Filament shows the moderator who was responsible **then**.
**Non-goals.** No attention items, no metrics, no AI.

---

### TG-M3 — Deterministic response tracking 🎯 *the first usable slice*

*(~3 days)*

**Goal.** A student question opens an attention item; a moderator reply closes it; Filament shows a
correct first-response time.
**Why it exists.** This is the product's core claim, proven with zero AI.
**Dependencies.** TG-M2.
**Repo areas.** `app/domain/moderation/attention.py` (pure rules),
`app/application/moderation/attention.py`, `app/workers/tasks/moderation/evaluate_attention.py`,
`alembic/versions/0005_moderation_attention.py`, Filament Live Attention Queue page.
**Database.** `attention_items`; `telegram_messages.attention_item_id`.
**Backend.** Rule set v1 (§13.1) as a pure, versioned function; burst grouping via a delayed actor;
response matching (§13.2); daily `expire_stale_items`.
**Filament.** **Live Attention Queue** page: oldest-first, live waiting time, dismiss, manual add,
reassign. Group and moderator columns for median/P90 FRT.
**n8n.** None.
**AI/model.** None.
**Tests.** The whole §22 block for burst, rules, correlation, FRT/median/P90, ageing.
**Smoke.** In one group: post `الكتاب مش ظاهر عندي` at 10:03, reply as moderator at 10:11 → the item
shows **8m**, `first_response_kind='direct_reply'`, attributed to the moderator responsible at 10:03.
**Acceptance.** A hand-computed first-response time matches the dashboard exactly, for a direct reply
and for a plain next-message reply. Unanswered count and oldest age are correct.
**Non-goals.** No incidents, no alerts, no AI, no violation handling.

---

### TG-M4 — Policy incidents *(~2–3 days)*

**Goal.** Violations become tracked incidents with the OPEN → ACKNOWLEDGED → RESOLVED lifecycle and
three separately-named timings.
**Why it exists.** The second half of the business problem, and it must exist before alerts.
**Dependencies.** TG-M3.
**Repo areas.** `app/domain/moderation/incident.py`, `app/application/moderation/incidents.py`,
`alembic/versions/0006_moderation_incidents.py`, Filament Incidents resource.
**Database.** `moderation_incidents`, `moderation_actions`.
**Backend.** Manual incident creation; action ingestion from `chat_member` (ban/restrict, actor from
`from`), `message_reaction`, and moderator replies; the state machine; `detected_at` vs `opened_at`.
**Filament.** **Incidents** resource with the six-question detail page (§17), an action timeline, and
the standing "Telegram does not report message deletion" footnote.
**n8n.** None.
**AI/model.** None.
**Tests.** Every legal and illegal transition; reaction/reply → `acknowledged` not `resolved`; ban →
`resolved` with the right actor; false-positive close excluded from missed; the three timings.
**Smoke.** Open an incident on a real message; react ✅ → ACKNOWLEDGED; restrict the sender →
RESOLVED with your name and the enforcement timing.
**Acceptance.** No path sets `resolved` from an acknowledgement alone; no field or label implies a
deletion was observed.
**Non-goals.** No AI detection, no alerts, no auto-moderation.

---

### TG-M5 — AI classification *(~3–4 days)*

**Goal.** Local AI proposes category / needs_response / needs_moderation / severity / confidence.
**Why it exists.** The rule set cannot see intent; this is the only place a model has an advantage.
**Dependencies.** TG-M4. **Gate:** TG-M3's rule-set precision must be measured first (§18.7), so the
model has a baseline to beat.
**Repo areas.** `app/application/moderation/classification.py`,
`app/prompts/moderation/classify_v1.md`, `app/workers/tasks/moderation/classify_message.py`,
`app/domain/model_profile.py`, `app/application/gateway/gateway.py` (additive `role=`),
`alembic/versions/0007_moderation_classification.py`, `app/scripts/seed_moderation_profile.py`.
**Database.** `message_classifications`; widen `ck_model_profiles_role`.
**Backend.** Pre-filter (skip service messages, bot messages, ack-stoplist, media-only, and messages
already answered) so most traffic never reaches the model; redact; call
`generate_structured(role="moderation")` with `max_output_tokens≈128`; store the prediction and link
it to the item/incident; confidence routing (§15.6); Dramatiq retries with backoff.
**Filament.** Category, confidence, model profile and prompt version shown on items and incidents.
**n8n.** None.
**AI/model.** Seed `ollama-gemma4-e2b-moderation`; `make smoke-moderation`.
**Tests.** `FakeLLMProvider` scripted valid / truncated / invalid; redaction; pre-filter skip rates;
confidence routing; a truncated response never yields a partial object; `make check` passes with
Ollama quit.
**Smoke.** `make smoke-moderation` classifies five real Arabic fixtures correctly.
**Acceptance.** Zero moderation code imports `httpx`/`ollama`/`openai`. Every prediction records its
profile, prompt version, taxonomy version and confidence. Ollama being down does not stop response
tracking.
**Non-goals.** No auto-moderation, no embeddings, no RAG, no model A/B.

---

### TG-M6 — Alerts *(~3 days)*

**Goal.** Configurable thresholds fire deduplicated alerts into a private moderators' group, with
actionable buttons.
**Dependencies.** TG-M5 (or TG-M4 with operator-opened incidents only).
**Repo areas.** `app/application/moderation/alerting.py`, `app/workers/tasks/moderation/{evaluate_alert_rules,deliver_alert}.py`,
the ticker in `telegram_main.py`, `app/providers/telegram/client.py` (`sendMessage`,
`answerCallbackQuery`, `editMessageText`), `alembic/versions/0008_moderation_alerts.py`,
Filament Alert Rules resource.
**Database.** `alert_rules`, `alerts`.
**Backend.** The 30 s tick under a Redis lease; rule evaluation with chat-override-first resolution;
`ON CONFLICT (dedupe_key)`; quiet hours; repeats; `callback_query` → `moderation_action`.
**Filament.** **Alert Rules** resource; alert history on the incident detail page.
**n8n.** None (deliberately — the callback returns through our own poller).
**AI/model.** None.
**Tests.** Dedupe; quiet-hours suppression recorded not dropped; `max_repeats`; chat override beats
global; **destination can never be a monitored student chat**; callback resolves the right incident;
delivery failure does not change incident state.
**Smoke.** Set "question waiting > 2 minutes"; leave a question unanswered; the private group receives
one alert (not two); press ✅ Handled; the incident resolves and the alert message is edited.
**Acceptance.** No SLA number appears in code. Zero messages sent to any monitored student group —
asserted by a test and verified by reading the group.
**Non-goals.** No email/WhatsApp, no escalation chains, no auto-moderation.

---

### TG-M7 — Performance dashboard *(~3 days)*

**Goal.** Overview, group performance and moderator performance, computed live in SQL.
**Dependencies.** TG-M6.
**Repo areas.** `app/application/moderation/metrics.py` (the SQL lives here, one function per metric,
unit-tested), Filament Overview + Team Performance pages and widgets.
**Database.** Read-only; add covering indexes only if a measured query exceeds ~300 ms.
**Backend.** Metric functions exactly as defined in §18, with the small-sample suppression rule.
**Filament.** Overview widgets; Team Performance; Group performance; period selector; ingestion-gap
banner; "unassigned groups" and "bot not admin" badges.
**n8n.** None.
**AI/model.** None.
**Tests.** Metric arithmetic against a fixed fixture with hand-computed answers, including
expired-item exclusion, attribution by historical assignment, and P90 suppression under 10 samples.
**Smoke.** Two weeks of seeded data produce numbers that match a hand-computed spreadsheet.
**Acceptance.** Every displayed number traces to a definition in §18. No composite score.
**Non-goals.** No materialised aggregates (§31), no exports, no scoring.

---

### TG-M8 — Classification review and reprocessing *(~2–3 days)*

**Goal.** Humans correct the AI without overwriting it; old messages can be re-labelled.
**Dependencies.** TG-M5, TG-M7.
**Repo areas.** `app/application/moderation/review.py`, `app/scripts/reprocess_classifications.py`,
`alembic/versions/0009_moderation_reviews.py`, Filament Classification Review page.
**Database.** `classification_reviews`.
**Backend.** Effective-label view; precision/recall metrics (§18.7); reprocess job producing a **diff
report** an operator applies or discards.
**Filament.** **Classification Review** queue: low-confidence and disputed items, Arabic-first, dense
and keyboard-driven (matching the master plan's §13 requirement); per-prompt-version accuracy.
**n8n.** None.
**AI/model.** Prompt v2 / taxonomy v2 become possible without data loss.
**Tests.** Review never mutates a prediction; exactly one `is_current`; reprocess is idempotent;
effective label resolution; precision/recall arithmetic.
**Smoke.** Correct a wrong label; the original prediction, model and confidence remain visible; run a
reprocess and see the diff before applying.
**Acceptance.** Full provenance for every label: prediction, profile, prompt version, confidence,
correction, reviewer, timestamp.
**Non-goals.** No automatic retraining, no model A/B harness.

---

### TG-M9 — n8n operational workflows *(~2 days)*

**Goal.** Give n8n a real, bounded job — and configure the container properly for the first time.
**Dependencies.** TG-M7.
**Repo areas.** `app/api/v1/moderation.py` (read-only summary endpoints + shared-secret auth),
`infra/docker-compose.yml` (n8n volume, `N8N_ENCRYPTION_KEY`, port), `infra/n8n/` (exported workflow
JSON — a directory the master plan claims exists but does not).
**Database.** None.
**Backend.** `GET /v1/moderation/summary?from&to&group_by` and
`GET /v1/moderation/open-items` behind `X-Moderation-Token` — the **first** authenticated endpoints
in this project.
**Filament.** An Integrations panel showing last digest run and webhook target (not a re-implementation
of n8n's editor).
**n8n.** Daily 08:00 digest → private moderators' group; weekly management summary. Both are pure
formatting over the API response.
**AI/model.** None.
**Tests.** Contract test on the summary shape; auth rejection without the header; a test asserting the
endpoints are read-only.
**Smoke.** `make automation-up`, import the workflow, trigger it manually, digest arrives.
**Acceptance.** Stopping n8n breaks nothing but digests. n8n holds no prompt, no threshold, no state.
**Non-goals.** n8n never receives Telegram updates, never computes a metric, never writes.

---

### TG-M10 — Reliability and privacy hardening *(~2 days)*

**Goal.** Retention, gap honesty and recovery become enforced behaviour rather than intentions.
**Dependencies.** TG-M9.
**Repo areas.** `app/workers/tasks/moderation/purge.py`, `app/application/moderation/gaps.py`,
runbook `docs/runbooks/tg-moderation.md`.
**Database.** No new tables; a partial index supporting the purge scan.
**Backend.** Nightly `purge_expired_text` in bounded batches; gap detection on startup and on 409;
reports flagged incomplete when the window overlaps a gap; replay-convergence script
(`app/scripts/replay_updates.py`) as an operator tool.
**Filament.** Retention status; gap list; "this report covers an incomplete window" banner.
**n8n.** None.
**AI/model.** None.
**Tests.** Purge nulls text and payloads but preserves metrics and moderator names; a report
overlapping a gap is flagged; replay from row 1 converges to identical derived state.
**Smoke.** Backdate a message past retention, run the purge, confirm the text is gone and the metric
row is intact.
**Acceptance.** No message text older than the retention window exists anywhere, including
`telegram_updates.payload` and `model_runs`.
**Non-goals.** No archival export, no encryption-at-rest change (that belongs to the master plan's
§18 backup work).

---

## 26. First Vertical Slice

**TG-M0 → TG-M1 → TG-M2 → TG-M3 is the right first target, and the operator's instinct to make it
AI-free is correct.**

```
one Telegram group, bot added as ADMIN
        ↓
silent long-poll ingester stores every update, idempotently
        ↓
group marked monitored · one moderator mapped and assigned
        ↓
10:03  student: «الكتاب مش ظاهر عندي»   → rule opens attention_item (opened_at = 10:03)
10:11  moderator replies                → item answered, first_response_kind = direct_reply
        ↓
Filament Live Attention Queue: 8m, attributed to the moderator responsible at 10:03
```

**Why AI-free is architecturally cleaner, not just cheaper.** The hard parts of this system are
correlation, attribution and idempotency — none of which a model helps with. Adding classification
first would mean debugging a probabilistic component and a deterministic one at the same time, and
every wrong number would have two possible causes. Proving the deterministic spine first also
produces the labelled dataset (operator dismissals and manual additions) that makes the model's value
*measurable* at TG-M5 rather than assumed.

Estimated **9–10 days** to a slice that already answers "who is slow, and where".

---

### 26.1 Local development and go-live

The whole plan runs on the operator's Mac with no tunnel, no public hostname and no inbound port —
that is a direct consequence of D‑TG‑01. Two constraints shape how local work is set up, and one of
them is a genuine trap.

**Two bots, always. One bot token has exactly one update consumer.** A laptop polling with the same
token as a live instance does not "share" updates — Telegram answers one of them with
`409 Conflict: terminated by other getUpdates request` and the two alternate, dropping updates on
both sides. So from TG-M1 onward there are two BotFather bots and two `.env` values:

| | Development | Live |
|---|---|---|
| Bot | `@InjazModerationDevBot` | `@InjazModerationBot` |
| `TELEGRAM_BOT_TOKEN` | dev token in `.env` | live token, live host only |
| Monitored chats | one throwaway test group | the real student groups |
| Alert destination | a private test group (or `filament_only`) | the private moderators' group |
| Database | `injaz_ai` locally, `injaz_ai_test` for tests | the live `injaz_ai` |

Both bots must be **administrators** in their own groups (§5.3). The dev group needs two or three
accounts in it — yours plus one acting as "student" — which is enough to exercise every rule in §13.

**A sleeping laptop is an ingestion gap.** Telegram holds undelivered updates for at most 24 hours
and offers no history API (§5.2), so:

- lid closed overnight → the backlog drains on wake, `ingestion_gaps` records the window, nothing is
  lost;
- lid closed Friday to Monday → **that weekend is permanently unrecoverable**, and every report
  overlapping it is flagged incomplete (§10.2).

That is acceptable against a dev group. It is **not** acceptable for the TG-M3 pilot on a real
student group, where a gap looks identical to "the moderator was fast" — the metric silently
under-counts. Before pointing the live bot at a real group, pick one:

1. run the poller under `caffeinate -s` and keep the machine awake and plugged in; or
2. move only the `ai-telegram` container to an always-on host (it needs Postgres and Redis, not
   Ollama — it makes no model calls); or
3. accept nightly gaps explicitly and configure `alert_rules.quiet_hours` to match, so overnight
   items are not counted as unanswered.

Option 1 is fine for a two-week pilot; option 2 is the answer before the system is used for anything
management acts on.

**Most development needs no Telegram at all.** `make check` must pass with the token unset and Ollama
quit (§22), so the rule set, burst grouping, response correlation, metric arithmetic and the incident
state machine are all developed against `FakeTelegramTransport` fixtures. Real Telegram is needed only
for each milestone's manual smoke test, and real Ollama only for `make smoke-moderation`.

**Go-live checklist — nothing here is architectural.**

```
[ ] live bot created; added as ADMIN to every group to be monitored
[ ] make tg-doctor         → getMe ok · webhook NOT set · allowed_updates correct
                             · bot is administrator in every chat · no unassigned monitored chat
[ ] live TELEGRAM_BOT_TOKEN in the live .env only; dev token never on the live host
[ ] dev poller STOPPED before the live poller starts   ← otherwise both get 409
[ ] telegram_chats.is_monitored enabled per group, deliberately, one at a time
[ ] moderators mapped and assignments opened with a real valid_from
[ ] alert destination = the private moderators' group; verify no rule resolves to a student chat
[ ] alert thresholds reviewed with management (they are data, not code)
[ ] MODERATION_TEXT_RETENTION_DAYS confirmed; purge job scheduled
[ ] host stays awake / always-on decision made (above)
[ ] one full smoke pass in the live pilot group before enabling the rest
```

No DNS record, no TLS certificate, no `setWebhook` call, no firewall change. Going live is a token,
a host and a set of `is_monitored` flags.

**What does not carry over.** Dev events stay in dev. Production starts empty, and because Telegram
retains nothing beyond 24 hours there is no backfill to do on either side — the first day of live
data is genuinely day one.

---

## 27. Risks

| Risk                                                       | Likelihood  | Impact                                                                               | Mitigation                                                                                                                         |
| ---------------------------------------------------------- | ----------- | ------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------- |
| Bot is not made admin in every group, or loses admin later | **High**    | Silent, total loss of `chat_member` and `message_reaction`; partial loss of messages | `make tg-doctor` + a dashboard badge + a `group_silent` alert. This is the single most likely way the system quietly stops working |
| Ingester down > 24 h                                       | Medium      | **Permanent, unrecoverable data loss**                                               | Restart policy, health block, `ingestion_gaps`, honest report flagging                                                             |
| Rule set v1 has poor recall on dialect Arabic              | **High**    | Under-counted questions                                                              | Measure it from day one (§18.7); operator "add missed item" is a first-class action, not an afterthought                           |
| A 4 B local model is weak on Saudi/Egyptian dialect        | **High**    | Wrong labels, false accusations                                                      | Confidence floor routes to review instead of alerting; humans correct; `qwen3:8b` can be activated for the moderation role alone   |
| Moderators experience it as surveillance                   | **High**    | Gaming (✅ without acting), resentment                                                | No composite score; the assistive queue and alerts ship *with* the metrics; acknowledgement ≠ resolution is explained to the team  |
| Attribution gap: silent deletion is invisible              | **Certain** | A fast, quiet moderator looks worse than a slow, loud one                            | Stated everywhere it appears; enforcement and confirmation are separate metrics; never a single number                             |
| Alert fatigue                                              | Medium      | Alerts ignored                                                                       | Quiet hours, `max_repeats`, dedupe, per-group thresholds                                                                           |
| Two Alembic tracks collide on a revision number            | Medium      | Broken migration chain                                                               | Reserve `0003`–`0009`; state the rebase rule in the spec (§23)                                                                     |
| Scope creep into auto-moderation                           | Medium      | Destroys the reaction-time metric                                                    | Non-goal, stated in §4 and in every milestone's non-goals                                                                          |
| Student PII accumulates in backups                         | Medium      | Compliance exposure                                                                  | 90-day purge; `pg_dump` encryption raised as an open item (§28)                                                                    |
| Bot token leaked in a spec or log                          | Low         | Full group access                                                                    | `scan_secrets.sh` shape rule; token never stored in a table                                                                        |

---

## 28. Open Questions

1. **Private moderators' group** — does one exist, and will the bot be added to it? TG-M6 needs a
   destination chat id. (Fallback: Filament-only alerts.)
2. **Bot admin rights** — will `can_delete_messages` be granted even though v1 never deletes? Granting
   it now avoids re-promoting later; not granting it is also fine and is the more conservative choice.
3. **`pg_dump` encryption** — the master plan's §18 nightly encrypted dump has no milestone. This
   domain adds student PII; should backup hardening be pulled forward?
4. **Moderator consent** — is the team being told what is measured? This affects adoption more than
   any technical choice, and the "assistance not surveillance" framing only works if it is stated.
5. **Which group is the pilot** for TG-M3, and who is its moderator?
6. **Quiet hours** — are there hours when no alert should fire, and is any coverage expected outside
   them? (Affects whether overnight items count as "unanswered".)
7. **Alert language** — Arabic only, or bilingual?

None blocks TG-M0–TG-M2. Items 1, 2 and 5 are needed before TG-M3's smoke test; item 6 before TG-M6.

---

## 29. Recommended Decisions

| ID          | Decision                                                                                                                                                                                                                                                                                                     | Rationale (short)                                                                                                                                                           |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **D‑TG‑01** | **Dedicated `ai-telegram` long-polling process** inside `apps/ai-api`. Not n8n, not a webhook. A webhook adapter behind the same provider interface stays possible if a tunnel ever exists                                                                                                                   | Outbound-only, so architecture rule §5.1‑5 stands unamended; Telegram enforces single-consumer semantics; n8n today is an unconfigured stub and raw-event loss is permanent |
| **D‑TG‑02** | Raw updates **append-only and immutable**; every derived row is rebuildable and a full replay must converge                                                                                                                                                                                                  | The only way taxonomy changes, model changes and bug fixes stay non-destructive                                                                                             |
| **D‑TG‑03** | `message` → `attention_item` with a **90 s burst rule**. No `conversations` table in v1                                                                                                                                                                                                                      | Covers the observed multi-message question at a fraction of the complexity                                                                                                  |
| **D‑TG‑04** | Time-versioned `moderator_group_assignments` with primary/backup and a partial unique index on the current primary                                                                                                                                                                                           | Reports must reflect who was responsible *then*; re-deriving history later is impossible                                                                                    |
| **D‑TG‑05** | Needs-response by a small **versioned rule set** plus operator override in v1; AI proposes from TG-M5                                                                                                                                                                                                        | Proves the metric before adding a probabilistic input, and produces the labelled data that justifies the model                                                              |
| **D‑TG‑06** | Response = any moderator's message in the same chat after `opened_at`, by direct reply or by being the next moderator message in the thread. **Reactions do not close questions**                                                                                                                            | The student's wait ends whoever answers; a ✅ is not an answer                                                                                                               |
| **D‑TG‑07** | Reply/reaction ⇒ **ACKNOWLEDGED**. Ban/restrict, alert "Handled", or Filament resolve ⇒ **RESOLVED**. False positives ⇒ **CLOSED_FALSE_POSITIVE**. Metrics named `acknowledgement_time`, `handling_confirmation_time`, `observed_enforcement_time`. **No deletion is ever claimed; no deletion probe in v1** | Telegram exposes no group-deletion update and no actor; the design measures what is actually observable                                                                     |
| **D‑TG‑08** | 7 categories (`QUESTION_COURSE`, `QUESTION_ACCESS`, `COMPLAINT`, `CHITCHAT`, `SPAM_OR_AD`, `ABUSE`, `OTHER`) + 2 booleans + severity + confidence, versioned by `taxonomy_version`                                                                                                                           | Fewer, more reliable labels; `COMPETITOR_AD` splits at v2 once real labelled data exists                                                                                    |
| **D‑TG‑09** | Alerts to a **private moderators' group** with inline buttons, delivered by the worker; Filament queue always available as fallback                                                                                                                                                                          | Keeps student groups silent; the button's `callback_query` returns through our own poller                                                                                   |
| **D‑TG‑10** | n8n owns **scheduled digests and external glue only**, and is optional through TG-M8                                                                                                                                                                                                                         | It cannot receive updates (single-consumer), and business logic in visual nodes is untestable                                                                               |
| **D‑TG‑11** | **90 days** for message text, `telegram_updates.payload` and non-moderator identity; metrics forever. Redaction happens **before** the gateway                                                                                                                                                               | Reports stay exact; the database does not become a permanent PII archive; payload capture cannot become a privacy regression                                                |
| **D‑TG‑12** | **No pgvector, no embeddings** in this domain in v1                                                                                                                                                                                                                                                          | Nothing in the requirements needs semantic similarity. Near-duplicate spam detection, if ever wanted, starts with a hash                                                    |
| **D‑TG‑13** | **No RAG.** Classification of a short message needs no retrieval                                                                                                                                                                                                                                             | Adding it would couple this domain to the assessment corpus for no measurable gain                                                                                          |
| **D‑TG‑14** | **New `role='moderation'`** in the existing `model_profiles`; one CHECK widened, one Literal widened, one additive `role=` keyword on the gateway. Lane stays `llm`                                                                                                                                          | Independent model choice and free per-profile cost accounting, with no new abstraction                                                                                      |
| **D‑TG‑15** | Predictions immutable; `is_current` partial unique index; reprocessing inserts and flips, then emits a **diff for operator approval**                                                                                                                                                                        | Historical reports stay reproducible; a model change never silently rewrites the past                                                                                       |
| **D‑TG‑16** | **No composite moderator score in v1**                                                                                                                                                                                                                                                                       | Small samples, unmeasured rule precision and an unresolvable attribution gap would make it misleading and gameable                                                          |

---

## 30. Suggested Spec Kit Breakdown

**Documentation location.** A sibling track, not an edit to the existing plan:

```
docs/plan/telegram/
├── telegram-moderation-intelligence.md  ← this document, the track's plan of record
├── telegram-api-capabilities.md         ← §5, kept current as the Bot API changes
└── metric-definitions.md                ← §18, the single source for every number in the UI

specs/
├── 001-m0-foundation/          (existing, untouched)
├── 002-m1-model-gateway/       (existing, untouched)
├── 003-tg-m0-moderation-foundation/
├── 004-tg-m1-telegram-ingestion/
├── 005-tg-m2-groups-and-ownership/
├── 006-tg-m3-response-tracking/
└── …one directory per TG milestone
```

Each spec directory follows the established house style exactly: `spec.md` (with `## Overview`,
prioritised user stories, `### Out of Scope (deferred to named later milestones)`, `## Dependencies`),
`plan.md` (with the five numbered Constitution Check questions, `## Post-Design Constitution Re-Check`,
`## Requirement → Design Traceability`, `## Phase Status`), `research.md`, `data-model.md`,
`contracts/`, `checklists/requirements.md`, then `tasks.md` from `/speckit-tasks`.

**Numbering.** `FR-001…` restarts per milestone (as M0 and M1 do). `SC-001…` likewise. Decisions use
the **`D-TG-NN`** namespace rather than continuing `D-41…`, because this is a separate domain with a
separate decision log — the prefix keeps ids globally unique, which is what the existing convention
actually requires.

**Contracts worth writing** (mirroring `gateway-interface.md`'s role as *the* durable contract):
- `004-.../contracts/telegram-provider.md` — the provider Protocol, the update model shapes, the
  error taxonomy, retry/429 semantics, and **the verified-capabilities table from §5**.
- `006-.../contracts/attention-rules.md` — the rule set v1, the burst rule, and the response-matching
  rules, as the definition later milestones code against.
- `009-.../contracts/moderation-api.md` — the n8n-facing endpoints and their auth.

**Cross-references to existing plans — additive only, no meaning changed:**
- `CLAUDE.md`: while a TG spec is active, its "Active feature" block points there; the existing M1
  block moves under a "Previous milestone" line, exactly as M0's did.
- `docs/plan/core/final-…-plan.md`: **do not edit the M0–M13 table.** Add one line under §20
  noting that a parallel Moderation Intelligence track is planned in
  `docs/plan/telegram/telegram-moderation-intelligence.md`, and one note under §15 that n8n's Telegram responsibilities in
  that track are digests only. Both are pointers, not redefinitions.
- The constitution needs **no amendment**. Every principle already holds: risk-proportional tests,
  `_test` isolation, `injazedu/` untouched, operator-owned Git, and scope discipline.

---

## Verification

How to prove the plan's first slice end to end, once implemented:

```bash
make doctor && make up && make migrate          # existing
make tg-doctor                                  # NEW: token, getMe, no webhook set,
                                                #      allowed_updates, per-chat bot admin status
make health | python3 -m json.tool              # telegram_ingestion block present and "ok"

# in the pilot Telegram group (bot added as ADMIN):
#   post a student question, wait, reply as the moderator
make psql
  select id, sent_at, is_from_moderator, left(normalized_text, 40) from telegram_messages
   order by sent_at desc limit 5;
  select opened_at, first_response_at,
         extract(epoch from (first_response_at - opened_at)) as frt_s,
         first_response_kind, status
    from attention_items order by opened_at desc limit 5;

# open http://localhost:8080/admin → Moderation Intelligence → Live Attention Queue
#   the displayed waiting time must equal frt_s, and the responsible moderator must be
#   the one assigned at opened_at (change the assignment afterwards and re-check — it must not move)

make check                                      # must pass OFFLINE, Ollama quit, no token set
TELEGRAM_BOT_TOKEN= make check                  # proves the poller is optional
```

Replay convergence (TG-M10): `python -m app.scripts.replay_updates --from-id 1 --into injaz_ai_test`
must reproduce byte-identical `attention_items` and `moderation_incidents`.


