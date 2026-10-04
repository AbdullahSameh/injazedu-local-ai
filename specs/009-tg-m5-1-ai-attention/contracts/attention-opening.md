# Contract: AI-assisted Attention Opening

**Feature**: `specs/009-tg-m5-1-ai-attention` · **Status**: durable from TG-M5.1 onwards. It amends
TG-M5's `classification-pipeline.md` R13/N1/F6 and TG-M5's FR-032 (the model's needs-response judgement was
measurement only) for **live** predictions only. Everything TG-M3's `attention-rules.md` decides — the burst,
the rule set, edits, what closes an item, attribution, ageing — is unchanged and still decides.

**The rule that carries all of it: the rule set has the first word; the model may add a second.** A live
prediction may open a question item only for a burst the rule set declined, only through TG-M3's own
`open_item`, and only on the anchor, `opened_at` and attribution a rule-opened item would have had. The model
never closes, dismisses, expires, re-dates or re-attributes anything.

---

## §1 — The gate

`app/domain/moderation/classification.py`, pure, the only definition (pipeline N7 applies):

- **G1.** `needs_response` is true.
- **G2.** `path = 'live'`. A catch-up prediction (`route = 'measurement_only'`) never passes (pipeline C2).
- **G3.** `route <> 'review'`. FR-030 already forbids a below-floor prediction from opening anything. The floor
  (0.60) is the only confidence condition, because a contract requires it; the incident threshold (0.85) is
  not a gate — confidence barely moves (TG-M5 Finding 2), and the benchmark and the pilot's dismissal rate are
  the control (§7, C9). Read from the stored route, never recomputed.
