# Phase 0 Research: TG-M3 — Deterministic Response Tracking

**Feature**: `specs/006-tg-m3-response-tracking`
**Date**: 2026-09-22
**Inputs**: `spec.md` (FR-001…FR-084, SC-001…SC-025, 3 clarifications) ·
`docs/plan/telegram/telegram-moderation-intelligence.md` (§7.2, §10.7, §11, §12, §13, §17, §18.1–18.3,
§18.7, §19.2, §20, §21, §22, §25 TG-M3, §26) · `docs/runbooks/tg-operator-prerequisites.md` (§C TG-M3,
§D, §F) · `.specify/memory/constitution.md` · the merged TG-M0, TG-M1 and TG-M2 code

Decision ids continue the domain's log at **D-TG-70** (TG-M2 ended at D-TG-69).

---

## §0 — Four findings

Each was produced by a probe against the live stack, the installed framework or the merged code, and
each would have shipped as a **silent** failure: no exception, no failing test, a dashboard that looks
plausible and is wrong in the direction that flatters the team.

### ⚠ Finding 1 — Seven of the source plan's own rule-set literals can never match, because they do not survive the normaliser.

FR-019 requires matching against `normalized_text`. The source plan's §13.1 prints the interrogative
and support list in ordinary Arabic orthography. Probe 1 ran TG-M0's `normalize()` over that list
exactly as the plan prints it:

```
CHANGES  'متى'   -> 'متي'      CHANGES  'إيش'    -> 'ايش'
CHANGES  'أين'   -> 'اين'      CHANGES  'أبغى'   -> 'ابغي'
CHANGES  'كيفية' -> 'كيفيه'    CHANGES  'مشكلة'  -> 'مشكله'
CHANGES  'متأخر' -> 'متاخر'
  7 of 31 change under normalize()
  1 of 10 ack-stoplist entries change: 'شكراً' -> 'شكرا'
```

`normalize()` step 5 folds `أ إ آ ٱ → ا`, `ة → ه`, `ى → ي`, and step 4 strips tashkeel
(`app/application/moderation/text.py:28-41`). A literal written with any of those characters is
compared against text in which they no longer exist, so **the comparison is false for every message,
forever**. There is no error and no failing assertion — the rule simply never fires. Among the seven
are `متى` and `مشكلة`, two of the most common question signals in a support group, and `أين`, the
plan's own example of an interrogative that carries no question mark.

The same fold makes the stoplist over-inclusive in one place and that is fine: `شكراً` and `شكرا`
collapse to the same entry.

**Resolution (D-TG-74).** Every literal in the rule set is stored **already normalised**, and a unit
test asserts `normalize(literal) == literal` for every entry of both lists. That test is the point:
fixing the seven known instances leaves the class of bug alive for the eighth literal somebody adds in
six months. The self-check makes it impossible to add one.

Probe 1 also measured two things the rule set can rely on: `؟` (U+061F) and `?` both survive NFKC
unchanged, so FR-017's question-mark signal is safe; and step 7 collapses three-or-more repeated
*letters* to one (`شكراااااا → شكرا`) but leaves repeated **emoji** untouched (`👍👍👍👍` is unchanged,
because an emoji is not a letter). The "bare emoji" stoplist rule must therefore handle runs itself.

### ⚠ Finding 2 — The unique constraint the source plan specifies for attention items collides across groups, and the idempotent insert form swallows the collision.

Source plan §10.7 specifies the anchor as `UNIQUE (telegram_message_id)`. Telegram numbers messages
**per chat**, from 1 upward — TG-M2's own table already knows this and constrains
`uq_telegram_messages_chat_msg` on `(telegram_chat_id, message_id)`
(`alembic/versions/0004_moderation_actors.py:121`). Probe 2 built the plan's stated constraint and ran
the two inserts:

```
INSERT INTO probe_items (telegram_chat_id, telegram_message_id) VALUES (-1001, 2);   -- INSERT 0 1
-- second group, its own message #2, using the ON CONFLICT DO NOTHING form idempotency requires:
INSERT INTO probe_items (telegram_chat_id, telegram_message_id) VALUES (-1002, 2)
  ON CONFLICT DO NOTHING;                                                            -- INSERT 0 0
SELECT count(*) → 1

-- the same insert without ON CONFLICT:
ERROR:  duplicate key value violates unique constraint "probe_items_telegram_message_id_key"
DETAIL:  Key (telegram_message_id)=(2) already exists.
```

