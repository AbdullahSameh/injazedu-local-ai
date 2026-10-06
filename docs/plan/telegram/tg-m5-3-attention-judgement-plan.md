# TG-M5.3 — A Separate Attention Judgement (Option B)

**Status:** plan, **approved by the operator on 2026-10-06 with every recommended decision** (§16). Nothing
here is implemented. `/speckit-specify` and implementation start only when the operator asks.
**Supersedes nothing.** `tg-m5-classify-v3-plan.md` and `specs/010-tg-m5-2-classify-v3/` stay as the historical
record of why this milestone exists. TG-M5.2 closed as *stopped under FR-216* on 2026-10-06.

## Context

TG-M5.1 lets a live prediction open a question item that rule set v1 declined. The signal is the
`needs_response` value of the same `classify_vN` call that judges adverts and abuse. Two milestones of evidence
show that one call cannot carry both judgements:

| Evidence | What it shows |
|---|---|
| Finding 10 (010) | Under v1/v2, needs-response was a pure function of the *category* on all 48 attention fixtures. Topic decided, not function. e2b + v2 opens 13 of 27 clear negatives. |
| Finding 11 (010) | On e2b, every wording that separated asking from informing moved the advert boundary (policy #21 → incident, real moderation #1 lost). Three rounds, no wording passed both. |
| Plan §16 (010) | **P2's attention wording worked on e2b**: 0/27 clear negatives opened, 0/13 positives missed. It failed only on the advert side, because it shared the prompt. |
| F1/F2 (010 research §2) | On e4b, the FR-205-compliant wording (generic nouns) re-opened extra #15. A one-sentence change to the needs-response wording flipped shipped #12 (a legitimate message) into an advert incident. |

FR-216 named the next step: **a separate needs-response judgement, as its own specification.** TG-M5.3 gives
the attention decision its own task, prompt, output, storage and qualification. `classify_v2` stays
byte-identical for moderation. This answers both failure modes at once: the attention wording can no longer
move the advert boundary, and the advert wording can no longer bias the attention decision.

**Plan name:** `docs/plan/telegram/tg-m5-3-attention-judgement-plan.md`.
- It follows `tg-m5-1-ai-attention-plan.md`: milestone number, then subject.
- *Attention* is the domain's established word: Attention Queue, `attention_items`, the attention-opening
  contract.
- *Judgement* is the repository's spelling (`request_rejudgement`, "per-fixture judgement").
- "Separate" describes the change relative to v3, not the thing being built, so it is left out of the name.

---

## 1. Scope and non-goals

**In scope**
- A new task, the **attention judgement**: one focused instruction answering "does this member's message need
  a moderator's response?", with its own output schema and allowlist.
- Immutable storage for its predictions, exclusions and failures.
- TG-M5.1's opener reads the attention judgement instead of the classification's `needs_response`.
- A model role for the task, and inactive candidate profiles for e2b and e4b.
- The qualification command, generalised into a task-agnostic core plus task suites. The attention suite is
  new; the moderation suite keeps 010's advert gates.
- A wording-selection protocol with a validation set, then a held-out set (written after the freeze) and the
  operator's fresh sample.
- The smallest metric and panel changes needed so the pilot gate (C9/M24) reads the new opener.

**Non-goals**
- Any change to `classify_v2`, routing, thresholds, incidents or TG-M4.
- Any change to TG-M3's rule set, bursts, settle window, attribution, matching or ageing.
- The deterministic no-link rule, which stays its own milestone.
- Burst-level (multi-message) model input.
- A prompt registry or `prompt_versions` table. 008 data-model §8 assigns that design to the assessment
  milestones; see §6.
- Fine-tuning, model chaining, or provisioning the production host.
- Catch-up (`path = 'catch_up'`) attention judgements. Deferred: see open decision 12.
- Reprocessing (`is_current` flips): TG-M8.

## 2. Responsibility boundaries

| Unit | Decides | Reads | May do |
|---|---|---|---|
| **Rule set v1** (TG-M3) | whether a burst carries an explicit question signal | burst texts, mention/reply facts | open `source='rule'`. **First word, unchanged** |
| **Moderation judgement** (`classify_v2`, TG-M5) | category, needs-moderation, severity, route | the first-posted, redacted text | open or list incidents. Its `needs_response` field is **measurement only again** |
| **Attention judgement** (new) | whether the writer needs a moderator's answer | the first-posted, redacted text | propose; `open_item` decides. Never closes, dismisses, expires, re-dates or re-attributes |
| **`open_item`** (TG-M3/TG-M5.1) | whether an item opens, its anchor, `opened_at`, owner | rules, then attention judgements, then the veto | the single insert |

**Domain contract vs serving.** Attention and Moderation are **independent judgements**:
- neither reads the other's output to decide whether to run;
- neither waits for the other;
- neither has an ordering dependency on the other.

The architecture allows them to run **concurrently** wherever the serving infrastructure supports it, for
example vLLM or several inference lanes on a production host. How many calls run at once, and in what order
when they compete for capacity, is a **scheduling policy of the deployment**, not part of the domain contract.

More generally, model-serving constraints must not shape the permanent domain design: Ollama's concurrency,
the development Mac's memory, current local hardware. They appear in this plan only as the *current*
deployment's policy and limits, and are labelled that way.

**The one cross-read** (open decision 3): `open_item` does not open an AI item on a message the moderation
judgement called `SPAM_OR_AD` or `ABUSE`. Such a message should be removed, not answered.
- **Read-only and one-way:** attention reads moderation's verdict; moderation never reads attention.
- **What it replaces:** TG-M5.1's G4, which existed only because both answers came from one self-contradicting
  prediction.
- **CHITCHAT is not vetoed.** A greeting-led question is CHITCHAT to the classifier but asking to the
  attention judgement.

## 3. End-to-end flow

```text
ingest: derive_message commits the row
   ├─ evaluate_attention, delayed MODERATION_BURST_GAP_S (90 s)   [TG-M3, unchanged]
   ├─ judge_attention(chat, msg)   ← new; independent of classify_message (no ordering dependency)
   │     attention eligibility (pure, one definition):
   │       AE1  classification eligibility E1–E8 (reuse `eligibility`)  → else excluded(reason)
   │       AE2  rule set v1 opens on this message's own first-posted words alone
   │            (`evaluate([text])`)                                    → else excluded('rule_opens')
   │     → gateway(role='attention', system=attention_vN, user=redacted text)
   │     → insert the immutable judgement
   │     → if live ∧ needs_response ∧ switch set: request_rejudgement (TG-M5.1 I1, same transaction)
   └─ classify_message(chat, msg)  [TG-M5, unchanged except: it no longer calls request_rejudgement]

settle (90 s later) or the sweep (30 s tick):
   open_item(burst) under chat_lock
     rules open?                → source='rule'                                      [unchanged]
     else switch set?           → the earliest member whose current attention judgement passes
                                   A1 live, A2 needs_response, G5–G6 window,
                                   V  no current classification ∈ {SPAM_OR_AD, ABUSE}
                                → source='ai', attention_judgement_id = that judgement
```

**Why AE2 is exact.** `evaluate` checks for "all acknowledgements" first, then for "any member with a
question signal". If one message's own words open, it is not an acknowledgement, so every burst containing it
opens too. The call could never be used, and skipping it is not a second definition of the rules: it calls the
same pure `evaluate`.
- **The one gap:** an edit inside the settle window that removes the signal. The burst then declines with no
  attention judgement on that member. This is stated as a limitation; hand-opening covers it.

**Timing alternatives considered** (open decision 5):

| Option | Calls | When the AI item can open | Verdict |
|---|---|---|---|
| **Ingest, with the AE2 skip** (recommended) | 1 + (1 − share skipped) per eligible message | at the settle (Case A, ~1–3 s of model time) | keeps TG-M5.1's usual path |
| Ingest, every eligible message | 2 per message | at the settle | wastes calls on certain rule-opens |
| After the settle, only when the burst's rules decline | fewest | always late: settle + queue + up to 30 s tick (Case B); a burst's N calls queue at once | judgement logic leaks into the opener |
| Dependent: attention runs only after classification says not SPAM/ABUSE | fewer on adverts | waits for the other judgement on every message | creates an ordering dependency between independent judgements; adverts are a small share |

**Concurrency and scheduling: deployment policy, not domain contract.** The two judgements are dispatched
independently at ingest and may run concurrently.
- **What happens depends on the serving infrastructure.**
  - **Today's local Ollama deployment:** the gateway's `llm` lane (`app/application/gateway/lanes.py`) admits
    one generation at a time machine-wide, so the two calls share a single constrained lane.
  - **A concurrent serving stack** (vLLM, or several lanes on a production host): both run in parallel, with
    no design change.
- **Current scheduling policy:** when both judgements need the same constrained inference lane, Attention is
  prioritised before Moderation, because it has the 90-second settle deadline and moderation has none.
  - **How:** it is implemented as configuration (enqueue order or queue priority), stated in the quickstart as
    the current policy, and changeable without touching the domain contract.
- **Not a domain rule:** sequential execution is not part of the contract. The contract requires only
  independence: no ordering, no waiting, and no input from the other judgement.
- **Out of scope:** lane capacity, worker thread count and queue topology are the gateway's (M1) and the
  deployment's concerns. Today's single-thread `ai-classifier` (Finding 4) matches a single-occupancy lane;
  with concurrent serving, its threads or services scale to the lane's capacity.

## 4. Data model (one additive revision)

**Options compared**

| Option | Immutability | Idempotency | Versions | Catch-up | Metrics / panel | Future tasks | Verdict |
|---|---|---|---|---|---|---|---|
| **A. A typed sibling table, `message_attention_judgements`, plus `message_attention_attempts`** | the same insert-only discipline as `message_classifications` | `uq … WHERE is_current`, `ON CONFLICT DO NOTHING` | `model_profile_id`, `model_run_id`, `prompt_version` | `path` + check, as 0007 | typed columns; the existing queries are untouched | per-message Telegram judgements reuse the pattern | **recommended** |
| B. A generic `ai_judgements(task, output jsonb, …)` | possible | possible | yes | yes | jsonb extraction everywhere, no check constraints; `message_classifications` stays separate anyway, so two patterns | assessment outputs are artefacts with a review lifecycle, not per-message judgements, so it would only ever hold Telegram rows | reject now; revisit if a third per-message judgement appears |
| C. A `task` discriminator on `message_classifications` | yes | `uq_classification_current` must widen | yes | yes | every C1–C9 query and panel read must add a filter; category, severity and needs_moderation would have to become NULLable | no | reject: high regression risk on shipped figures |
| D. Attention columns added to `message_classifications` later | **breaks**: the row is updated after the second call | — | — | — | — | — | reject |

**Recommended shape** (names are proposals for the spec):

- **`message_attention_judgements`**
  - **Columns:** `id`, `telegram_chat_id`, `telegram_message_id`, `model_profile_id` (`RESTRICT`), `model_run_id`
    (`SET NULL`), `prompt_version` varchar(40), `intent` varchar(20), `needs_response` boolean, `path`
    varchar(20), `is_current` boolean, `created_at`.
  - **`needs_response` is derived** by one pure domain function from `intent` and stored at insert, so the
    panel reads it and never recomputes it. There is deliberately no CHECK restating the mapping (008
    data-model §2's "no second definition" rule).
  - **Constraints:**
    - `fk_…_message` → `telegram_messages`;
    - `uq_…_identity (id, chat, message)`;
    - `uq_…_current … WHERE is_current`;
    - checks on `intent` and on `path ∈ {live, catch_up}` (catch-up is deferred, but the shape is kept so it
      needs no later migration);
    - `ix_…_profile (model_profile_id, prompt_version)`.
  - **No text, no UPDATE, no DELETE.**
- **`message_attention_attempts`:** `outcome` is `excluded` or `failed`.
  - `reason` is E1–E8's eight reasons, plus `rule_opens` for exclusions, or the gateway failure kinds for
    failures.
  - `model_profile_id` is required exactly for a failure. `uq_…_exclusion` makes each exclusion a single row;
    failures are appended.
  - This mirrors 0007 §3 without touching its table or its C5 status queries.
- **`attention_items.attention_judgement_id`:** a nullable FK.
  - New check `ck_attention_ai_link`: `source = 'ai'` ⇔ exactly one of `message_classification_id` /
    `attention_judgement_id` is set, and neither is set otherwise.
  - Historical TG-M5.1 items keep their `message_classification_id`.
- **`model_profiles`:** `ck_model_profiles_role` gains `attention` (open decision 4).
  `uq_model_profiles_one_active_per_role` then gives exactly one active attention model.
- **Revision id:** the next free one after `0007`. The roadmap's reservation of `0008`–`0009` for TG-M6/TG-M8
  is a documentation convention (master plan: "whichever ships first wins"). The spec updates that table; it
  is not an architectural constraint.

## 5. Output schema

**Recommended** (open decision 2):

```json
{"intent": "asking" | "informing" | "social" | "offering" | "other"}
```

`needs_response = (intent == "asking")`, derived in `app/domain/moderation/…`. There is no confidence field.
- **Why an enum and not a boolean.** The model must name what the message *does*. This is the
  function-over-topic distinction Finding 10 asks for, and it yields a "why" for metrics and dismissals.
  `offering` gives adverts an explicit non-asking bucket, without the attention task judging whether a
  message breaks a rule.
- **Why no confidence.** Finding 2: self-reported confidence was 0.90–1.00 on everything. The controls are
  the benchmark and the pilot's dismissal rate (M24). Dropping the field also removes a floor gate, TG-M5.1's
  G3, which only existed because FR-030 bound the classification's confidence.
- **The boolean schema is held in reserve.** It is used only if the enum underperforms in the selection round
  (§8.3).

## 6. Prompt and version structure

- **The file:** `app/prompts/moderation/attention_v1.md`, version = file stem, pinned by SHA-256. A new wording
  is a new file (D-TG-136).
- **Its own allowlist and setting:** `ModerationAttentionPromptVersion = Literal["attention_v1"]` and
  `MODERATION_ATTENTION_PROMPT_VERSION`. Blank = no attention calls, and nothing is recorded (like "no active
  profile").
- **The pin test generalises:** every file under `app/prompts/moderation/` belongs to exactly one allowlist and
  is pinned. The every-instruction G4 test stays scoped to `classify_*`.
- **The request:** `system` = the pinned instruction and `user` = the redacted first-posted text, exactly
  pipeline P1–P5. The safeguards stack:
  1. **Capability bound** (the strongest): the worst a manipulated answer can do is open a question item a
     moderator dismisses. No close, no act, no outbound message.
  2. **The closed output schema** (pydantic `Literal`). Anything else is a recorded `structured_output_invalid`
     failure and opens nothing.
  3. **The derivation lives in the domain**, not in the model.
  4. **Redaction before the gateway.** No text in logs.
  5. **Injection-shaped lines** in the validation set ("ignore the instructions…"), counted like any other
     line.
- **Candidate wordings during selection** are not shipped files. The qualification command accepts
  `--candidate-file` from the read-only fixtures mount. Such a run prints `CANDIDATE` and can never print
  `QUALIFIED`. Only an allowlisted, pinned version can qualify.
- **Shared wording:** small duplication with `classify_v2` (the intro, the normalisation and redaction note) is
  accepted. No base template.
- **Project-wide prompt management** belongs to a later milestone, before assessment generation: a registry
  synced from Git, `prompt_version_id`, and the panel read-only with outcome figures. TG-M5.3 only adds a
  second allowlist on the existing file + pin pattern.

## 7. Model and profile strategy

- **A new role, `attention`** (open decision 4), so the task's model is chosen independently: principle E.
  - **Cost:** the role check, the `Role`/`GenerationRole` literals, `registry.resolve('attention')`, and the
    panel's role option.
  - **Rejected:** reusing `moderation`, which would force one model for both tasks forever.
- **Candidates**, inactive, with the e2b/e4b moderation params (`num_ctx 2048`, `num_predict 128`,
  `temperature 0`, `reasoning_effort none`): `ollama-gemma4-e2b-attention` and `ollama-gemma4-e4b-attention`.
  Profiles 14 and 17 stay as they are. The e4b model stays installed.
- **Goal:** the smallest model that qualifies reliably for this task.
  - **e2b is the hypothesis** (P2's attention side on e2b was 0/27 and 0/13) and is measured first.
  - **e4b is the fallback.**
  - **Production-host candidates** are a qualification step on that host, never a silent change here.
- **Memory is a deployment limit, not a design input.**
  - **On the current development host**, different models for the two tasks mean Ollama swaps models (load
    time and RAM). The 16 GB Mac cannot hold e2b + e4b comfortably (Finding 13). So in *development*, the same
    model is preferred unless qualification forces otherwise.
  - **The architecture allows a different model per task.** A production host picks per task on its own
    qualification results and capacity.

## 8. Qualification and benchmark

### 8.1 Structure (open decision 7)

Generalise `app/scripts/qualify_moderation.py` into:
- a **task-agnostic core**: set discovery, fixture keys (`label_class`, `tracked`), the per-fixture judgement
  seam, repeat comparison, latency percentiles, errors, the gate table, the verdict, exit codes, and the
  "no text" formatter;
- **task suites**: `moderation`, today's advert gates, and `attention`, which is new.

Interface: `make qualify TASK=moderation|attention PROFILE=… PROMPT=… FIXTURES_DIR=… [REPEAT=2]`, with
`make qualify-moderation` kept as an alias.
- **Why not one combined command:** each switch is per task. AI Attention switch-on depends on the
  attention pair; a moderation pair change depends on the moderation pair.
- **Assessment tasks** later plug in as suites over the same core.
- **A convenience wrapper** that runs both suites for the configured deployment can come later. It is not
  needed to decide anything.

### 8.2 Gates

**The attention suite** (every judgement takes the real path: rules first, then AE1/AE2, then the model, then
A1–A2):

| # | Gate | Passes when |
|---|---|---|
| A1 | Tuning: clear negatives model-opened | = 0 |
| A2 | Tuning: clear positives missed | = 0 |
| A3 | Validation: clear negatives model-opened / rule-declined clear positives missed | ≤ 1 / ≤ 1 |
| A4 | Held-out: the same | ≤ 1 / ≤ 1 of ≥ 10 |
| A5 | Fresh sample: the same | ≤ 1 / ≤ 1 (required for `QUALIFIED`) |
| A6 | Violations answered `asking` (every moderation-set line with needs_moderation true; no veto credited) | threshold set in the spec (proposed ≤ 1, lines reported) |
| A7 | Repeat | 0 differing lines, `--repeat` ≥ 2 |
| A8 | Latency | p95 single call ≤ 10 s. The per-message estimate (§10) is reported for the serving mode of the host the run is on |
| A9 | Errors | = 0 |
| — | Ambiguous (Policy S); intent agreement | reported, never gated |

**The moderation suite:** 010's Q5–Q7 and Q10–Q12 unchanged, plus repeat and errors, over `classify_v2` and the
moderation profile. Q1–Q4 and Q9 move to the attention suite as A1–A5.

**The production rule (R1 restated):** `MODERATION_AI_ATTENTION_FROM` may be set only when the active attention
profile + `MODERATION_ATTENTION_PROMPT_VERSION` is `QUALIFIED` on that host. Any change to the moderation pair
requires a `QUALIFIED` moderation suite.

### 8.3 Wording selection: is the distinction learned, or are nouns memorised? (open decision 8)

The candidates are fixed **before any run**, all with the §5 schema:

| Candidate | Content |
|---|---|
| **W1, generic** | asking / informing / mixed / Policy S / social / offering; no domain nouns |
| **W2, P2-derived** | P2's measured Asking/Informing paragraphs (010 research §2), adapted to the single task, with P2's noun lists as measured |
| **W3, generic + domain glossary** | W1 plus one sentence naming what the *service* provides (lectures, recordings, links, books, exams, registration, the platform). A glossary of the domain, not fixture topics |

1. **Selection round, run once.**
   - **Matrix:** each candidate × {e2b, e4b}, `--repeat 2`, on the tuning sets plus a new **validation set**.
   - **The validation set:** synthetic, about 40 lines, on topics outside **both** the tuning vocabulary and
     the held-out list. For example: app installation, attendance/absence, study-plan changes, mock-exam
     access, audio/video quality, account name change, refund status, mentor contact.
   - **Reading the noun effect:** if W3 or W2 beat W1 only on in-vocabulary tuning lines, and not on
     validation, the nouns are memorisation. If they also win on validation, they are policy, and the
     glossary stays.
2. **The decision rule, written before running:**
   - take the smallest model with any candidate passing A1, A2, A3, A6, A7 and A9;
   - among passing candidates, prefer W1 > W3 > W2 (fewest assumptions first).
3. **At most one revision round**, restricted to the failing sentence, then freeze.
4. **Stop condition:** if nothing passes after the revision, stop and report, as FR-216 did. There are no
   further rounds.

### 8.4 Sets

| Set | Kind | Role | Status |
|---|---|---|---|
| `real-attention*.jsonl` (operator's, outside Git) | attention | tuning | exists. **T031's annotations are needed first** (ambiguous lines, plan §13) |
| `attention_smoke_fixtures.jsonl` | attention | tuning | exists, annotated |
| `attention_validation_fixtures.jsonl` | attention | validation (selection) | new, written before the selection round |
| `attention_heldout_fixtures.jsonl` | attention | held-out | new, **written after the freeze**; 010 data-model §3's grid and topics, which were never written |
| `fresh-attention.jsonl` (operator's) | attention | fresh sample | operator; labelled before any run |
| `real-moderation.jsonl`, `moderation_smoke*_fixtures.jsonl` | moderation | moderation suite; **also attention A6** | exist; tracked #1 and #11 unchanged |

## 9. Held-out and fresh real sample

- **Held-out:** written only after `attention_vN` is pinned, run once on the chosen pair, never edited
  afterwards, and a failure is reported as it stands (010 X2/X4). Its topics (certificate, grades, homework
  submission, payment receipt, group link, exam hall, meeting app, timetable file) differ from the tuning and
  validation vocabulary. At least 10 rule-declined clear positives; at least 80% without a question mark.
- **Fresh sample:** 20–30 real messages, labelled by the operator before any run, never tuned against.
  Required for `QUALIFIED`, as 010 Q9.
- **Contamination guard:** the implementer never sees validation results before writing the held-out set's
  topics (they are fixed in this plan), and never sees held-out results before freezing.

## 10. Latency and cost

- **Calls per eligible message:** 1 (moderation) + 1 (attention), minus the share AE2 skips. On the
  fixtures, a message's own words open the rules on 6/24 (original real set), 1/24 (paired set) and 2/14
  (shipped), so about 5–25% would be skipped. The pilot measures the real share.
- **Model time per message depends on the serving mode, not on the design.**
  - **Current local deployment** (single-occupancy lane, one-thread `ai-classifier`, 010's measured medians):
    - **e2b:** ~0.85 s per call, so ~1.7 s per message and ~35 messages a minute;
    - **e4b:** ~1.4 s per call, so ~2.8 s per message and ~21 a minute.
    - Under the current scheduling policy the attention call goes first, so its own wait is about one call
      per message ahead of it in the queue.
  - **Concurrent serving:** per-message time approaches the slower of the two calls, not their sum, and the
    backlog drains in parallel.
- **Deadline:** an attention judgement must land before its burst's settle (90 s). On the current local
  deployment, a backlog of about 50 simultaneous messages still makes it on e2b, and about 30 on e4b.
  - **A late judgement is still correct:** Case B, `request_rejudgement` and the sweep, up to 30 s later.
- **New figure:** the share of attention judgements landing before their message's settle (§13). This replaces
  SC-207's proxy with a measured fact for whatever serving mode is deployed.
- **Per-message latency in qualification:** the attention suite reports the per-message estimate for the
  host's serving mode:
  - the sum of the two p95s on a single-occupancy lane;
  - the larger of the two on a concurrent one.

  The threshold is fixed in the spec as a deadline property (lands before the settle), not as a
  serial-execution assumption.

## 11. Failure, retry, idempotency, immutability

These mirror TG-M5's F1–F6 and I1–I4, per task:
- **Claims and writes:**
  - **A claim key per task** (`ai:mod:attention:msg`), so the two tasks never block each other's claims.
  - **One idempotent insert** on `uq_…_current`; a replay is `already_judged`.
  - **Exclusions** are recorded once; **failures** are appended and name the model.
  - **No active attention profile or a blank prompt:** nothing recorded, no call.
- **Retries:**
  - **Transient errors** (unreachable, timeout, circuit open) retry at task level with doubling backoff, up to
    `MODERATION_CLASSIFY_MAX_ATTEMPTS`. The gateway runs with `max_retries=0` (Finding 6).
  - **Final errors** (truncated, invalid structure) are recorded failures that open nothing.
- **Immutability:** no UPDATE or DELETE on judgements. `is_current` stays true until TG-M8. The judgement reads
  the captured first-posted words (Finding 5), not edits.
- **Failure isolation:** a failed attention judgement never blocks classification, and the reverse holds too.
  The rules still open explicit questions while either model is down.

## 12. Integration

**TG-M3:** unchanged. The rule set keeps the first word. The burst, settle, E1–E5 edits, anchor, `opened_at`,
`responsible_at`, the C10 lookback, matching and ageing all apply to AI items exactly as today.

**TG-M5:** `classify_v2` and its route, incidents and possible violations are unchanged. Its `needs_response`
returns to measurement only: `classify_one` stops calling `request_rejudgement`. Contract R13/N1/F6 get a
dated re-amendment.

**TG-M5.1** (`attention-opening.md` gets a dated amendment, not a rewrite):

| Item | Change |
|---|---|
| G1–G4 | replaced by A1 `path='live'`, A2 `needs_response` (derived from `intent`), and V, the SPAM_OR_AD/ABUSE veto. G3 lapses (no confidence) |
| G5–G6 `within_attention_window` | unchanged. The judgement's `created_at` is compared with the switch and the item's age |
| O1–O5 | unchanged, except O3: the item carries `attention_judgement_id` |
| I1–I4 reconciliation | unchanged mechanism, now called from the attention judgement's transaction |
| L1–L3 live vs catch-up | unchanged: only live judgements pass; switching on never reaches back (G5) |
| T1–T4 | unchanged |
| D1–D2 dual purpose | now two judgements: an incident and a question item can both open; adverts and abuse are vetoed on the question side |
| `source='ai'` | unchanged meaning; the link column depends on era (the §4 check) |
| No backfill | unchanged. Historical items keep their classification link; nothing is re-derived |

**Removed, not kept as a fallback** (open decision 9): the classification-sourced proposal. It never
qualified (Finding 10), and two sources would be two definitions of "the model proposes".
- **The deploy-time consequence:** once TG-M5.3 deploys with `MODERATION_ATTENTION_PROMPT_VERSION` blank, AI
  opening stops, even where `MODERATION_AI_ATTENTION_FROM` is set. That affects development, where the switch
  is set today.

## 13. Observability and metrics

- **C9** (model-opened questions, the M24 pilot gate):
  - groups by the *opening* judgement's (model, prompt);
  - unions the history (classification-linked, TG-M5.1) with the new rows (attention-linked, TG-M5.3);
  - each era has its own rows, never pooled (K3).
- **C6** (the queue label): shows the attention judgement's intent on the item's earliest `asking` member. The
  classification's category stays available.
- **C1/C2:** attention-judgement rows are added beside the classification rows, grouped by attention prompt.
  - **Limit:** rule-opened members are mostly AE2-skipped. The attention model's agreement on rule-opened
    questions therefore comes from the benchmark, not production. This is stated on the page.
- **New, C10 (coverage and timeliness):**
  - each eligible message's attention status: judged / excluded (reason, including `rule_opens`) / failed /
    not yet;
  - the share of judgements landing before the settle, per model.
- **The panel:** the SQL above in the existing pages. No state, gate or derivation is computed in PHP; it reads
  stored `needs_response`, `intent` and links. `DatabaseTransactions` tests, as before.

## 14. Migration, rollout, rollback

1. **One additive revision:** the two tables, the role check, `attention_items.attention_judgement_id` with
   `ck_attention_ai_link`. No `GRANT`; the default ACL applies. Existing rows satisfy every new constraint.
2. **Code ships dark:** a blank `MODERATION_ATTENTION_PROMPT_VERSION` means no calls. Note §12's
   consequence for the development switch.
3. **Seed** the two inactive attention profiles.
4. **Selection round** (§8.3), on e2b first. Then freeze `attention_v1`, run the held-out set once, add the
   operator's fresh sample, and reach `QUALIFIED` or stop.
5. **Development shadow:** activate the attention profile and set the prompt. Judgements accumulate; C10 shows
   coverage and timeliness. The opening switch can stay set.
6. **Pilot:** M24 ≤ 10% dismissed over ≥ 30 model-opened items, as SC-206.
7. **Production host:** qualify the host's own candidates there, then configure the same way.

**Rollback**
- **Blank `MODERATION_AI_ATTENTION_FROM`:** no AI items; judgements continue for measurement.
- **Blank the attention prompt:** no calls at all.
- **The revision is forward-only once judgements exist,** because the data is immutable. A downgrade drops
  only empty tables.

## 15. Risks

| Risk | Mitigation |
|---|---|
| **Overfitting** the wording to about 60 tuning lines | Candidates fixed before running; one selection round + ≤ 1 revision; an off-vocabulary validation set; held-out written after the freeze and run once; a fresh real sample; a stop condition |
| **Noun memorisation** (the #15 lesson) | W1 vs W3 vs W2 compared on validation topics outside every list (§8.3) |
| **Coupling** through the veto | One-way, read-only, two categories. A6 measures the attention judgement alone; the veto is never credited |
| **Late judgements** under backlog | The current scheduling policy (Attention first on a shared constrained lane); concurrent serving where available; the C10 timeliness figure; Case B reconciliation is already correct |
| **Serving limits leaking into the domain** (lane, Mac memory) | Independence is the contract; ordering, concurrency, threads and model placement are deployment policy, labelled as current, changeable without a contract change |
| **The one-message benchmark vs real bursts** | Unchanged from TG-M5.1 (D-TG-171); the pilot's dismissal rate is the backstop |
| **An edit removes the signal of an AE2-skipped message** | Stated limitation; rare; hand-opening |
| **Model swapping** if the two tasks need different models | Same-model preference; memory checked during qualification |
| **Label ambiguity** (Policy S) | Ambiguous lines are reported, never gated; T031 annotations; label reviews stay the operator's |
| **A metrics discontinuity** (C9 eras) | Per-era rows; no pooling |
| **Prompt injection** | §6's stack; the capability bound is the real control |

## 16. Decisions: approved 2026-10-06, every recommended option

1. **Storage:** typed sibling tables (recommended) vs a generic judgements table.
2. **Output:** an `intent` enum with derived `needs_response` and no confidence (recommended), vs a boolean.
3. **Veto:** SPAM_OR_AD/ABUSE classifications veto AI attention opening (recommended), vs no cross-read.
4. **Model role:** a new `attention` role (recommended), vs reusing `moderation`.
5. **Call timing:** at ingest with the AE2 rule skip (recommended), vs every message, vs after the settle. The
   two judgements are independent and may run concurrently. The *current* scheduling policy prioritises
   Attention before Moderation only when both need the same constrained inference lane; it is not a contract
   rule.
6. **Shadow mode:** calls run whenever the attention prompt is configured, independent of the opening switch
   (recommended).
7. **Qualification:** a generic core with task suites, `make qualify TASK=…` (recommended). A6's threshold
   starts from the proposed ≤ 1, and the per-message latency threshold is a deadline property (it lands
   before the settle). The spec fixes both values.
8. **Wording protocol:** W1/W2/W3 × e2b/e4b, one selection round + ≤ 1 revision, a validation set, the
   preference order, and the stop condition.
9. **Remove the classification-sourced opener** (recommended), accepting that development AI opening pauses
   until `attention_v1` qualifies.
10. **Revision numbering:** take the next free id and update the roadmap's reservation table.
11. **Names:** `attention_v1`, `MODERATION_ATTENTION_PROMPT_VERSION`, `message_attention_judgements`,
    `message_attention_attempts`, `attention_judgement_id`.
12. **Attention catch-up:** deferred (recommended) vs included as measurement-only.

## 17. Next Spec-Kit step after approval

1. **Operator:** T031's annotations of the external attention sets (ambiguous lines; real moderation #1
   `no-link-rule`). The fresh sample can follow, but must exist before `QUALIFIED`.
2. **`/speckit-specify`:** "TG-M5.3 per `docs/plan/telegram/tg-m5-3-attention-judgement-plan.md`, with the
   approved decisions", giving `specs/011-tg-m5-3-attention-judgement/`.
3. **`/speckit-clarify`** for whatever §16 left open, then `/speckit-plan`. The contracts:
   - `attention-judgement.md`: AE1–AE2, A1–A2, V, the schema and failures;
   - `qualification.md` v2: the core plus suites, gates A1–A9;
   - dated amendments to 008's pipeline/metrics and 009's attention-opening contract.
4. **`/speckit-tasks`**, then implementation, which starts only on the operator's go-ahead.

## Verification (when implemented)

- **`make check` with Ollama quit:**
  - the pins, the generalised "one set per allowlist" test, and the G4 test on `classify_*`;
  - AE1/AE2, A1/A2/V and the intent derivation as pure tests;
  - the judgement insert's idempotency and immutability on `injaz_ai_test`;
  - `open_item`: rules first, an attention item linked through `attention_judgement_id`, the veto, and
    `ck_attention_ai_link` rejecting both links or neither;
  - reconciliation Case A and Case B;
  - independence: each judgement records and opens correctly with the other absent, failed or later; no
    code path waits on, orders after, or reads the other's output, except the open-time veto;
  - catch-up never opening;
  - C9 era rows and the C10 figures;
  - every TG-M3, TG-M4, TG-M5 and TG-M5.1 suite unchanged in outcome.
- **The qualification runs:**
  - the selection matrix, the freeze, the held-out run once, and the fresh sample, with counts recorded in
    011's research;
  - 010's C2/C3 checks (no rows written, no Arabic characters in output) on every run.
- **The development shadow week:** the C10 coverage and timeliness figures, then the pilot's M24.
