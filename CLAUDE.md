<!-- SPECKIT START -->
Active feature: **TG-M0 — Moderation Intelligence Domain Foundation** (`specs/003-tg-m0-moderation-foundation/`)

Read before working on this feature:

- `specs/003-tg-m0-moderation-foundation/plan.md` — implementation plan, Constitution Check, project structure
- `specs/003-tg-m0-moderation-foundation/spec.md` — requirements (FR-001…FR-034) and success criteria
- `specs/003-tg-m0-moderation-foundation/research.md` — 12 decisions (D-TG-17…D-TG-28) with rationale and rejected alternatives
- `specs/003-tg-m0-moderation-foundation/contracts/moderation-text.md` — **the** TG-M0 contract: the normaliser, the redactor, the redact-before-gateway rule
- `specs/003-tg-m0-moderation-foundation/contracts/domain-boundary.md` — the boundary rules and the five gate checks
- `specs/003-tg-m0-moderation-foundation/quickstart.md` — operator walkthrough and known limitations

This is a **second bounded domain**, not a feature of the first. Its source plan of record is
`docs/plan/telegram/telegram-moderation-intelligence.md` (11 milestones, TG-M0…TG-M10); the operator's
human steps are `docs/runbooks/tg-operator-prerequisites.md`.

TG-M0 ships **no table, no Telegram call, no screen and no model call.** Alembic revisions `0003`–`0009`
are reserved for this domain and unconsumed.

Two measured facts that drive this design (see research.md §0):

1. ⚠ A naive repeated-character collapse turns the phone number `0555555555` into `05`. Normalisation
   runs *before* redaction, so the redactor then finds nothing to replace. The collapse is
   **letters-only** — D-TG-21. This corrects the source plan's §15.4 wording.
2. ⚠ Stdlib `logging` **rejects** `extra={"message": …}`, so the correlation key is `message_id` — D-TG-24.
   The `KeyError` fires inside `makeRecord`, which a call below the logger's level never reaches: a test
   without `setLevel` passes vacuously.

Architecture rules, mechanically enforced by `make check`:

- **no `httpx` / `ollama` / `openai` import outside `app/providers/`** (M1);
- **moderation modules may import only** `app.{domain,application}.moderation`, `app.providers.telegram`,
  `app.workers.tasks.moderation`, `app.application.gateway`, `app.infrastructure`, `app.domain.model_profile`;
- **no assessment-side module may import moderation** (composition roots — `app/main.py`, `app/workers/`,
  `app/scripts/` — are exempt);
- **no Telegram SDK** outside `app/providers/telegram/`; the provider speaks the Bot API over `httpx`;
- **no message text in any log line.**

Previous milestones (still current infrastructure): `specs/001-m0-foundation/`, `specs/002-m1-model-gateway/`.
The M1 gateway is reused as-is — it is the single most valuable asset for this domain.

Project-wide, always: `.specify/memory/constitution.md`. Its non-negotiables in one line —
`injazedu/` is read-only, Git actions belong to the operator, and no test may touch a database
whose name lacks `_test`.

Broader context: `docs/plan/core/final-injazedu-local-ai-code-agent-implementation-plan.md`.
<!-- SPECKIT END -->
