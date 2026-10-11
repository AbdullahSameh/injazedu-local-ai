# Feature Specification: TG-M5.1 — AI-assisted Attention Opening

**Feature Branch**: none created — Git is operator-owned (constitution IV); work sits on `m5/ai-classification`
**Created**: 2026-10-03
**Status**: Implemented, awaiting the operator's benchmark and switch-on
**Input**: "Use the existing TG-M5 classification as a second source for opening Attention items when the AI
says a student/member message needs a response, while keeping all TG-M3 response tracking, timing,
assignment, burst grouping and lifecycle logic unchanged." (operator brief, 2026-10-03; plan of record
`docs/plan/telegram/tg-m5-1-ai-attention-plan.md`)

## Provenance — what this milestone changes, and what it keeps

- **TG-M3** opened question items from rules only (`source = 'rule'`), and reserved `source = 'ai'` and
  `message_classification_id` for TG-M5 (`specs/006…/data-model.md`).
- **TG-M5** made the model's needs-response judgement **measurement only** (008 spec, clarification
  2026-09-27 Q2; FR-032; pipeline R13/N1/F6) and deferred "letting the model open question items" to "no
  earlier than TG-M8" (008 Out of Scope), "to be decided on the evidence this milestone produces".
- **TG-M5.1** takes that decision early, on that evidence: `classify_v2` records `needs_response = true` on
  implicit questions such as «في محاضرة اليوم», which the rule set — by design, kept to clear question
  forms — cannot see. It lets a **live** prediction open an item **the rule set declined**. Each superseded
  statement carries a dated "Amended by TG-M5.1" note beside it, and none is deleted.

## Clarifications

### Session 2026-10-03

- Q: A prediction both needs a response and needs moderation (e.g. a complaint with an accusation). What does
  the model open? → A: **Both units, independently.** The question side follows this milestone's gate and
  the violation side follows TG-M5's routing, unchanged, as TG-M4 already keeps a rule-opened item and an
  incident on one message (TG-M4 I7). needs_response on SPAM_OR_AD, ABUSE or CHITCHAT contradicts the
  instruction ("always false") and opens no question.
- Q: A live prediction lands late (classifier backlog, or `ai-classifier` down while Redis holds the queue).
  → A: **Decline if the item would be born expired.** A prediction recorded `MODERATION_ITEM_MAX_AGE_S` or more
  after the burst's `opened_at` opens nothing. A younger one opens normally. If a moderator already answered,
  TG-M3's C10 lookback closes the item `answered` in the same transaction, with its real response time.
- Q: A burst member was edited before judgement — does its prediction (of its first-posted words) count? →
  A: **Yes.** The anchor and `opened_at` follow TG-M3 E3 (the edited member, at `edited_at`), the
  conservative clock. Typo-fixed implicit questions are caught.
- Q: How is the behaviour switched on? → A: **A dated switch, `MODERATION_AI_ATTENTION_FROM`** (blank = off).
  Only live predictions recorded at or after the instant can open an item. Every judgement path reaches the
  same answer, and switching on never reaches back into history.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — An implicit question opens an item the moderators can see and answer (P1)

A student posts «في محاضرة اليوم». The rule set finds no question signal. `classify_v2` records
`QUESTION_COURSE`, `needs_response = true`. When the burst settles, an item opens with `source = 'ai'`, dated
from the student's message, owned by the group's owner at that moment. The Live Attention Queue shows
"Opened by: Model" and the model's view. A moderator replies, and the item closes `answered` with the real
response time.

**Acceptance**: (1) The rules decline and a live, qualifying prediction exists → one `ai` item, `rule_version`
NULL, linked to the prediction, `opened_at` = the burst's anchor time. (2) A direct reply or the next group
message closes it exactly as TG-M3 closes a rule item. (3) A rule question opens a `rule` item whatever the
model says, and a later prediction never adds a second item.

### User Story 2 — Both orderings converge on one item (P1)

**Acceptance**: (1) Classified before the settle → the item opens at judgement. (2) Classified after the
settle → the message goes back on the sweep's work list and the next tick opens exactly one item. (3) Replays
and concurrent judgements leave one item. (4) A classification racing an open judgement still converges.

