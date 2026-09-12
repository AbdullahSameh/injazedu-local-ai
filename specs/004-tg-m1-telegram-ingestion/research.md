# Phase 0 Research: TG-M1 — Telegram Event Ingestion

**Feature**: `specs/004-tg-m1-telegram-ingestion` · **Date**: 2026-09-09
**Spec**: [spec.md](./spec.md) — FR-001…FR-045, SC-001…SC-024
**Source plan**: `docs/plan/telegram/telegram-moderation-intelligence.md` §5, §7.1, §9, §10.1–10.3, §20, §21, §25 TG-M1
**Decision namespace**: `D-TG-29`…`D-TG-45`, continuing TG-M0's `D-TG-17`…`D-TG-28`

---

## 0. The three findings that changed the design

Everything else in this document is ordinary design work. These three are not: each was found by
running something, each contradicts a reasonable reading of the spec or the source plan, and each
would have produced a silent failure rather than an error.

### ⚠ Finding 1 — After a week of silence, Telegram picks a **random** next `update_id`, and a strictly-forward offset then stalls capture forever

The Bot API's `Update` documentation says, verbatim:

> "Update identifiers start from a certain positive number and increase sequentially. […] **If there
> are no new updates for at least a week, then identifier of the next update will be chosen randomly
> instead of sequentially.**"

And `getUpdates`' `offset` parameter, verbatim:

> "Identifier of the first update to be returned. Must be greater by one than the highest among the
> identifiers of previously received updates. **By default, updates starting with the earliest
> unconfirmed update are returned.** […] The negative offset can be specified to retrieve updates
> starting from −offset update from the end of the updates queue. **All previous updates will be
> forgotten.**"

Put those together against the spec as written and there is a hole:

- **FR-019** says *"The confirmed position MUST never move backwards."*
- A randomly chosen next identifier can be **lower** than the last one stored.
- The poller always asks with `offset = last_update_id + 1`, and Telegram returns only updates whose
  identifier is **at or above** that offset.
- Therefore the new, lower-numbered update is **never returned**. The poll succeeds, returns an empty
  list, reports no error, and does so forever. Capture is dead and every health signal is green.

This is the worst failure shape this milestone can have: not a crash, not a gap that gets recorded,
but an ingester that reports itself perfectly healthy while receiving nothing. It is also invisible
in testing, because it needs a **week of total silence across every chat the bot is in** to trigger —
a dev bot over a holiday, or the pilot group during an exam break.

**The recovery is to omit `offset` entirely**, which the documentation defines as "updates starting
with the earliest unconfirmed update" — so the low-numbered update is returned and capture resumes.
It is emphatically **not** a negative offset: that one says "all previous updates will be forgotten",
which discards the unconsumed backlog and is a data-loss operation.

Consequences, taken up in D-TG-33: FR-019 gains one documented exception, the reset is recorded as
its own gap reason (it is *not* a loss — writing an `update_id_jump` marker here would be dishonest
in the other direction, claiming missing data where none is missing), and a stall detector triggers
the re-sync. This corrects a requirement in the approved spec rather than merely implementing it, so
it is flagged for the operator in `plan.md` rather than absorbed silently.

### ⚠ Finding 2 — The natural place for the ingestion health probe **fails `make check`**

Probe 4 planted the files the source plan's §25 TG-M1 "Repo areas" row implies, then ran the gate's
own boundary checks against them. Result:

```
apps/ai-api/app/application/probes/telegram_ingestion.py:2:
    from app.infrastructure.models_moderation import telegram_updates
>>> CHECK 2 FAILS (reverse rule) <<<
```

`app/application/probes/` is assessment-side infrastructure and sits inside check 2's scope
(`app/domain`, `app/application`, `app/providers`, `app/api`). The moment the probe reads a
moderation table, TG-M0's own boundary rule — correctly — rejects it.

This is the boundary working, not a defect in it. But it means "add a probe next to the other four
probes" is not available, and the two obvious escapes are both wrong:

- **Adding an allowlist entry** weakens the rule TG-M0 exists to establish, and the spec's own edge
  case forbids it: *"adding moderation rules must not silently widen it."*
- **Renaming the module** so the grep stops matching (`models_tg.py` instead of `models_moderation.py`)
  passes the gate by evading it and leaves assessment code genuinely free to import moderation tables.

