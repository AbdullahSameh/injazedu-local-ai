# Contract: Ingestion Guarantees

**Status**: the rules every later milestone in this domain may rely on and must not weaken.
**Owner**: `apps/ai-api/app/application/moderation/ingest.py`
**Binding on**: TG-M1…TG-M10.

Where `contracts/telegram-provider.md` says what the platform does, this file says what **we
promise** about it. Three guarantees, one non-promise, and the exact conditions under which each
holds.

---

## G1 — Exactly once, for everything delivered while capture is running

**Promise.** Every update the platform delivers while the capture process is running is stored
exactly once, and schedules exactly one unit of interpretation.

**Mechanism.** `UNIQUE (bot_id, update_id)`, and a single statement per batch:

```sql
INSERT INTO telegram_updates (bot_id, update_id, update_type, chat_id, payload)
VALUES (…), (…), …
ON CONFLICT (bot_id, update_id) DO NOTHING
RETURNING id, update_id;
```

Interpretation is scheduled **only for the rows this returns** (probe 1b: a 3-row batch with one
conflict returns the two new identifiers). Idempotency is the database's, not the application's
(FR-045) — there is no read-then-write window for a concurrent duplicate to slip through.

**Holds even when**: the same update is delivered twice; a batch is retried whole; the process dies
mid-batch; two batches overlap.