`INSERT 0 0`. No error, no retry, no log line, one row where there should be two. FR-009 requires
repeated judgement to be harmless, which forces `ON CONFLICT … DO NOTHING` — and that is precisely the
form that converts this collision from a crash into **a question in the second group that silently
never opens**. Because message ids restart near 1 in every chat, this lands on the *earliest* messages
of every group after the first: the pilot's first day, and the second group the operator ever measures.

**Resolution (D-TG-71).** The anchor is `UNIQUE (telegram_chat_id, telegram_message_id)`, matching
TG-M2's precedent exactly. **This corrects the source plan's §10.7 as written**, and is recorded as a
correction rather than a preference.

### ⚠ Finding 3 — The delayed judgement exists only in Redis, and this stack's Redis is not durable. A lost delayed message is a question that never happened.

Source plan §7.2 schedules `evaluate_attention` for `sent_at + 90 s`. Probe 3 read how Dramatiq 2.2.1
implements that: `RedisBroker.enqueue(message, delay=…)` rewrites the message onto the `.DQ` queue with
an `eta` and stores it in Redis. Nothing about the pending judgement exists in Postgres.

Probe 4 then measured this stack's Redis:

```
infra/docker-compose.yml:25   image: redis:7-alpine       (no volume declared, no command override)
CONFIG GET appendonly  →  no
CONFIG GET save        →  3600 1   300 100   60 10000
```

No AOF. RDB only, and at those thresholds a quiet instance can go **up to an hour** between snapshots.
`/data` is an anonymous volume, so an ordinary `make down` keeps it — but `make down-hard` is
`docker compose down -v` and removes it, and any ungraceful stop loses everything written since the last
snapshot.

The failure is silent in every direction. TG-M1's gap detection watches the *Telegram* poll, not the
queue, so no gap is recorded. The messages are safely in `telegram_messages` — they just never become
items. The dashboard reports fewer questions asked, which reads as a quiet hour.

**Resolution (D-TG-72, D-TG-80).** The delayed message becomes an **optimisation**, and Postgres holds
the authoritative work list — which is not a new invention here but TG-M1's own established pattern,
stated in its code: *"`ix_telegram_updates_pending (received_at) WHERE processed_at IS NULL` is the
authoritative work list; the dramatiq message `store_batch` schedules is only an optimisation"*
(`app/workers/tasks/moderation/drain_pending_updates.py:3-5`). TG-M3 adds
`telegram_messages.attention_evaluated_at` with a matching partial index, and a sweep claims what is due
and unjudged. A NULL `attention_item_id` cannot serve, because it cannot distinguish *not yet judged*
from *judged and correctly declined*.

### ⚠ Finding 4 — The stack has no periodic execution of any kind. The source plan's "30 s tick" was never built.

FR-038 needs a scheduled ageing step and Finding 3's sweep needs a recurring trigger. Source plan §7.3
assigns "the 30 s tick" to `ai-telegram`. Probe 5 searched for it: there is no `periodiq`, no
APScheduler, no cron, no Laravel scheduler container, and no `cron`/`schedule`/`tick` symbol anywhere in
`app/workers/` or `app/providers/telegram/`. `app/telegram_main.py:161-175` is
`while True: await _poll_once(...)` and nothing else; `drain_pending_updates.send()` fires **once**, at
startup (`:164`). TG-M1 shipped no recurring work, so nothing revealed the absence.

Probe 5 also measured what is available for free: `get_updates` is called with
`timeout_s = TELEGRAM_POLL_TIMEOUT_S` (default 30), so the loop body runs at least every ~30 seconds
whether or not any message arrives. That **is** the tick the source plan describes; it has simply never
been used.

**Resolution (D-TG-86).** The poll loop gains one throttled call per iteration that **enqueues** the
ageing step and the sweep and computes nothing, behind a Redis `SET NX EX` tick lease shaped exactly
like the existing `hold_poll_lease` (`app/application/moderation/ingest.py:99-124`) — so a fast group
that returns the long-poll every second does not flood the queue. This keeps §7.3's component
boundary intact: `ai-telegram` still never writes derived state, exactly as it already only sends
`drain_pending_updates`. The consequence, accepted and recorded: **with no credential configured the
poller does not run, so nothing expires** — which is harmless, because with no credential nothing is
captured either, and every automated test drives the steps directly.