The answer is D-TG-31: compose the probe at the **composition root**, which the gate already exempts
by directory and the constitution already treats as the wiring layer. It also falls out better than
the alternative — the probe becomes *optional at composition time*, which is exactly FR-007's
"no credential means capture does not run".

Worth noting what did **not** fail: `app/api/v1/health.py` importing a module *named*
`telegram_ingestion` is fine, because the rule matches on the imported path containing `moderation`
or `providers.telegram`, not on the word "telegram". The failure is specifically the probe reading a
moderation table.

### ⚠ Finding 3 — `ComponentReport` **silently discards** an ingestion block passed as an ad-hoc keyword

Probe 3, against the real class:

```
P3 unknown field ACCEPTED, dumped as:
  {'status': 'ok', 'required': False, 'latency_ms': 0, 'detail': '', 'gateway': None}
P3 model_config: {'frozen': True}
```

`ComponentReport` is `frozen=True` but does **not** set `extra="forbid"`, so pydantic v2's default
applies: an unrecognised keyword is accepted without error and then dropped. A probe written as
`ComponentReport(status=OK, required=False, ingestion={...})` raises nothing, returns a valid report,
and produces a health payload with **no ingestion data in it**. Every assertion of the shape
`report["status"] == "ok"` passes.

That is FR-034 and SC-013 failing while looking green. The block must be a **declared field**,
exactly as `gateway` already is (D-TG-32), and the test must assert the block's contents rather than
the component's status.

---

## 1. Ingestion process and placement

### D-TG-29 — A dedicated `ai-telegram` compose service with its own entrypoint

**Decision.** One new singleton container running `apps/ai-api/app/telegram_main.py`, sharing the
`ai-api` image, `mem_limit: 256m`, depending on `postgres` and `redis` only. It runs the long-poll
loop and nothing else. No inbound port is declared.

**Rationale.** The source plan's §7.3 splits responsibility explicitly: the poller *durably stores
and advances the offset*; **all interpretation happens in the worker**. Keeping them in one process
would mean an interpretation bug can crash the process holding the offset — the one thing that must
not be lost. Separation is also what makes FR-020's backlog drain meaningful: the poller keeps
capturing while the worker is stopped.

`app/telegram_main.py` sits at the `app/` root, alongside `app/main.py`. Probe 4 confirms that
directory is outside check 2's scope, so the entrypoint may wire moderation and assessment
infrastructure together as a composition root — the same exemption `app/main.py` and `app/workers/`
already rely on.

**Alternatives rejected.** *A thread inside `ai-api`* — the API restarts on every deploy and holds
the offset hostage to unrelated code. *A Dramatiq actor that re-enqueues itself* — long polling for
30 s inside a worker thread occupies a slot the worker needs, and Dramatiq's retry semantics would
fight the offset's own recovery. *n8n* — cannot be a second consumer of the token (§5.2), and the
plan's D-TG-10 already settles this.

### D-TG-30 — One multi-row insert per batch; enqueue only what it returns

**Decision.** Each poll issues a single
`INSERT … VALUES (…), (…), … ON CONFLICT (bot_id, update_id) DO NOTHING RETURNING update_id, id`,
and schedules interpretation only for the rows it returns.

**Rationale — measured (probe 1, 1b).** Against the real Postgres 16:

```
INSERT … VALUES (1,100) ON CONFLICT DO NOTHING RETURNING id;   →  (0 rows)
INSERT … VALUES (1,100),(1,101),(1,102) ON CONFLICT DO NOTHING
                                        RETURNING update_id;   →  101, 102
```

`RETURNING` yields **only genuinely inserted rows**, so FR-010 and FR-011 are the same statement
rather than a read-then-write with a race in the middle. One round trip per batch, not one per event.

**Alternatives rejected.** *`SELECT` then `INSERT`* — a duplicate delivered concurrently slips
through the gap. *`ON CONFLICT … DO UPDATE`* — would rewrite an append-only row, violating FR-009.
*Per-event inserts* — 100 round trips where one suffices, and no atomic batch boundary.

### D-TG-31 — The ingestion probe is composed at the composition root

