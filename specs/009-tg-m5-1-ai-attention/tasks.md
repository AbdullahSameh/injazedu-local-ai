# Tasks: TG-M5.1 — AI-assisted Attention Opening

Every test is scripted: no model runtime, no credential, no network. All run on `injaz_ai_test`.

- [x] **T101** The gate, pure: `proposes_attention` (G1–G4) and `within_attention_window` (G5–G6) —
  `tests/moderation/classification/test_attention_gate.py`.
- [x] **T102** `open_item(ai=…)`: rules first, then `_model_proposal` under `chat_lock`; a shared anchor and clock
  (`_anchor_and_opened_at`) — `test_ai_attention.py` (who opens, the gate's refusals, the clock, edits,
  attribution, dual-purpose).
- [x] **T103** `request_rejudgement` and the classifier's call in the prediction's transaction —
  `test_ai_attention.py` (Case A, Case B, the forced race, replays, catch-up, switch blank).
- [x] **T104** `MODERATION_AI_ATTENTION_FROM` (blank = off, offset required); the switch passed by
  `evaluate_attention`, `sweep_unjudged_bursts`, `rederive_chat` — `test_config_ai_attention.py`,
  `test_ai_attention.py::test_rederive_with_attention_reaches_the_live_answer_and_never_reaches_back`.
- [x] **T105** Compose and `.env.example` wiring (`ai-worker`, `ai-classifier`, `migrate`).
- [x] **T106** C9 in Python and PHP; the accuracy page's block and kept count — `test_metrics_model_opened.py`,
  `ModelOpenedQuestionsTest.php`.
- [x] **T107** "Opened by" on the Live Attention Queue — `LiveAttentionQueueTest::test_each_waiting_item_shows_who_opened_it`.
- [x] **T108** `smoke_attention.py`, the synthetic fixtures and `make smoke-attention` —
  `test_attention_smoke_scoring.py`.
- [x] **T109** Dated amendments: 008 spec / pipeline / data-model / metrics / control-panel; 006 attention-rules
  and data-model; the source plan; `CLAUDE.md`; runbook §C.
- [x] **T110** `make check` with Ollama quit.
- [ ] **T111** *(operator)* The benchmark on real labels; counts recorded in `research.md` §2.
- [ ] **T112** *(operator)* Switch on in development; the «في محاضرة اليوم» live check and a moderator reply.
