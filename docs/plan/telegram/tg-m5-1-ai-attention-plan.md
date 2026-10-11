# TG-M5.1 — AI-assisted Attention Opening

## Context

`classify_v2` correctly records `needs_response=true` on implicit questions such as «في محاضرة اليوم», but no
`attention_item` opens because TG-M3's rule set finds no question signal. TG-M5 deliberately made needs-response
**measurement only**. M5.1 makes the live prediction a **second opener**: it applies only after the rule set has
declined, and only through TG-M3's own `open_item`. Bursts, settle window, `opened_at`, attribution, matching,
FRT and lifecycle stay exactly as they are. Nothing is committed (the operator owns Git).

**Decisions taken (2026-10-03, operator):** (1) dual-purpose → both units, independently; (2) a late prediction
that would be born expired opens nothing; (3) an edited member's first-posted prediction still counts, and the
anchor and `opened_at` follow TG-M3 E3; (4) the switch is a dated instant, `MODERATION_AI_ATTENTION_FROM`.

---

## 1. Current flow: a rule-opened item

`derive_message` (`app/application/moderation/messages.py:174`) inserts the row and, for a non-moderator person,
sends `evaluate_attention` with `delay = MODERATION_BURST_GAP_S` (90 s). Then:
`evaluate_attention_once` → `assemble_burst` (`attention.py:44`) → `open_item` (`attention.py:162`). Inside
`chat_lock`, `open_item` does the following:
- If any burst member already has `attention_item_id`, it converges on that item (E2/E4).
- Otherwise it checks that the chat is monitored, the sender is not a moderator or bot, and no member is a
  service message. Then it calls `evaluate(texts, …)` (`domain/moderation/attention.py:152`).
- When the rules open, the anchor is the earliest member (or the latest edited member) and `opened_at` is its
  `sent_at` (or `edited_at`). It sets `responsible_at(opened_at)` and inserts with `ON CONFLICT
  uq_attention_anchor DO NOTHING`, `source='rule'`, `rule_version=1`.
- It stamps every member with `attention_evaluated_at` and `attention_item_id`.
- It runs the C10 lookback, `match_existing_responses`.
- `sweep_unjudged_bursts` runs on the 30 s tick and claims `attention_evaluated_at IS NULL`. This is the
  authoritative work list. `apply_edit` clears that column to force a re-judgement (E5).

## 2. Current flow: TG-M5 classification

`derive_message` also sends `classify_message(chat_pk, message_id, "live")`, on the `moderation_classify` queue
served by `ai-classifier`. `classify_one` (`application/moderation/classification.py:342`) then:
1. Takes the Redis claim and checks idempotency (I1–I3).
2. Runs `eligibility` (E1–E8; acknowledgements are excluded by the shared `is_acknowledgement`).
3. Re-extracts the first-posted text from the captured event and redacts it.
4. Calls the gateway, then quantises and routes the answer (R1–R6).
5. Inserts the immutable prediction.
6. If the route is `incident`, calls `insert_incident` in the same transaction.

## 3. Why `needs_response=true` opens nothing today

Nothing in the code reads `needs_response`: `open_item` only consults `evaluate()`, and `classify_one` only acts
on `route == 'incident'`. The contracts require this:
- 008 `spec.md:79`, clarification 2026-09-27 Q2: "Measurement only … The model opens … no question item."
- 008 `spec.md` FR-032 (565–567), the edge case at 402–404, SC-014 (792–793), SC-015, and Out of Scope at 692
  ("…no earlier than TG-M8").
- `contracts/classification-pipeline.md`: R13 ("The route never touches a question item"), N1 and F6.
- 008 `data-model.md` §5 (251–254): `message_classification_id` "stays NULL … `source='ai'` stays reserved".
- 006 `data-model.md:23`: "`ai` is reserved for TG-M5 and never written here".
- Source plan, "Correction (TG-M5)": "the model opens no question item anywhere in this pipeline".
- `CLAUDE.md`: "The model opens no question and closes nothing."
- Code comments at `models_moderation.py:356-358` and `712-714`.

M5.1 amends each of these with a dated note. None is deleted.

## 4. Architecture

```
student message ──► derive_message ──► evaluate_attention (+90 s) ─┐
                         │                                         ├─► open_item (chat_lock) — ONE decision point
                         │                    sweep (30 s tick) ───┘     1. rules (unchanged)      → source='rule'
                         └─► classify_message ─► classify_one            2. else model's proposal  → source='ai'
                                                   └─ live prediction proposes attention?        3. else nothing
                                                      → request_rejudgement (E5's own mechanism)
```

