# Research: TG-M5.1 — AI-assisted Attention Opening

Decisions continue TG-M5's numbering (last: D-TG-163). Every figure here is a count — never message text.

## §0 — Why now

- `classify_v2` records `needs_response = true` on implicit questions the rule set cannot see. «في محاضرة
  اليوم» has no `؟`, no interrogative and no support pattern; this was observed in the development group on
  2026-10-02.
- TG-M5's own design deferred acting on that judgement until evidence existed (008 spec Out of Scope). The
  benchmark below is that evidence, gathered before the switch is set.

## §1 — Decisions

- **D-TG-164 — A dated switch, `MODERATION_AI_ATTENTION_FROM`, not a boolean.** A boolean makes
  `rederive_chat --with-attention`, which races the live sweep, open model items for predictions recorded
  while the flag was off. Comparing a stored `created_at` with a configured instant makes the decision a
  function of stored facts, so every path reaches the same answer. Blank = off = TG-M5.
- **D-TG-165 — needs_response on SPAM_OR_AD, ABUSE or CHITCHAT is ignored.** Both instructions say "always
  false" for these. A true value contradicts itself — R8's two-way consistency, applied to the question side.
- **D-TG-166 — Reconciliation is E5's mechanism.** The classifier clears `attention_evaluated_at` under
  `chat_lock`, in the prediction's own transaction, and the 30 s sweep re-judges. This adds no polling, no
  queue and no second judgement path. The lock argument is contract I3.
- **D-TG-167 — No item born expired.** A prediction recorded `MODERATION_ITEM_MAX_AGE_S` or more after
  `opened_at` opens nothing. Such an item would count as unanswered, permanently, against a moderator whose
  queue never showed it.
- **D-TG-168 — An edited member's first-posted prediction counts; the clock is E3's.** Typo fixes inside the
  settle window are common. Ignoring them would miss exactly the implicit questions this milestone exists
  for, and `edited_at` is the conservative clock.
- **D-TG-169 — Dual-purpose predictions open both units, independently.** This follows TG-M4 I7, which
  already keeps a rule-opened item and an incident on one message.
- **D-TG-170 — C9, and an amended reading of M19.** Model-opened questions per model: dismissed ÷ opened is
  the pilot's operational gate (Finding 2: confidence does not separate right from wrong). C7 is unchanged;
  the page prints the kept count beside the recall floor.
- **D-TG-171 — The benchmark judges each fixture as a one-message burst, rules first.** Without that, the
  number that matters cannot be read: the model's false positives that become new moderator work, since a
  false positive the rules already opened costs nothing new.

## §2 — The benchmark, before switching on

`FIXTURES=~/Projects/injaz-m5-fixtures/real-attention.jsonl make smoke-attention ARGS="--prompt classify_v2"`

### Run 1 — 2026-10-03, `ollama-gemma4-e2b-moderation`, floor 0.600 / threshold 0.850

**The fixture set.** 24 lines, outside the repo. 15 are expected true: 4 explicit questions and 11 implicit or
support. 9 are expected false: near-miss statements and acknowledgements. The labels are a **first draft by the
implementer** — taken from the operator brief's examples plus sanitised variants — and are pending the
operator's review and real additions.

| | `classify_v2` | `classify_v1` |
|---|---|---|
| needs_response agreed | 21/24 | 20/24 |
| false negatives | 0 | 1 (#9) |
| false positives | 3 (#18, #21, #22) | 3 (#18, #21, #22) |
| **model-opened on expected-false** | **3 / 9** | **3 / 9** |
| opener, expected true | rule 6 · model 9 · none 0 | rule 6 · model 8 · none 1 |
| opener, expected false | rule 0 · model 3 · none 6 | rule 0 · model 3 · none 6 |
| category exact (secondary) | 13/15 | 13/15 |

Shipped synthetic set, `classify_v2`: 14/15 matched; 0 false negatives; 1 false positive (#10); model-opened on
expected-false 1/6.

**Finding 9 — the model reads an announcement as a question.** Every false positive, in both sets and under
both instructions, is a student *telling* the group something: a link or handout posted, a class cancelled as
already announced, a platform working again. All came back `QUESTION_*` with `needs_response = true` at
0.90–0.95. Self-reported confidence does not separate them (Finding 2 again). Every implicit question
`classify_v2` was given, it caught (9/9 beyond the rule set).

**Reading.** With the switch on, this set predicts roughly one unnecessary item for every three near-miss
announcements. The cost is a dismissal ("Not a real question"), which C9 counts. Whether that rate is
acceptable for a pilot is the operator's decision. If it is not, the fix is a new instruction version
(`classify_v3`, D-TG-136) that separates informing from asking — never an edit, and outside this milestone. The
switch, the gate and C9 stay as they are.