- **G4.** `category ∉ {SPAM_OR_AD, ABUSE, CHITCHAT}` — both instructions say needs_response is "always false" for
  these; a true value contradicts itself (D-TG-165, R8's question-side counterpart).
- **G5.** `created_at ≥ MODERATION_AI_ATTENTION_FROM`. Blank = off: nothing in this contract happens, and the
  system is exactly TG-M5 (D-TG-164).
- **G6.** `created_at < opened_at + MODERATION_ITEM_MAX_AGE_S` — never an item born expired (D-TG-167).

`proposes_attention` is G1–G4; `within_attention_window` is G5–G6. G1–G4 need only the prediction; G5–G6 need
the item's `opened_at`, which only `open_item` knows.

## §2 — Opening

- **O1.** `open_item` evaluates rule set v1 first, unchanged. Only when it declines **and** the switch is set
  does it consult predictions. An item both would open is `source = 'rule'`.
- **O2.** It reads the current predictions of the burst's members **inside `chat_lock`** and takes the first,
  in the burst's `(sent_at, message_id)` order, that passes G1–G6 — the same choice C6/M17 makes for the label
  shown on the queue.
- **O3.** The item: `source = 'ai'`, `rule_version = NULL` (`ck_attention_rule_version`),
  `message_classification_id` = that prediction (written once, never updated). The anchor, `opened_at` and
  `responsible_moderator_id` come from the same code a rule-opened item uses (§5).
- **O4.** The same preconditions as the rules: a measured chat; a person, not a moderator or bot; no service
  message in the burst. A burst already covered by any item converges on it (E2/E4) and consults nothing.
- **O5.** Stamping (`attention_evaluated_at`, `attention_item_id`) and the open-time lookback (C10) are TG-M3's,
  unchanged.

## §3 — Reconciliation: a prediction that lands after the burst was judged

- **I1.** When `classify_one` records a prediction that passes G1–G4 and the switch is set, it calls
  `attention.request_rejudgement` **in the same transaction**. Under `chat_lock`, that clears
  `attention_evaluated_at` on the message — only when the message has a personal sender, was already judged,
  and no item covers it. This is E5's own mechanism; the classifier judges nothing.
- **I2.** The sweep (every `MODERATION_TICK_INTERVAL_S`, 30 s) claims the message from TG-M3's authoritative
  work list and judges its burst through `open_item`. No new polling and no new queue.
- **I3.** Race-free. `open_item` stamps only under `chat_lock`, and the request reads and clears only under it.
  If the judgement holds the lock first, it cannot see the uncommitted prediction and declines, then the
  request clears the flag. If the request holds it first, the judgement reads the committed prediction. The
  sweep's `FOR UPDATE SKIP LOCKED` holds only rows whose flag is NULL, and the request updates only rows
  whose flag is NOT NULL, so no lock cycle is added.
- **I4.** Idempotent. `uq_attention_anchor` with `ON CONFLICT DO NOTHING`, E4's convergence and pipeline I1–I4
  (one prediction per message) make any replay — of the classification, the judgement or the sweep — land on
  the one item.

**Case A** (classified before the settle, the usual ~1 s): the request finds the message not yet judged and
does nothing; the settle-time judgement reads the prediction. **Case B** (classified after): the request puts
the message back; the next sweep opens the item.

## §4 — Live and catch-up

- **L1.** Only live predictions pass (G2). `classify_chat` never requests a re-judgement.
- **L2.** Every judgement path builds the switch the same way (`ai_attention_from_settings`): the fast path,
  the sweep and `rederive_chat --with-attention`. A re-judgement therefore opens a model item only where live
  judgement would have, and the result does not depend on which path got there first.
- **L3.** Switching on never reaches back: a prediction recorded before `MODERATION_AI_ATTENTION_FROM` never
  passes G5, whichever path re-judges its burst later.

## §5 — Time and attribution

- **T1.** `opened_at` is the burst's (B2): the earliest member's `sent_at`, even when the flagged member is a
  later one — never the classification time.
- **T2.** Edits (D-TG-168): a member's prediction of its **first-posted** words still counts after the member is
  edited; the anchor and `opened_at` follow E3 (the most recently edited member, at `edited_at`). The stored
  prediction is not "pre-edit wording re-read" in E1's sense — it is a durable record, so the same burst
  always reaches the same answer.
- **T3.** `responsible_moderator_id = responsible_at(chat, opened_at)` — the owner when the question was asked,
  not when the model answered.
- **T4.** A question a moderator answered before the late prediction landed: the item opens and the C10
  lookback closes it `answered` **in the same transaction**, with FRT = `first_response_at − opened_at`. It is
  never visible as open. That is TG-M3's existing answer for any item that opens after its answer (C10).

## §6 — Dual-purpose predictions

- **D1.** The question side (this contract) and the violation side (pipeline R1–R6) are decided
  independently (decision 1, D-TG-169), as TG-M4 already keeps a rule-opened item and an incident on the same
  message (TG-M4 I7).
- **D2.** So `COMPLAINT · needs_response · needs_moderation` opens a question item (if the rules declined)
  **and** is listed as a possible violation (inconsistent); `OTHER` with both, consistent and ≥ 0.85, opens a
  question item **and** an incident; `SPAM_OR_AD` / `ABUSE` with needs_response true open no question item (G4).

## §7 — The benchmark, before switching on

- **B1.** `FIXTURES=<path outside the repo> make smoke-attention [ARGS="--prompt classify_v2 --profile …"]`
  reads `{"text", "needs_response", "category"?}` JSONL and writes nothing. The real set lives outside Git
  (`~/Projects/injaz-m5-fixtures/real-attention.jsonl`); the shipped set is synthetic.
- **B2.** Each fixture is judged as a one-message burst, the way live traffic is: the rule set (`evaluate`),
  then eligibility (an acknowledgement never reaches the model), then the model, routed (`route_prediction`)
  and gated (`proposes_attention`). Each is the real function (N7).
- **B3.** The summary reports needs-response agreement, **false negatives** and **false positives** (with
  line numbers), category agreement (secondary), and the opener tallies — rule / model / none / excluded /
  error — split by label. **Model-opened on expected-false** is the new moderator work this milestone risks,
  printed on its own line.
- **B4.** It never prints a fixture's text, and exits non-zero on any mismatch. Whether to switch on is the
  operator's decision on those numbers. A prompt fault is a new `classify_vN`, never an edit (D-TG-136).

## §8 — What may never happen

- **N1.** A model-opened item whose `opened_at` is the classification time, or whose attribution is the owner
  at classification time.
- **N2.** Two items for one burst because both openers fired. The rule set decides first; uniqueness and E4
  backstop it.
- **N3.** A catch-up prediction, a below-floor prediction, a prediction recorded before the switch, or a
  needs-response claim on SPAM_OR_AD / ABUSE / CHITCHAT opening an item.
- **N4.** A prediction closing, dismissing, expiring, re-dating or re-attributing any item, or being written
  onto a rule- or operator-opened item.
- **N5.** Judgement logic in the classifier, or a second definition of the gate (in PHP, SQL or a test helper).
- **N6.** Message text in a log line, or an outbound message, alert or bot act of any kind.

## §9 — Limitations, stated rather than hidden

- **A growing burst.** When an earlier member's judgement runs before a later member's rule signal arrives,
  the model can open the item first. The item is then `ai` where the rules would also have opened it later.
  The anchor and `opened_at` are identical either way.
- **The classifier down.** While it is down, questions only the model would catch are not tracked; rule
  questions still are. Predictions that land within `MODERATION_ITEM_MAX_AGE_S` reconcile within one tick.
- **Hand-opening (pre-existing, unchanged).** It takes no `chat_lock` and accepts a burst's non-anchor member.
- **The recall floor.** With the switch on, rule misses the model caught are not operator-added, so the
  rule-recall floor reads higher. The accuracy page prints C9's kept count beside it.
