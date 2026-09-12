<!-- SPECKIT START -->
Active feature: **TG-M1 — Telegram Event Ingestion** (`specs/004-tg-m1-telegram-ingestion/`)

Read before working on this feature:

- `specs/004-tg-m1-telegram-ingestion/plan.md` — implementation plan, Constitution Check, the two operator items
- `specs/004-tg-m1-telegram-ingestion/spec.md` — requirements (FR-001…FR-045), success criteria, 4 clarifications
- `specs/004-tg-m1-telegram-ingestion/research.md` — 17 decisions (D-TG-29…D-TG-45), 10 probes, **3 findings**
- `specs/004-tg-m1-telegram-ingestion/data-model.md` — the four tables of revision `0003`
- `specs/004-tg-m1-telegram-ingestion/contracts/telegram-provider.md` — **the** TG-M1 contract: the protocol, the capability table, the error taxonomy, the identifier-reset protocol
- `specs/004-tg-m1-telegram-ingestion/contracts/ingestion-guarantees.md` — G1–G6 and the explicit non-promises
- `specs/004-tg-m1-telegram-ingestion/contracts/health-ingestion.md` — the health block, its composition-root wiring, `tg-doctor`
- `specs/004-tg-m1-telegram-ingestion/quickstart.md` — operator walkthrough, smoke test, known limitations

This is the second milestone of a **second bounded domain**, not a feature of the first. Its source
plan of record is `docs/plan/telegram/telegram-moderation-intelligence.md` (11 milestones, TG-M0…TG-M10);
the operator's human steps are `docs/runbooks/tg-operator-prerequisites.md` — **§B (both bots created,
privacy disabled before the first group add, bot promoted to admin) is a prerequisite for TG-M1's
smoke test**, though every automated test runs without it.

TG-M1 ships **no message parsing, no screen and no model call.** The bot **sends nothing** and the
machine **opens no inbound port**. Alembic revision `0003` is consumed here; `0004`–`0009` stay reserved.

Three measured facts that drive this design (see research.md §0):

1. ⚠ After **a week with no updates at all**, Telegram picks the next `update_id` **randomly** — it can
   be *lower* than the last one stored. A strictly-forward offset then never receives it: polls succeed,
   return empty, raise nothing, **forever**, while every health signal stays green. Recovery is to
   **omit `offset` entirely**; never a negative offset, which the docs say forgets the whole backlog.
   This gives spec FR-019 its one documented exception — D-TG-33.
2. ⚠ The natural home for the ingestion health probe (`app/application/probes/`) **fails `make check`** —
   correctly, since it is assessment-side and may not read moderation tables. The probe lives in
   `app/application/moderation/` and is composed at the **composition root** (`app/main.py`), which the
   gate exempts by directory — D-TG-31. Do **not** widen the allowlist to route around this.
3. ⚠ `ComponentReport` is `frozen=True` but not `extra="forbid"`, so an ad-hoc `ingestion=` keyword is
   **accepted and silently dropped**. The block must be a *declared field*, and tests must assert its
   **contents**, never just `status == "ok"` — D-TG-32.

Architecture rules, mechanically enforced by `make check`:

- **no `httpx` / `ollama` / `openai` import outside `app/providers/`** (M1);
- **moderation modules may import only** `app.{domain,application}.moderation`, `app.providers.telegram`,
  `app.workers.tasks.moderation`, `app.application.gateway`, `app.infrastructure`, `app.domain.model_profile`;
- **no assessment-side module may import moderation** (composition roots — `app/main.py`, `app/workers/`,
  `app/scripts/`, and `app/`-root files such as `app/telegram_main.py` — are exempt **by directory**);
- **no Telegram SDK** outside `app/providers/telegram/`; the provider speaks the Bot API over `httpx`;
- **no message text in any log line.** The correlation key is `message_id`, never `message` — stdlib
  `logging` rejects `extra={"message": …}` inside `makeRecord` (TG-M0's D-TG-24).

Previous milestones (still current infrastructure): `specs/001-m0-foundation/`,
`specs/002-m1-model-gateway/`, `specs/003-tg-m0-moderation-foundation/`. The M1 gateway is reused
as-is; TG-M0's boundary, settings, correlation-id whitelist and secret scan are all first consumed here.

Project-wide, always: `.specify/memory/constitution.md`. Its non-negotiables in one line —
`injazedu/` is read-only, Git actions belong to the operator, and no test may touch a database
whose name lacks `_test`.

Broader context: `docs/plan/core/final-injazedu-local-ai-code-agent-implementation-plan.md`.
<!-- SPECKIT END -->
