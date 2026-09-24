<!-- SPECKIT START -->
Active feature: **TG-M3 — Deterministic Response Tracking** (`specs/006-tg-m3-response-tracking/`) — 🎯 *the first usable slice*

Read before working on this feature:

- `specs/006-tg-m3-response-tracking/plan.md` — implementation plan, Constitution Check, the two operator items
- `specs/006-tg-m3-response-tracking/spec.md` — requirements (FR-001…FR-084), success criteria, 3 clarifications
- `specs/006-tg-m3-response-tracking/research.md` — 28 decisions (D-TG-70…D-TG-97), 10 probes, **4 findings**
- `specs/006-tg-m3-response-tracking/data-model.md` — revision `0005`: one table, one alter, the state machine
- `specs/006-tg-m3-response-tracking/contracts/attention-rules.md` — **the** TG-M3 contract: the burst (B1–B4), rule set v1 (R1–R5), edits (E1–E5), what closes an item (C1–C11), attribution (A1–A5), ageing (G1–G4), the non-promises
- `specs/006-tg-m3-response-tracking/contracts/attention-metrics.md` — the exact SQL behind every number (M1–M20)
- `specs/006-tg-m3-response-tracking/contracts/control-panel-attention.md` — the Live Attention Queue, its actions, what the panel may not do
- `specs/006-tg-m3-response-tracking/quickstart.md` — operator walkthrough, the runbook smoke test, 12 known limitations

This is the fourth milestone of a **second bounded domain**, not a feature of the first. Its source
plan of record is `docs/plan/telegram/telegram-moderation-intelligence.md` (11 milestones, TG-M0…TG-M10);
the operator's human steps are `docs/runbooks/tg-operator-prerequisites.md` — **§C's TG-M3 row (name the
pilot group and its moderator; live bot admin there; live credential on the host that runs capture) and
§D (where the live capture process runs) are prerequisites for the smoke test**, on top of §B and the
TG-M2 row still holding, though every automated test runs without any of them.

TG-M3 makes the product's core claim — *this student waited this long, and this named person was
responsible* — with **zero AI**: no model call, no categorisation, no severity, no incident, no alert,
no outbound message, no inbound port. It measures waiting and answering, and nothing else. Alembic
revision `0005` is consumed here; `0006`–`0009` stay reserved.

The three rules that carry this milestone:

- **The clock starts when the student spoke, not when the machine noticed.** Judgement is *delayed* by
  the settle window so the whole burst is judged together; `opened_at` is always the burst's earliest
  message's own `sent_at`. A ninety-second error here would shorten every response time in the product.
- **One matcher, two entry points.** A moderator can answer *inside* the settle window, so opening an
  item immediately evaluates already-stored messages through the **same** predicate as newly arriving
  ones. Two implementations of one rule are two ways for the number to disagree with itself.
- **Every transition is the same guarded write.** `UPDATE … WHERE id = :id AND status = 'open'` is
  simultaneously the concurrency control, the write-once rule, and the reason re-running any step is
  harmless. There is **no transition out of a terminal state** — not on a later message, not on an edit,
  not on a second dismissal.

Four measured facts that drive this design (see research.md §0):

1. ⚠ **Seven of the source plan's own §13.1 rule literals can never match.** `normalize()` folds
   `أ إ آ ٱ → ا`, `ة → ه`, `ى → ي` and strips tashkeel, so `متى`, `أين`, `كيفية`, `إيش`, `أبغى`,
   `مشكلة`, `متأخر` compared against `normalized_text` return false for **every message, forever**, with
   no error — and `متى` and `مشكلة` are among the commonest real signals. Literals are stored
   **already normalised**, and a test asserts `normalize(literal) == literal` for all 45 entries — the
   self-check is the fix, not the seven corrections — D-TG-74.
2. ⚠ **§10.7's `UNIQUE (telegram_message_id)` collides across groups, and the idempotent insert form
   swallows it.** Telegram numbers messages per chat from 1, so group B's message #2 hits group A's row:
   measured `INSERT 0 0` under `ON CONFLICT … DO NOTHING` (which FR-009 forces), one row where there
   should be two, no error, no log line. It lands on the *first* questions of every group after the
   first. The anchor is `UNIQUE (telegram_chat_id, telegram_message_id)` — D-TG-71.