**Decision.** The probe lives at `app/application/moderation/ingestion_probe.py` (inside the
moderation boundary, where reading moderation tables is permitted). `app/main.py` — exempt by
directory — constructs it during startup and stores the callable on `app.state`. `app/api/v1/health.py`
adds a `ProbeSpec` for it **only when that state attribute is present**, and imports nothing from
moderation.

**Rationale.** See Finding 2. This keeps the boundary intact with no allowlist entry and no evasive
renaming, and it makes the block's presence conditional on composition — matching FR-007, where an
absent credential means the component simply is not wired.

**Alternatives rejected.** *Allowlist entry in `check.sh`* — weakens the rule TG-M0 exists to create;
forbidden by the spec's own edge case. *Renaming `models_moderation.py`* — passes the gate by
defeating it. *A moderation-owned HTTP route separate from `/health`* — a second health surface for
the operator to know about, contradicting §21's "extend the existing report rather than adding a
stack".

### D-TG-32 — `ingestion` is a declared field on `ComponentReport`

**Decision.** Add `ingestion: dict[str, Any] | None = None` beside the existing
`gateway: dict[str, Any] | None`, and assert the block's **contents** in tests, never just the
component's status.

**Rationale.** See Finding 3 — the alternative is a silently empty block. Mirroring `gateway` also
keeps one shape for "a component with a detail block" rather than inventing a second mechanism.

**Alternative rejected.** *Setting `extra="allow"` on the model* — turns every typo into a new field
and makes the payload's shape unreviewable. *`extra="forbid"`* would at least be loud, but it is a
behaviour change to a shared model that assessment code also constructs; declaring the field is
additive and contained.

---

## 2. Position, ordering and the reset

### D-TG-33 — ⚠ FR-019 gains exactly one documented exception: an identifier reset

**Decision.** The confirmed position moves backwards in **one** circumstance, and only after it is
detected and recorded:

1. **Detect a stall.** Polls are succeeding, returning empty, and no event has been stored for longer
   than a configured window (default **8 days** — Telegram's own threshold is "at least a week", so
   the detector sits just beyond it).
2. **Re-sync by omitting `offset` entirely.** Never a negative offset: the documentation states that
   forgets all previous updates, which would discard an unconsumed backlog.
3. **Adopt whatever identifier comes back**, even a lower one, and record an `ingestion_gaps` row
   with reason `update_id_reset`.

`update_id_reset` is deliberately **not** counted as missing data. Nothing was lost — Telegram simply
renumbered — and marking the window "incomplete" would be dishonest in the opposite direction from
the one this milestone guards against.

**Rationale.** See Finding 1. Without this, a week of quiet permanently silences a green-looking
ingester.

**Alternatives rejected.** *Trusting FR-019 literally* — produces the stall. *Always polling with no
offset* — re-delivers every unconfirmed update on every poll and never confirms consumption, so the
backlog never clears. *A negative offset to "get the latest"* — documented to forget all previous
updates; a data-loss operation dressed as a recovery. *Detecting the reset by comparing timestamps* —
`date` is per-event, not per-poll, and an empty poll carries none.

### D-TG-34 — A recycled identifier after a reset is accepted as a residual risk, not engineered away

**Decision.** The uniqueness key stays `(bot_id, update_id)`. After a reset, a genuinely new event
whose randomly chosen identifier collides with one already stored would be silently dropped by
`ON CONFLICT DO NOTHING`. This is recorded as a known limitation, and every reset writes a gap row
so a human can see when the window of exposure began.

**Rationale — measured (probe 9).** The collision is real: `INSERT (1,500) ON CONFLICT DO NOTHING`
against a stored `(1,500)` returns zero rows and stores nothing, whether or not the payloads differ.
It requires a full week of silence **and** a random landing inside an already-used range.

The obvious fix — an `id_epoch` column incremented on each reset, added to the unique key — was
considered and rejected, because it **trades a rare failure for a more likely one**: idempotency, the
milestone's single most important property, would then depend on the epoch counter never advancing
spuriously. A detection bug that bumps the epoch turns every redelivered update into a duplicate row,
which corrupts every count downstream. Principle I says protect idempotency; adding a second variable
to its key does the opposite.

**Flagged for the operator** in `plan.md` rather than buried here: this is a deliberate acceptance of
a small data-integrity risk, and the reviewer should agree with it explicitly.