---

## §1 — Probes

Ten probes. Postgres 16.15, Dramatiq 2.2.1, Filament v5.7.8, Laravel 12.69.1, Livewire 4.4.3. Every
schema probe ran inside `BEGIN … ROLLBACK` against `injaz_ai_test` on temporary tables — no development
data touched, nothing left behind (Principle II).

| # | Question | Result |
|---|---|---|
| 1 | Do the source plan's §13.1 literals survive `normalize()`? | **No.** 7 of 31 interrogative/support entries and 1 of 10 stoplist entries change → **Finding 1**. `؟` and `?` both survive; repeated *letters* collapse to one, repeated **emoji** do not |
| 2 | Is §10.7's `UNIQUE (telegram_message_id)` safe across groups? | **No.** Second group's message #2 → `INSERT 0 0` under `ON CONFLICT DO NOTHING`, `duplicate key` without it → **Finding 2** |
| 3 | How does Dramatiq 2.2.1 hold a delayed message? | `RedisBroker.enqueue(…, delay)` → `.DQ` queue + `eta`, entirely in Redis, max 7 days. Nothing in Postgres → **Finding 3** |
| 4 | Is this stack's Redis durable? | **No.** `appendonly no`; `save 3600 1 / 300 100 / 60 10000`; anonymous volume that `make down-hard` deletes → **Finding 3** |
| 5 | Does any periodic execution exist? | **None.** No scheduler dependency, no cron, no tick. `telegram_main.py:161` is a bare `while True` poll; `drain_pending_updates.send()` runs once at startup. But the long-poll bounds the loop at ~30 s → **Finding 4** |
| 6 | What does `percentile_cont` return below the sample floor, and on no rows? | 4 samples `[60,120,180,900]` → median `150`, p90 `684` — an authoritative-looking number from four points, which is exactly what FR-066 suppresses. **0 rows → NULL, not 0**: the panel must distinguish "no data" from "zero seconds" |
| 7 | Can the panel poll a table without a reload? | **Yes.** `vendor/filament/tables/src/Table/Concerns/CanPollRecords.php:11` — `poll(string\|Closure\|null $interval = '10s')`. FR-056 is satisfiable with no custom JavaScript |
| 8 | How many consumers can match responses concurrently? | **Eight.** `WORKER_PROCESSES=2 × WORKER_THREADS=4` (`.env.example:36-37`), all pulling `default`. Rule (b)'s "close only the oldest" is a read-then-write race between them (D-TG-81) |
| 9 | Is `0005` free, and is there a precedent for the write-once guarded update? | **Yes.** `alembic_version` = `0004`, `0005`–`0009` reserved by TG-M2's plan. TG-M2's `apply_edit` establishes the targeted-`UPDATE`-only idiom; `drain_pending_updates` establishes `FOR UPDATE SKIP LOCKED` claiming |
| 10 | Will the panel's role reach the new table without a `GRANT`? | **Yes.** `infra/postgres/initdb/01-roles.sql:20`'s `ALTER DEFAULT PRIVILEGES FOR ROLE ai_migrator` already covers `ai_control` in both databases — confirmed by TG-M2's probe 9 and unchanged |

**Not probed, deliberately**: Filament table rendering and action wiring, Eloquent casting, Dramatiq
delivery semantics beyond the delay mechanism, and Livewire's polling transport. All are framework
behaviour, exempt under Principle I.

---

## §2 — Decisions

### Schema and migration

**D-TG-70 — Revision `0005_moderation_attention` creates one table and alters one.** Creates
`attention_items`; alters `telegram_messages` with `attention_item_id` (FK, NULL) and
`attention_evaluated_at` (timestamptz, NULL). Down-revision `0004`, confirmed head by probe 9. No other
table is touched. *Alternative rejected:* a separate `attention_evaluations` queue table to hold pending
judgements — two columns on a row that already exists answer the same question, and a queue table would
need its own idempotency, its own cleanup and its own index.