**Does not hold when**: capture is not running (that is G3's job), or after an identifier reset has
recycled an identifier (§NP1).

---

## G2 — The confirmed position never runs ahead of what is stored

**Promise.** The offset confirmed to the platform is always at or behind the highest successfully
stored identifier. Consumption is confirmed **only after** durable storage.

**Why it is the sharpest rule here.** Reversing the order loses events *silently*: the platform
considers them consumed and never redelivers, while nothing in the system records that they existed.
Every other failure in this milestone is loud by comparison.

**The order, exactly:**

1. `INSERT … RETURNING` (above)
2. **`COMMIT`**
3. `UPDATE ingestion_state SET last_update_id = <highest stored>, last_success_at = now()`
4. schedule interpretation for the returned rows
5. next poll uses `offset = last_update_id + 1`

**Steps 2 and 3 before step 4, deliberately** (D-TG-36). Scheduling inside the transaction lets a
worker dequeue and look for a row whose transaction has not committed — or has rolled back and never
will. Committing first makes the only failure mode "a message we did not send", and G3 covers that.

**Consequences the caller must not undo:**

- The store being unavailable means the position does **not** advance. The platform redelivers.
- A partial batch advances only as far as the last row actually stored.
- The position moves backwards in exactly one case: §5 of the provider contract, recorded first.

---

## G3 — Nothing is lost because a *consumer* stopped

**Promise.** Uninterpreted rows are never abandoned. If interpretation was never scheduled — a crash
between commit and enqueue, a broker outage, a worker that was down — the row is still found and
handled.

**Mechanism.** `ix_telegram_updates_pending (received_at) WHERE processed_at IS NULL` is the
authoritative work list; the queue message is an optimisation. `drain_pending_updates` claims in
`update_id` order with `FOR UPDATE SKIP LOCKED` so it can run alongside live capture (probe 8).

**The pending index is the outbox.** No separate outbox table exists, because `processed_at` has to
exist anyway.

---

## G4 — A window we could not observe is recorded as such

**Promise.** Any period during which events could have occurred but could not have been received is
written to `ingestion_gaps` with a reason, and is never silently removed or merged.

**The five reasons, and which ones mean data is missing:**

| Reason | Trigger | Data missing? |
|---|---|---|
| `downtime` | silence since `last_success_at` exceeded **5 minutes** on restart | only if > 24 h |
| `update_id_jump` | next identifier > `last_update_id + 1`, and the silence was **under** a week | **yes, permanently** |
| `conflict_409` | the stand-down threshold was reached | only if > 24 h |
| `unrecoverable_24h` | any window longer than the platform's retention | **yes, permanently** |
| `update_id_reset` | stall detected, re-synced with the offset omitted | **no** — Telegram renumbered |

**The 5-minute minimum** (FR-025) exists so ordinary poll cycles and quick redeploys write nothing. A
marker that appears on every report means nothing on any report.

**`update_id_reset` is not a loss, and must not be rendered as one.** Marking that window incomplete
would be dishonest in the opposite direction from the one this domain guards against — claiming
missing data where none is missing. TG-M7 reads `unrecoverable` and the reason, not merely the
presence of a row.

**A jump under a week is a real loss; a jump after a week is a renumbering.** The same observable
(`update_id` higher than expected) means two different things depending on `last_event_at`, and
conflating them either invents losses or hides them. This is a contract test, not a comment.

---

## NP1 — What is **not** promised

Stated plainly, in the source plan's "the platform will not pretend" spirit.

1. **Nothing about windows when capture was not running.** Beyond 24 h the events are gone from
   Telegram and no design recovers them.
2. **Nothing before the bot joined a chat.** There is no history API.
3. **No deletion detection, ever**, and no deleting actor. Not a gap to be closed later.
4. ⚠ **Not exactly-once across an identifier reset.** After a reset (provider contract §5) a
   genuinely new event whose randomly chosen identifier collides with one already stored is silently
   dropped by `ON CONFLICT`. Accepted deliberately (D-TG-34): the alternative — adding an epoch
   counter to the uniqueness key — makes G1, the most important guarantee here, depend on that
   counter never advancing spuriously. Every reset writes a gap row, so the exposure window is
   visible. Requires a full week of total silence **and** a random landing inside a used range.
5. **No ordering promise about arrival.** Order is recovered from `update_id` and from the platform's
   own `date`; the machine clock is used only to record when capture happened (FR-013).
6. **Not byte-identical storage.** `JSONB` is semantically complete; key order is not preserved and
   duplicate keys collapse (probe 2b, D-TG-35). No consumer needs byte fidelity.

---

## G5 — Silence and containment

**Promise.** For the whole of TG-M1: the bot sends nothing, and the machine listens for nothing.

| Rule | Enforced by |
|---|---|
| No message, reaction, deletion, ban or restriction | No such method exists on the provider (provider contract §8) |
| No inbound port | The capture service declares none; it is a poller |
| The platform's inbound delivery is not configured | `tg-doctor` asserts `getWebhookInfo` reports no URL; `setWebhook` is not implemented |
| One consumer per credential | Redis lease `ai:tg:poll:lease` (same machine) + the platform's `409` (across machines) |
| No message text in any log line | The gate's check 4, over the moderation directories |
| The credential never reaches the database or a log | It is read from the environment by the provider only; the secret scan covers the repository |

Redis holds **a lock, never a fact** (§7.3). The stand-down counter, the position and every gap live
in Postgres.

---

## G6 — Capture is optional, and absence is a supported state

**Promise.** With no credential configured the system starts, readiness is unchanged, and the full
quality gate passes offline. Absence means one thing only: capture is not running.

Three states must be **distinguishable** in the health report (FR-007c):

| State | Meaning |
|---|---|
| no credential configured | supported, healthy, deliberate |
| credential present, platform unreachable | transient; retrying; recovers unattended |
| credential present, credential rejected | operator action needed |

Collapsing any two of these is a contract violation. The offline quality gate depends on the first
being indistinguishable from healthy, and an operator debugging the third must not be told the second.

---

## Requirement coverage

| Guarantee | Requirements |
|---|---|
| G1 | FR-008, FR-010, FR-011, FR-012, FR-045 · SC-001, SC-002 |
| G2 | FR-015…FR-019 · SC-003, SC-004 |
| G3 | FR-020, FR-032, FR-033 · SC-021 |
| G4 | FR-021…FR-025 · SC-005…SC-008 |
| G5 | FR-001…FR-005b, FR-037…FR-040 · SC-015, SC-017, SC-018 |
| G6 | FR-007…FR-007d · SC-013, SC-016, SC-023 |
| NP1 | FR-023 and the spec's inherited-limitation record |