### D-TG-35 — Payload stored as `JSONB`: semantically complete, not byte-identical

**Decision.** `payload JSONB NOT NULL`, holding the whole update. The spec's "exactly as delivered"
(FR-008) means **semantically complete**, and the contract says so in as many words.

**Rationale — measured (probe 2, 2b).** JSONB round-trips a real Telegram update losslessly for every
purpose this domain has — Arabic text, emoji, nested `chat`/`from`/`reply_to_message`, and the
negative supergroup identifier all survive, and `payload->'message'->>'text'` extracts cleanly. But
JSONB is **not** byte-preserving:

```
'{"b":1,"a":2}'::jsonb  →  {"a": 2, "b": 1}     -- key order not preserved
'{"a":1,"a":2}'::jsonb  →  {"a": 2}             -- duplicate keys collapsed
```

Neither matters here: JSON object key order is insignificant by definition, and the Bot API emits no
duplicate keys. JSONB buys operator-readable `->>` extraction in `make psql` and indexable content
later. Recording the caveat is what keeps FR-008's "verbatim" from being read as a byte-level promise
the storage does not make.

**Alternative rejected.** *`json` or `text`* — preserves the bytes, but every extraction becomes a
parse, `make psql` inspection becomes unreadable, and no index is possible. Byte fidelity has no
consumer in this domain; TG-M10's replay convergence is over *derived state*, not over payload bytes.

### D-TG-36 — Enqueue after commit; the pending index, not the queue, is the source of truth

**Decision.** Interpretation is scheduled **after** the storing transaction commits. If the process
dies between commit and enqueue, the row simply stays pending and `drain_pending_updates` picks it up.
The partial index `WHERE processed_at IS NULL` is authoritative; the queue message is an optimisation
that makes the common case fast.

**Rationale — measured (probe 8).** The partial index serves the drain efficiently at realistic
volumes, and `FOR UPDATE SKIP LOCKED` lets a drain run concurrently with live capture without either
blocking the other:

```
EXPLAIN … WHERE processed_at IS NULL ORDER BY update_id LIMIT 100
  →  Limit → Sort → Index Scan using ix_p8_pending on p8
SELECT … FOR UPDATE SKIP LOCKED LIMIT 3  →  996, 997, 998
```

Enqueueing *inside* the transaction is the opposite mistake and a classic one: Dramatiq writes to
Redis immediately, so a worker can dequeue and look for a row whose transaction has not committed —
or has rolled back and never will. Committing first makes the only failure mode "a message we did not
send", which the pending index already covers.

**Alternative rejected.** *Transactional outbox* — the pending index already **is** the outbox, for
free, because `processed_at` has to exist anyway.

---

## 3. Failure handling and the platform contract

### D-TG-37 — Two layers of single-consumer enforcement, and a bounded stand-down

**Decision.** Same machine: a Redis lease `ai:tg:poll:lease`, claimed with `SET … PX … NX`, reusing
the fencing-token pattern `app/application/gateway/lanes.py` already proved. Across machines: the
platform's own `409`, which is authoritative. On `409` the consumer backs off with increasing delay
and, after **5 consecutive** rejections (configurable), **stops polling entirely**, writes a
`conflict_409` gap row, reports itself stood down, and requires an explicit restart. A successful poll
resets the counter.

**Rationale.** The 5-count and the stand-down are the operator's clarification, recorded in the spec's
Clarifications section, and the reasoning is in FR-004a: two consumers that keep retrying *alternate*,
so both lose events while both look healthy. The Redis lease is not redundant with the `409` — it
stops the same-machine case (a stray `docker compose up` while one is already running) before a single
event is lost, whereas the `409` only fires after Telegram has already terminated someone's poll.

Redis holds a **lock**, never a fact — §7.3's rule, and the reason the stand-down counter and the gap
row live in Postgres.

### D-TG-38 — A closed error taxonomy for the provider, mirroring the gateway's

**Decision.** `app/providers/telegram/errors.py` defines a small closed set with a `retryable`
class-var, in the exact shape of `app/application/gateway/errors.py`: `TelegramUnreachableError`
(retryable), `TelegramTimeoutError` (retryable), `TelegramRateLimitedError` (retryable, carries
`retry_after`), `TelegramConflictError` (not retryable — stand down), `TelegramAuthError` (not
retryable — a revoked or malformed credential), `TelegramRejectedError` (not retryable).