**D-TG-71 — The anchor is `UNIQUE (telegram_chat_id, telegram_message_id)`.** Finding 2. This corrects
the source plan's §10.7 and matches `uq_telegram_messages_chat_msg`. Together with an FK onto
`telegram_messages (telegram_chat_id, message_id)` it makes an item that anchors on a message which was
never stored impossible. *Alternative rejected:* the plan's literal single-column unique — measured to
silently discard the second group's first question.

**D-TG-72 — `telegram_messages.attention_evaluated_at` is the authoritative work list, with a partial
index `WHERE attention_evaluated_at IS NULL`.** Finding 3. It is set for every message a judgement
considered, whether or not an item resulted, which is the distinction `attention_item_id` alone cannot
make. The index is partial so it shrinks to nothing in steady state, exactly like TG-M1's pending index.

**D-TG-73 — `status`, `source` and `first_response_kind` are `String` columns with `CHECK`
constraints, not Postgres enum types.** The established idiom in this schema
(`ck_assignment_role`, `ck_telegram_messages_sender`). Adding a value to a CHECK is an ordinary
migration; adding one to an enum type is not transactional in the same way. *Alternative rejected:*
native enums, for no gain and a harder `0006`.

**D-TG-74 — The rule set is a pure function whose literals are stored normalised, guarded by a
self-check test.** Finding 1. Lives in `app/domain/moderation/attention.py` — the domain layer, no I/O,
no clock, no session — so it is exercised without a database. The test asserting
`normalize(literal) == literal` for every entry is not a formality; it is the mechanism that keeps the
finding fixed. *Alternative rejected:* normalising the literals at import time — it would hide the
problem rather than prevent it, and would make the module's source stop being a readable statement of
what the rules are (FR-020).

### The rule set

**D-TG-75 — The acknowledgement stoplist is evaluated first and wins outright.** FR-015 before FR-016.
A student replying `تمام` to a moderator satisfies FR-017's "direct reply to a moderator" signal, so
without precedence every thanks in every group opens an item. Bare-emoji detection handles runs itself,
since probe 1 showed `normalize()` does not collapse repeated emoji.

**D-TG-76 — `rule_version` is an integer constant in the same module as the literals, and changing any
literal bumps it.** FR-012. The version is stored on the item, so a figure produced under version 1 is
never re-explained by version 2 — which is the whole basis of §18.7's precision measurement.

**D-TG-77 — A mention of a moderator and a direct reply to a moderator's message are question signals
that need no text at all.** FR-017. Both are resolvable from TG-M2's stored facts: the reply target is
`reply_to_message_id`, and a mention is matched against the mapped moderators' usernames. Both are known
false-positive sources and are exactly what the dismissal count measures.

**D-TG-78 — "Bare emoji or ≤ 2 characters" is measured on the normalised text after stripping
whitespace and emoji runs.** FR-015. A single `👍`, a sticker with no caption, and `ok` all land in the
stoplist; `ليش` (3 characters) does not.

### Burst formation and judgement

**D-TG-79 — A burst is keyed on `(telegram_chat_id, telegram_user_id, message_thread_id)` with a gap of
at most `MODERATION_BURST_GAP_S`, ordered by `sent_at`, and anchored on the earliest member.** FR-001 …
FR-005. `message_thread_id IS NULL` matches only other NULLs, which in SQL means the comparison is
written `IS NOT DISTINCT FROM`, not `=` — FR-002's "no thread is itself a distinct thread value". A
message sent by a `sender_chat` rather than a person cannot start a burst at all (FR-013).

**D-TG-80 — Judgement is scheduled per message with a delay, and the delayed message is an optimisation
only.** Finding 3 and D-TG-72. `evaluate_attention.send_with_options(delay=burst_gap_ms)` is the fast
path; the sweep claims anything with `attention_evaluated_at IS NULL AND sent_at < now() - burst_gap`.
Each run recomputes the burst from the database and anchors on its earliest member, so repeated runs
converge on one item (FR-009) — which is why a burst that is still growing when the first delayed
message fires needs no look-ahead. *Alternative rejected:* trying to schedule exactly one judgement at
the burst's true end — that instant is not knowable until the burst is already over.