- **The gate (pure, single definition)**, `app/domain/moderation/classification.py`:
  `proposes_attention(path, route, needs_response, category, recorded_at, opened_at, enabled_from, max_age_s)`.
  It is true only when all of these hold:
  - `path == 'live'`: catch-up stays measurement only.
  - `route != 'review'`: FR-030 already forbids a below-floor prediction from opening *anything*. The floor
    (0.60) is used only because a contract requires it; the incident threshold (0.85) is not a gate.
  - `needs_response` is true.
  - `category ∉ {SPAM_OR_AD, ABUSE, CHITCHAT}`: both instructions say needs_response is "always false" for these,
    so a true value contradicts itself (the spirit of R8).
  - `enabled_from` is set and `recorded_at ≥ enabled_from`.
  - `recorded_at < opened_at + MODERATION_ITEM_MAX_AGE_S`: no born-expired item (decision 2).
- **`open_item(session, burst, *, ai: AiAttention | None = None)`.** The anchor and `opened_at` computation moves
  ahead of the decision, so both openers share it. If the rules decline, `ai` is set and the existing gates
  passed, it reads the current predictions of the burst's members *inside the lock*. It walks them in
  `(sent_at, message_id)` order, which is the same choice C6/M17 makes, and takes the first one the gate
  accepts. It then inserts `source='ai'`, `rule_version=NULL`, `message_classification_id=<that prediction>`.
  Stamping and the C10 lookback are unchanged. `ai=None` gives exactly TG-M3/M5 behaviour.
- **`request_rejudgement(session, *, chat_pk, message_id)`**, new in `attention.py`. Under `chat_lock` it reads
  the message. When `attention_item_id IS NULL`, `attention_evaluated_at IS NOT NULL` and `telegram_user_id IS
  NOT NULL`, it sets `attention_evaluated_at = NULL`. That is E5's re-judgement mechanism; the classifier
  contains no attention logic.
- **`classify_one`**: after a prediction row is inserted, if `MODERATION_AI_ATTENTION_FROM` is set and the gate's
  prediction-side terms hold, it calls `request_rejudgement` **in the same transaction** as the prediction (and
  any incident).
- **Config**: `moderation_ai_attention_from: datetime | None`, alias `MODERATION_AI_ATTENTION_FROM`. Blank means
  off, and a naive datetime is rejected. Every judgement path builds `AiAttention(enabled_from, max_age_s)` from
  settings: `evaluate_attention`, `sweep_unjudged_bursts` and `rederive_chat --with-attention`. So every caller
  reaches the same answer, and enabling the switch never reaches back into history.

## 5. Race design

- **Case A (prediction before settle):** the prediction commits at about 1 s. At +90 s `open_item` reads it under
  the lock, the rules decline, and a `source='ai'` item opens. `request_rejudgement` is a no-op, because the
  message has not been judged yet.
- **Case B (settle before prediction):** at +90 s `open_item` declines and stamps the message. Later,
  `classify_one` takes `chat_lock`, sees the message judged with no item, clears `attention_evaluated_at` and
  commits. The next tick's sweep (≤ 30 s) runs `open_item`, which finds the prediction, and the item opens.
  There is no new polling: this is TG-M3's authoritative work list.
- **Interleaved:** both sides touch the decisive state only under `chat_lock`:
  - If `open_item` holds the lock first, it cannot see the uncommitted prediction and declines. Then the
    classifier clears the flag and the sweep re-judges.
  - If the classifier holds it first, `open_item` reads the committed prediction and opens.