3. ⚠ **The delayed judgement exists only in Redis, and this stack's Redis is not durable.** Dramatiq
   2.2.1 holds a delayed message on the `.DQ` queue with an `eta`, entirely in Redis; measured
   `appendonly no`, `save 3600 1 / 300 100 / 60 10000`, anonymous volume that `make down-hard` deletes.
   A lost message is a question that never happened — no gap is recorded, because TG-M1's gap detection
   watches the Telegram poll, not the queue. So `telegram_messages.attention_evaluated_at IS NULL` is
   the **authoritative work list** and the delayed message is an optimisation, exactly as TG-M1 already
   does for `drain_pending_updates` — D-TG-72, D-TG-80.
4. ⚠ **The stack has no periodic execution of any kind** — no scheduler, no cron, no tick. §7.3 assigns
   "the 30 s tick" to `ai-telegram` but TG-M1 never built it: `telegram_main.py:161` is a bare
   `while True` poll and `drain_pending_updates.send()` fires once at startup. The long-poll bounds the
   loop at ~30 s, so the tick is available for free: one leased `SET NX EX` enqueue per iteration, which
   **enqueues and computes nothing**, preserving §7.3's boundary — D-TG-86.

Architecture rules, mechanically enforced by `make check`:

- **no `httpx` / `ollama` / `openai` import outside `app/providers/`** (M1);
- **moderation modules may import only** `app.{domain,application}.moderation`, `app.providers.telegram`,
  `app.workers.tasks.moderation`, `app.application.gateway`, `app.infrastructure`, `app.domain.model_profile`;
- **no assessment-side module may import moderation** (composition roots — `app/main.py`, `app/workers/`,
  `app/scripts/`, and `app/`-root files such as `app/telegram_main.py` — are exempt **by directory**;
  this is why `app/scripts/rederive_chat.py` may import both, and why the tick may live in
  `telegram_main.py`);
- **no Telegram SDK** outside `app/providers/telegram/`; the provider speaks the Bot API over `httpx`;
- **no message text in any log line.** `check.sh`'s check 4 fails a `logger.*()` call on a line that
  also mentions `original_text`, `normalized_text`, `redacted_text`, `message_text` or `caption`. The
  correlation keys here are `message_id` and `item_id`, never `message` — stdlib `logging` rejects
  `extra={"message": …}` inside `makeRecord` (TG-M0's D-TG-24);
- **`app/domain/moderation/attention.py` stays pure**: no I/O, no clock, no session. It is a function
  over strings, which is what makes running the whole Arabic fixture corpus cheap.

Panel rules: Alembic owns the schema, so **no migration from Filament**; no platform call, no model
call, no bulk job behind a toggle, **no average and no composite score anywhere** (tested). Feature
tests use `DatabaseTransactions` against `injaz_ai_test` — never `RefreshDatabase`, `DatabaseMigrations`
or `migrate:fresh`. No `GRANT` is needed in a migration: `ALTER DEFAULT PRIVILEGES FOR ROLE ai_migrator`
already reaches `ai_control` in both databases. Arabic content keeps `dir="auto"` **per field**; the
panel locale and chrome stay English and LTR (TG-M2's D-TG-56, and this is the first milestone that
actually displays message text).

Previous milestones (still current infrastructure): `specs/001-m0-foundation/`,
`specs/002-m1-model-gateway/`, `specs/003-tg-m0-moderation-foundation/`,
`specs/004-tg-m1-telegram-ingestion/`, `specs/005-tg-m2-groups-and-ownership/`.
The M1 gateway is untouched. Consumed here for the first time: TG-M0's `normalize()` and the burst/age
settings, TG-M1's captured events and `process_update` handoff, and all of TG-M2 — typed messages, the
write-once `is_from_moderator`, `responsible_at(chat, t)`, the measurement gate and `rederive_chat.py`.

Project-wide, always: `.specify/memory/constitution.md`. Its non-negotiables in one line —
`injazedu/` is read-only, Git actions belong to the operator, and no test may touch a database
whose name lacks `_test`.

Broader context: `docs/plan/core/final-injazedu-local-ai-code-agent-implementation-plan.md`.
<!-- SPECKIT END -->