**D-TG-81 — Judgement and response matching take a per-chat advisory lock for the duration of one
transaction.** Probe 8: eight concurrent consumers, and rule (b) — "close only the oldest open item" —
is a read-then-write race. `pg_advisory_xact_lock(hashtext(chat_id))` serialises per chat and releases
on commit or rollback with no cleanup path to get wrong. It costs nothing when groups are quiet and
serialises only within one group when they are not. *Alternative rejected:* `SELECT … FOR UPDATE SKIP
LOCKED` on the item rows alone — it prevents two closers from writing the same row but not from each
selecting a *different* "oldest", which is the failure that would silently credit one message with two
items.

### Response matching

**D-TG-82 — One matcher, two entry points.** FR-027. `match_response(chat, message)` is called when a
moderator message is derived, and `match_existing_responses(item)` is called at the moment an item opens
(FR-026), both delegating to the same predicate. The second exists because a moderator can answer inside
the settle window, before the item exists — the session's first clarification.

**D-TG-83 — Rule (a) is evaluated before rule (b), and rule (b) is restricted to the oldest open item.**
FR-025, FR-026, FR-027. A direct reply resolves to a specific item through the burst membership recorded
on `telegram_messages.attention_item_id`; a plain group message resolves to
`ORDER BY opened_at ASC LIMIT 1` over open items in the same chat and thread, inside D-TG-81's lock.

**D-TG-84 — Ties are broken by `(sent_at, message_id)`.** FR-034. Two moderators answering in the same
second is not hypothetical in a busy group, and "whichever transaction committed first" is not a
defensible answer to "who answered". Both components come from Telegram, so the result is the same on
every re-derivation.

**D-TG-85 — Closing is a guarded `UPDATE … WHERE id = :id AND status = 'open'`.** FR-033, FR-035. The
guard is the concurrency control and the write-once rule in one clause: a second closer updates zero
rows and stops, a dismissed or expired item is never closed, and re-running the matcher over the same
messages changes nothing. This mirrors TG-M2's `apply_edit` — a targeted UPDATE of named columns, never
an upsert.

**D-TG-86 — The 30-second tick lives in the poll loop, behind a Redis tick lease, and only enqueues.**
Finding 4. One `SET NX EX` on `ai:tg:tick:lease` per loop iteration; on success, send
`expire_stale_items` and `sweep_unjudged_bursts`. `ai-telegram` computes nothing and writes no derived
state, preserving §7.3's boundary exactly as the existing `drain_pending_updates.send()` does.
*Alternatives rejected:* adding a scheduler dependency (new infrastructure for two recurring jobs,
Principle V); the Laravel scheduler (the panel must run no bulk job, and no scheduler process exists);
`dramatiq` periodic middleware (not installed, and it would put the schedule in Redis — the state
Finding 3 is about).

**D-TG-87 — Expiry is one guarded `UPDATE … WHERE status = 'open' AND opened_at < now() - max_age`.**
FR-037, FR-038. Set-based, idempotent by its own predicate, no row loop, and safe to run every 30
seconds even though the ceiling is 24 hours.

### Edits and re-derivation

**D-TG-88 — An edit re-judges the burst from its current text and opens an item only when the burst has
none.** The session's second clarification, FR-022 … FR-024. Implemented by clearing
`attention_evaluated_at` on the edited message so the ordinary sweep picks it up — one mechanism, not
two. The new item anchors on the edited message with `opened_at = edited_at`. *Alternative rejected:*
recovering pre-edit text from the captured event's payload — it expires with the retention window, which
would make the same edit produce different items at different times.

**D-TG-89 — `rederive_chat.py` gains `--with-attention`, defaulting off.** The session's third
clarification, FR-082, FR-083. It clears `attention_evaluated_at` for the named chat and window and runs
the judgement inline, then reports opened / answered / expired. Idempotent by D-TG-71 and D-TG-85.
Nothing else backfills, and no screen control triggers it.

### Metrics

**D-TG-90 — `contracts/attention-metrics.md` is the single definition of every figure, and the panel's
SQL is quoted from it.** FR-070. Both the Python side and the panel compute from the same stated
expressions; the source plan's §30 `metric-definitions.md` becomes worth extracting when TG-M7 adds
incident and coverage figures to these.

**D-TG-91 — Percentiles are computed in SQL with `percentile_cont`, and "no data" is NULL, never
zero.** Probe 6. `answered` is displayed beside every percentile, and the p90 cell renders a stated
reason below `MODERATION_PERCENTILE_MIN_SAMPLES` rather than a number. *Alternative rejected:*
computing percentiles in PHP over a fetched collection — it would be a second definition of the number
this milestone exists to make defensible.