### User Story 3 — The model never adds work it should not (P1)

**Acceptance**: no item for needs_response false; for a below-floor prediction; for SPAM_OR_AD / ABUSE /
CHITCHAT; for a catch-up prediction; for a prediction recorded before the switch, or one recorded
`MODERATION_ITEM_MAX_AGE_S` late; with the switch blank; for a moderator's or a bot's message; or for an
acknowledgement (never classified).

### User Story 4 — The pilot's false-positive rate is visible (P2)

The Classification Accuracy page shows, per model, the questions the model opened: dismissed ÷ opened (the
operational gate), answered ÷ opened, and still unanswered ÷ opened. Beside the rule baseline it shows how
many model-opened questions were kept, because those are rule misses the operator-added count never sees.

### User Story 5 — The operator benchmarks before switching on (P1)

`make smoke-attention` over the operator's own labelled messages, kept outside the repo, reports
needs-response agreement, false negatives, false positives, and who would open an item (rule / model /
nobody) split by label. Model-opened on expected-false fixtures is the new moderator work, printed on its own
line.

### Edge cases

Growing bursts, the classifier down, hand-opening, and the recall floor: `contracts/attention-opening.md` §9.

## Requirements *(mandatory)*

- **FR-101**: A live prediction MUST be able to open a question item only when the rule set declined the burst,
  only through TG-M3's `open_item`, and only when it passes the gate (contract G1–G6).
- **FR-102**: The rule set MUST be evaluated first. An item both would open MUST be `source = 'rule'`.
- **FR-103**: A model-opened item MUST carry `source = 'ai'`, `rule_version = NULL` and
  `message_classification_id`. It MUST be anchored, dated and attributed exactly as a rule-opened item of the
  same burst would be (TG-M3 B2, E3, A1). The classification time MUST never be used.
- **FR-104**: A prediction that lands after its burst was judged MUST put the message back on TG-M3's
  authoritative work list, in the transaction that records it, through E5's mechanism. Judgement MUST stay in
  `open_item` alone.
- **FR-105**: One burst MUST still open at most one item, under every ordering, replay and concurrency.
- **FR-106**: Catch-up predictions MUST stay measurement only. Re-derivation MUST reach the same answer as live
  judgement.
- **FR-107**: A blank `MODERATION_AI_ATTENTION_FROM` MUST leave every behaviour exactly as TG-M5 left it.
- **FR-108**: Response matching, FRT, ageing, dismissal and attribution MUST be TG-M3's, unchanged, for every
  source.
- **FR-109**: The Live Attention Queue MUST show who opened each item (Rule / Model / Operator), from `source`.
- **FR-110**: The Classification Accuracy page MUST show C9 per model, never pooled, every ratio with its
  denominator, with no average and no percentage.
- **FR-111**: A benchmark command MUST report needs-response agreement, false negatives, false positives and
  the opener tallies by label, without printing text and without writing anything.
- **FR-112**: No migration. Revisions `0008`–`0009` stay reserved.

## Success Criteria *(mandatory)*

- **SC-101**: In the development group, «في محاضرة اليوم» opens one `ai` item, `status = open`, `opened_at`
  equal to the platform timestamp. A moderator's reply closes it `answered` with FRT = reply − `opened_at`.
- **SC-102**: With the switch blank, every TG-M3/TG-M4/TG-M5 test passes unchanged, and the classifier never
  touches `telegram_messages`.
- **SC-103**: Across both orderings, replays and a forced race, exactly one item per burst.
- **SC-104**: `make check` passes with Ollama quit.
- **SC-105**: The benchmark's numbers are recorded in `research.md` before the switch is set.

## Out of Scope

- Replacing the rule set, or expanding its patterns for implicit wording.
- Changing `classify_v1.md` / `classify_v2.md`, the thresholds, the incident routing, the gateway, redaction,
  the first-posted-text behaviour, or the queue's layout beyond one column.
- Bot replies, alerts (TG-M6) and auto-moderation.
- Hand-opening under `chat_lock` (pre-existing; contract §9).