**Rationale.** The gateway's D-27 reasoning applies unchanged: retry logic must branch on a flag, never
on message text. Reusing the shape means one mental model for two providers. Probe 5 confirms the
mapping source is stable — `httpx.ReadTimeout` → `TimeoutException` → `TransportError` — so connect,
read and pool failures are distinguishable without string matching.

`429` carries the wait in `parameters.retry_after` in the response body, and honouring it is the
provider's job alone (FR-005) — no caller may implement its own backoff.

### D-TG-39 — Long poll at 30 s server-side, 35 s client read timeout

**Decision.** `getUpdates(timeout=30)`, with an `httpx.Timeout(connect=5, read=35)`.

**Rationale — measured (probe 5).** `httpx.Timeout(5.0, read=35.0)` resolves to
`connect=5.0, read=35.0, write=5.0, pool=5.0`. The read timeout **must exceed** the server-side
long-poll window, or the client aborts every single poll at the moment Telegram is legitimately
holding the connection open — producing a permanent stream of retryable timeouts that looks exactly
like an unreachable platform. Five seconds of headroom absorbs the round trip.

### D-TG-40 — `limit=100` is the API's own ceiling, not an arbitrary number

**Decision.** `getUpdates(limit=100)`, and the configurable ceiling FR-005a requires defaults to 100.

**Rationale.** The Bot API documents `limit` as *"Values between 1-100 are accepted"*, default 100.
The operator's clarified batch ceiling and the platform's maximum are therefore the same number, which
removes the question of whether a larger batch would be better — none is available. FR-005b's drain
constraint is satisfied comfortably: at 100 events per poll and a poll every few seconds, a weekend's
backlog at the expected volume (low hundreds per day, D-TG-45) drains in seconds, far inside the 24 h
retention window.

### D-TG-41 — `allowed_updates` is re-asserted every poll, and late arrivals of unwanted kinds are harmless

**Decision.** Send the configured `allowed_updates` on every `getUpdates` call, and store any kind
that arrives regardless.

**Rationale.** The documentation warns: *"this parameter doesn't affect updates created before the
call to getUpdates, so unwanted updates may be received for a short period of time."* Because FR-012
already stores unrecognised kinds verbatim rather than discarding them, this is a non-event — the
transitional updates land in the spine like everything else. Re-asserting the list on every call also
makes FR-006's "re-asserted on every restart" free rather than a startup step that can be skipped.

The two kinds that must be listed explicitly — `chat_member` and `message_reaction` — are not
delivered by default and additionally require the bot to be an administrator (§5.1). Requesting them
from day one costs nothing; discovering at TG-M4 that months of them were never requested costs
everything, because there is no history API to recover them from.

### D-TG-42 — Bot identity via `getMe`, retried indefinitely, never cached-fallback

**Decision.** Resolve the numeric bot id from `getMe` before storing anything; on failure, stay up,
retry with increasing delay, and never fall back to a previously stored identity.

**Rationale.** The operator's clarification, recorded in the spec. The identity is half the
idempotency key, so nothing may be stored without it; and a swapped credential must never write events
under the previous bot's identity. Staying up rather than exiting is what makes a laptop that boots
before its Wi-Fi connects recover unattended.

---

## 4. Records and discovery

### D-TG-43 — Chat rows come from any chat-bearing update; standing comes only from `my_chat_member`

**Decision.** Upsert a `telegram_chats` row from any update that carries a chat. `bot_status` is
written **only** from `my_chat_member`, and a chat first seen another way records
`bot_status = 'unknown'`.

**Rationale.** A bot already present in a group before capture started never emits a
standing-change update, so relying on `my_chat_member` alone leaves those groups invisible — and they
are precisely the groups a pilot starts with. Recording `unknown` rather than assuming `member` keeps
FR-028 honest; the source plan's §5.1 makes administrator status the load-bearing prerequisite, and
guessing it is exactly the thing that would hide a coverage failure.

### D-TG-44 — Supergroup migration links both directions and re-points nothing yet

**Decision.** On `migrate_to_chat_id` / `migrate_from_chat_id`, write both columns on both rows so the
pair is navigable from either side. TG-M1 re-points **no** derived state, because none exists yet.

