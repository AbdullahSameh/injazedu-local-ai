# Implementation Plan: TG-M5.1 — AI-assisted Attention Opening

**Spec**: `spec.md` · **Contract**: `contracts/attention-opening.md` · **Plan of record**:
`docs/plan/telegram/tg-m5-1-ai-attention-plan.md` (the 15-point analysis, approved 2026-10-03)

## Summary

`open_item` gains a second opener, consulted only after rule set v1 declines. A small pure gate decides
whether a stored, live prediction proposes the burst needs an answer. A late prediction re-enters TG-M3's
authoritative work list through E5's mechanism. The panel gains one column and one figure (C9), and the
operator gains a benchmark. No migration.

## Constitution Check

| Principle | How this milestone meets it |
|---|---|
| I. Risk-proportional testing | Tested: the gate (pure, every boundary); who opens; both orderings; replays; a forced race; catch-up; the switch blank; late and early predictions; edits; attribution across a handover; matching for `ai` items; dual-purpose; re-derivation; config; C9 arithmetic (Python and PHP); the Opened-by column; benchmark scoring. Not tested beyond existing suites: the Make target and compose wiring (configuration, checked by `docker compose config`). |
| II. Test database isolation | Every new test runs on `injaz_ai_test` through the existing fixtures; PHP uses `DatabaseTransactions`. |
| III. `injazedu/` read-only | Untouched. |
| IV. Git operator-owned | No branch, no commit; the operator commits. |
| V. Approved scope | Exactly the approved design; the four decisions are recorded in `spec.md`. No pattern expansion, no prompt change, no threshold change, no migration. |

Architecture rules (`make check`): the gate lives in `app/domain/moderation/classification.py` (pure, stdlib
only); `app/application/moderation/attention.py` imports only permitted prefixes; no text in any log line; no
PHP computation of state, route or eligibility (the column labels a stored value; C9 is SQL quoted from the
metrics contract).

## Files

| Where | Change |
|---|---|
| `app/domain/moderation/classification.py` | `NO_RESPONSE_CATEGORIES`, `proposes_attention`, `within_attention_window` |
| `app/application/moderation/attention.py` | `AiAttention`, `ai_attention_from_settings`, `_anchor_and_opened_at`, `_model_proposal`, `open_item(ai=…)`, `request_rejudgement` |
| `app/application/moderation/classification.py` | one call to `request_rejudgement` after the prediction insert |
| `app/workers/tasks/moderation/{evaluate_attention,sweep_unjudged_bursts}.py`, `app/scripts/rederive_chat.py` | pass the switch |
| `app/infrastructure/config.py` | `MODERATION_AI_ATTENTION_FROM` (blank = off, offset required) |
| `app/application/moderation/metrics.py` | C9 |
| `app/scripts/smoke_attention.py`, `attention_smoke_fixtures.jsonl`, `Makefile` | the benchmark |
| `infra/docker-compose.yml`, `.env.example` | the switch reaches `ai-worker`, `ai-classifier`, `migrate` |
| `apps/ai-control/…/LiveAttentionQueue.php` | "Opened by" column |
| `apps/ai-control/…/ClassificationMetrics.php`, `ClassificationAccuracy.php`, blade | C9 block, kept count beside the baseline |
| specs 006 / 008, source plan, `CLAUDE.md`, runbook | dated amendment notes |

## Progress

| Phase | Status |
|---|---|
| Analysis and decisions | ✅ 2026-10-03 (`docs/plan/telegram/tg-m5-1-ai-attention-plan.md`) |
| Implementation | ✅ `tasks.md` |
| Benchmark on real labels | ⏳ operator — `quickstart.md` §2 |
| Switch on in development, live check | ⏳ operator — `quickstart.md` §3 |