**D-TG-92 — No average and no composite, enforced by a test that greps the panel for them.** FR-069,
source plan §18.6. Stated as a decision because "add an average, it is one line" is the single most
likely well-meaning regression in this milestone.

### The control panel

**D-TG-93 — The Live Attention Queue is a Filament custom page with a table, polled at 15 s.** Probe 7,
FR-054, FR-056. A page rather than a resource because an attention item is not operator-created CRUD:
the only writes are dismiss and hand-open, and both are actions.

**D-TG-94 — The waiting time is computed server-side on each poll, never by a browser clock.** FR-055.
A JavaScript ticker would disagree with every other number in the product by the viewer's clock skew,
and the milestone's acceptance is that the screen and a hand computation agree exactly.

**D-TG-95 — Arabic content keeps `dir="auto"` per field; the panel's locale and chrome stay
untouched.** D-TG-56 carried forward unchanged. TG-M2's Finding 1 measured that per-navigation-group
direction does not exist in Filament v5.7.8, and this milestone is the first to display message text,
which is where it actually matters.

**D-TG-96 — Dismiss and hand-open are row and header actions; there is no bulk action anywhere.**
FR-057. Dismissing twenty items with one click is how a false-positive count stops meaning anything.

**D-TG-97 — Per-group and per-moderator figures ship as a table on the same page, scoped by a period
filter.** FR-059. Not a second navigation entry: TG-M7 owns Team Performance, and shipping a
half-version of it now would have to be removed later.

---

## §3 — Settings

Two exist already and are consumed here for the first time; two are added.

| Key | Default | Status |
|---|---|---|
| `MODERATION_BURST_GAP_S` | 90 | **Exists** (TG-M0). Already validated positive — its comment names TG-M3 |
| `MODERATION_ITEM_MAX_AGE_S` | 86400 | **Exists** (TG-M0), unread until now |
| `MODERATION_TICK_INTERVAL_S` | 30 | **New.** The tick lease TTL (D-TG-86); throttles the poll loop's enqueue |
| `MODERATION_PERCENTILE_MIN_SAMPLES` | 10 | **New.** The p90 suppression floor (D-TG-91, source plan §18.1) |

Both new keys are optional and defaulted, following the established block's rule that nothing in this
domain is required to boot.

---

## §4 — What this milestone deliberately does not build

- No incident, no lifecycle, no moderator action, no enforcement evidence — TG-M4. `chat_member` and
  `message_reaction` stay captured and uninterpreted, and a reaction explicitly changes no figure here.
- No model call, no taxonomy, no confidence, no severity, no redaction in a live path — TG-M5.
  `message_classification_id` is shaped on the item and left NULL.
- No threshold, no quiet hours, no alert, no outbound message — TG-M6.
- No overview page, no widgets, no ingestion banner, no incompleteness marker over unobserved
  windows — TG-M7.
- No conversation table, no cross-sender threading, no thread hierarchy.
- No automatic backfill, no rule tuning, no learning.
- No deletion inference of any kind, in this or any later milestone.

---

## §5 — Traceability

| Requirement group | Decisions |
|---|---|
| Burst formation (FR-001…FR-010) | D-TG-79, D-TG-80, D-TG-71, D-TG-72 |
| Rule set (FR-011…FR-021) | D-TG-74, D-TG-75, D-TG-76, D-TG-77, D-TG-78 |
| Edits (FR-022…FR-024) | D-TG-88 |
| Response matching (FR-025…FR-035) | D-TG-82, D-TG-83, D-TG-84, D-TG-85, D-TG-81 |
| Ageing and expiry (FR-036…FR-040) | D-TG-86, D-TG-87 |
| Attribution (FR-041…FR-045) | D-TG-48 (reused), D-TG-70 |
| Operator correction (FR-046…FR-053) | D-TG-73, D-TG-85, D-TG-96 |
| The screen (FR-054…FR-062) | D-TG-93, D-TG-94, D-TG-95, D-TG-96, D-TG-97 |
| Metric arithmetic (FR-063…FR-070) | D-TG-90, D-TG-91, D-TG-92 |
| Boundaries and observability (FR-071…FR-084) | D-TG-86, D-TG-89, D-TG-72 |