- **Deadlock check:** the sweep's `FOR UPDATE SKIP LOCKED` only ever holds rows with `attention_evaluated_at
  IS NULL`, and the classifier updates only rows that are NOT NULL. So no lock cycle is added.

## 6. Idempotency

- The anchor is unique (`uq_attention_anchor`) and the insert is `ON CONFLICT DO NOTHING`.
- E4: any member that carries `attention_item_id` makes every later judgement converge on that item.
- I1–I4 give one prediction per message, so there is at most one re-judgement request, and the request itself
  is idempotent.
- The rules always run first. When both openers would open, the item is `source='rule'`, so rule-opened items
  are identical with the switch on or off, except in growing bursts (see limitations).
- `message_classification_id` is written only at insert of an `ai` item and never updated later. A rule item
  "gets" the model's label only through the existing C6 join, so N1/E4 hold.

## 7–8. Burst semantics, `opened_at`, attribution

- There is still one burst, one anchor and one item.
- The anchor is chosen by TG-M3's own rule regardless of opener. B2 sets `opened_at` to the earliest member's
  `sent_at`, even when the model-flagged member is later. E3 sets it to the latest edit's `edited_at` when a
  member was edited.
- It is never the classification time.
- `responsible_moderator_id = responsible_at(chat, opened_at)` uses the same code path.
- An edited member's prediction (of its first-posted words) still counts (decision 3). The anchor and clock
  follow E3, which is the conservative clock.

## 9. Already-answered messages

TG-M3 C10 defines this case: an item opens historically and the lookback closes it in the same transaction. So a
late `ai` item whose question a moderator already answered opens **and** closes as `answered`, with FRT measured
from `opened_at`, and it is never visible as open. A prediction recorded ≥ 24 h after `opened_at` opens nothing.
Rule (b)'s oldest-only rule (C3) is unchanged.

## 10. Live vs catch-up

- Catch-up predictions have `path='catch_up'` and route `measurement_only`, so they never pass the gate.
- `classify_chat` therefore never requests a re-judgement.
- `rederive_chat` sends no classification (Q2). Its `--with-attention` re-judgement can open an `ai` item only
  where live judgement would have opened one, by the same dated gate, so it reaches the same answer on every path.

## 11. Dual-purpose (decision 1: both, independently)

| Prediction | Question side | Violation side (unchanged R1–R6) |
|---|---|---|
| COMPLAINT, needs_response=T, needs_moderation=T | `ai` item if the rules declined | inconsistent → Possible Violations |
| OTHER, both T, severity ≠ none, ≥ 0.85 | `ai` item | incident (`source='ai'`) |
| ABUSE / SPAM_OR_AD with needs_response=T | none (self-contradicting) | as routed |

«انتوا نصابين، متى بترجعوا فلوسي؟» already opens a rule item (متي, ؟); M5.1 does not change that.

## 12. Files

**Code (`apps/ai-api`)**
- `app/domain/moderation/classification.py`: `NO_RESPONSE_CATEGORIES` and `proposes_attention` (pure).
- `app/application/moderation/attention.py`: `AiAttention`; the `open_item(ai=…)` branch with a shared anchor
  block; `request_rejudgement`.
- `app/application/moderation/classification.py`: one call after the prediction insert.
- `app/workers/tasks/moderation/evaluate_attention.py`, `sweep_unjudged_bursts.py` and
  `app/scripts/rederive_chat.py`: pass `AiAttention` from settings.
- `app/infrastructure/config.py`: the new setting. Also add it to `.env.example`, and to compose env if settings
  are passed explicitly.
- `app/infrastructure/models_moderation.py`: dated comment notes only.
- `app/application/moderation/metrics.py`: **C9** (below).
- Benchmark: `app/scripts/smoke_attention.py`, the synthetic `app/scripts/attention_smoke_fixtures.jsonl` (no
  real text), and a `Makefile` `smoke-attention` target.

**Panel (`apps/ai-control`)**
- `LiveAttentionQueue.php`: one badge column, **Opened by**: Rule / Model / Operator, read from `source`.
  "Model's view" already shows the prediction.
- `ClassificationMetrics.php` and `classification-accuracy.blade.php`: a C9 block.

**New metric C9 (`classification-metrics.md` §8a):** per `(model_profile_id, prompt_version, taxonomy_version)`,
the count of `ai` items opened, dismissed and answered. Rows join through `message_classification_id`, are
selected by `opened_at`, and are never pooled. "Dismissed ÷ opened" with its denominator is the **pilot
false-positive gate**. C7 is verbatim and unchanged; the page prints C9's "model-opened and kept" beside the
rule-recall floor, because those are rule misses that are not in `operator_added`. C1 already excludes `ai`. C2's
"unverified" set shrinks naturally.

**Specs and docs**
- New `specs/009-tg-m5-1-ai-attention/`: `spec.md` (clarifications 2026-10-03 ×4, FRs, SCs), `plan.md`
  (Constitution Check), `research.md` (D-TG-164…, and the benchmark counts only, never text),
  `contracts/attention-opening.md` (the gate, races, idempotency, timing and the never-list), `quickstart.md`
  and `tasks.md`.
- Dated "Amended by TG-M5.1 (2026-10-03)" notes beside every statement in §3. Add Out-of-Scope and SC
  clarifications. FR-052 and the panel-contract Q2 note the new column.
- Point E1 in 006 `attention-rules.md` to the clarification for decision 3.
- `CLAUDE.md`: the active feature becomes TG-M5.1.
- Runbook §C: a TG-M5.1 row (`real-attention.jsonl` kept outside the repo).

## 13. Migration

**None.** `ck_attention_source` already allows `'ai'`. `ck_attention_rule_version` requires NULL for non-rule
items. `message_classification_id` and `fk_attention_classification` exist, and the prediction lookup uses
`uq_classification_current`. Revisions 0008–0009 stay reserved. The rule "`ai` ⇒ classification id NOT NULL" is
enforced in code and tests.

## 14. Tests

All tests use a scripted model, need no runtime, and run on `injaz_ai_test`. The integration tests go in a new
`tests/moderation/classification/test_ai_attention.py` and the gate tests in `test_attention_gate.py`.

1. A rule question → one `rule` item with a NULL classification id.
2. The same burst then gets a live `needs_response=true` prediction, followed by a request and a sweep → still
   one item, `rule`, unchanged.
3. Implicit question + a live prediction that passes the gate → `ai` item, `rule_version` NULL, the id linked.
4. No item for each of: `needs_response=false`; `route='review'`; CHITCHAT, SPAM or ABUSE with T; catch-up;
   recorded before FROM; switch blank (M5-identical); prediction ≥ max-age late.
5. Case A, end to end.
6. Case B: the flag is cleared and the sweep opens exactly one item.
7. Replays: a classify twice; evaluate, sweep and rederive repeated; concurrent evaluate + sweep → one item.
   Also the interleaving test: hold an `open_item` transaction open while `classify_one` runs, then commit and
   assert the item converges.
8. `classify_chat` catch-up → no request, no item.
9–10. An `ai` item closes by direct reply and by group message (C3 oldest-only). `answered`,
   `first_response_*` and the FRT are correct. A moderator answer that came before a late prediction → item
   born `answered`.
11. `opened_at` equals the earliest member when the flagged member is later; the edited case uses `edited_at`.
   Responsibility is checked across a handover.
12. Acknowledgement behaviour is unchanged (an ack-only burst gets no prediction and no item).
13–14. Every existing TG-M3/M4/M5 test passes unchanged; the switch defaults to blank.
15. Further checks: dual-purpose rows from §11; config blank and naive values; domain purity and boundary
    checks; no text in logs; the pure scoring of the benchmark.
16. PHP: `LiveAttentionQueueTest` (the Opened-by labels) and `ClassificationAccuracyPageTest` (C9 with
    denominators, no average).

## 15. Benchmark

- Fixture: `~/Projects/injaz-m5-fixtures/real-attention.jsonl`, outside Git. Each line is `{"text",
  "needs_response", "category"?}`, about 20–30 lines.
- I'll seed it with the brief's positives and near-misses; you add and check the real lines and labels.
- `FIXTURES=… make smoke-attention ARGS="--prompt classify_v2"`. Each line prints, never the text:
  - expected vs predicted needs_response;
  - the category;
  - the self-reported confidence;
  - the rule verdict (`evaluate`);
  - eligibility (an ack is excluded without a model call);
  - the route;
  - the gate result;
  - the resulting **opener** (rule / model / none / excluded).
- Summary:
  - needs_response agreed n/N;
  - **false negatives** and **false positives**, each with line numbers;
  - category exact (secondary);
  - opener tallies split by expected label. **Model-opened on expected-false is the new moderator work**, which
    is the key risk.
- The run exits non-zero on any mismatch.
- Whether to switch on is your call on those numbers. A prompt fault would mean a new `classify_v3`, which is
  outside this milestone.

## Verification

1. Run `make check` with Ollama quit: ruff, mypy, boundary checks, pytest, and the PHP suite.
2. Run the benchmark against `classify_v2` and record the counts in `research.md`.
3. Set `MODERATION_PROMPT_VERSION=classify_v2` and `MODERATION_AI_ATTENTION_FROM=<now>`, then restart
   `ai-worker`, `ai-classifier` and the poller.
4. **You** post «في محاضرة اليوم» from the student account. After about 90 s I verify with psql (no text
   columns):
   - `message_classifications`: `needs_response=t`, `path=live`, `prompt_version=classify_v2`;
   - `attention_items`: `source=ai`, `status=open`, `message_classification_id` set, `rule_version` NULL,
     `opened_at = sent_at`, the expected `responsible_moderator_id`;
   - the queue shows "Opened by: Model".
5. **You** reply as a moderator. I verify `status=answered`, the `first_response_*` fields, and FRT =
   `first_response_at − opened_at`.
6. Optional: post «تمام شكرا» and «… كان الشرح ممتاز» and verify that no item opens.

## Known limitations (go into quickstart)

- **Growing bursts.** If a burst is still growing when an earlier member's judgement runs, the model can open the
  item before a later member's rule signal arrives. The item is then `ai` where the rules would also have opened
  it. Timing is identical.
- **Classifier down.** While the classifier is down, implicit questions are not tracked; rule questions still
  are. Results that arrive within 24 h reconcile within one tick.
- **Hand-open, pre-existing.** `openByHand` takes no `chat_lock` and accepts a non-anchor member of a burst. That
  is unchanged and out of scope.
- **Rule-recall floor.** With the switch on, the rule-recall floor reads higher, because misses the model caught
  are not operator-added. The page shows C9's kept count beside it.