**Rationale.** The plan's §20.2 calls this "the classic Telegram footgun" and requires assignments and
open items to follow the migration — but those tables arrive in TG-M2 and TG-M3. Capturing the link
now is what makes that later re-pointing possible; doing the re-pointing now would be scope the spec
explicitly defers.

### D-TG-45 — Scale, and what is therefore *not* built

**Decision.** Design for one dev group now, a few dozen groups and ~5 moderators at rollout, low
hundreds of events per day. No partitioning, no separate archive table, no queue-depth autoscaling, no
metrics server.

**Rationale.** The operator's clarification. §21 is explicit that counters are rows in Postgres read
by SQL, not a Prometheus deployment. At this volume the append-only spine is a few hundred thousand
rows a year — a table, not a data-engineering problem. Recording the number matters so that a later
milestone measuring something very different knows which assumption it is departing from.

---

## 5. Deliberately not in TG-M1

Recorded so a reviewer can see each was considered and declined, not overlooked:

| Not built | Why not |
|---|---|
| A webhook adapter | No tunnel exists, no inbound port is permitted (D-TG-01), and `getUpdates` and a webhook are mutually exclusive. The provider interface leaves room for one. |
| Message parsing, sender resolution, `is_from_moderator` | TG-M2. The interpreting step here only marks a row handled — that is what makes capture correctness provable in isolation. |
| A screen to mark a group monitored | TG-M2. The flag exists and defaults to off; the operator sets it with one `UPDATE` for the smoke test. |
| The text purge job | TG-M10. Only the *shape* that makes purging possible (`payload_purged_at`) ships here. |
| Replay convergence proof | TG-M10 — there is no derived state to converge on yet. |
| Multi-bot operation | The records are keyed by `bot_id` so it stays possible; running two is not in scope. |
| Retry middleware for the interpreting actor | The actor does one `UPDATE`. A retry policy belongs with the milestone that adds work worth retrying. |
| An `id_epoch` in the uniqueness key | D-TG-34 — trades a rare failure for a likelier one. |

---

## 6. Probe log

Every number in this document came from one of these. All are reproducible; `quickstart.md` §6 gives
the commands.

| # | Probe | Result |
|---|---|---|
| 1 | `ON CONFLICT DO NOTHING RETURNING` on a duplicate | 0 rows returned, 1 row stored → D-TG-30 |
| 1b | Same, 3-row batch with 1 conflict | returned `101, 102` only → one statement serves FR-010 **and** FR-011 |
| 2 | JSONB round-trip of a real update (Arabic, emoji, nested, negative chat id) | lossless for every extraction this domain needs |
| 2b | JSONB key order and duplicate keys | **order not preserved, duplicates collapsed** → D-TG-35's honesty caveat |
| 2c | Supergroup id magnitude in `BIGINT` | fits with room to spare |
| 3 | `ComponentReport(… ingestion={…})` | **silently accepted and dropped** → Finding 3, D-TG-32 |
| 4 | Planted the source plan's natural TG-M1 layout, ran the gate | **check 2 fails** → Finding 2, D-TG-31 |
| 5 | `httpx.Timeout`, `MockTransport`, exception hierarchy | read timeout must exceed the long poll → D-TG-39; `MockTransport` serves as the stand-in |
| 6 | Bot API `getUpdates` docs — `limit`, `offset`, retention, `allowed_updates` | `limit` max **100** → D-TG-40; the offset wording → Finding 1 |
| 7 | Bot API `Update` docs — `update_id` sequencing | **"chosen randomly"** after a week → Finding 1, D-TG-33 |
| 8 | Partial index `WHERE processed_at IS NULL` + `FOR UPDATE SKIP LOCKED` | index scan used; concurrent claim works → D-TG-36 |
| 9 | Recycled `update_id` against the unique key | silently dropped → D-TG-34's accepted risk |
| 10 | `alembic heads` | head is `0002`; **`0003` is free** |

**Unresolved `NEEDS CLARIFICATION`: none.** The spec's four clarifications were resolved with the
operator before this phase; Findings 1–3 were resolved by decision here, with Findings 1 and the
D-TG-34 risk acceptance escalated to the operator in `plan.md`.
