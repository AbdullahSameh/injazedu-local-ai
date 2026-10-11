# Review: the rules open, the model advises — a rule + AI hybrid for Attention

**Date**: 2026-10-10 · **Status**: architecture review only. Nothing in the code, schema, settings, prompts, fixtures
or evidence was changed. · **Asked by**: the operator, after TG-M5.3 closed (second cycle stopped under W-7′).

**Inputs read**:
- the code paths in §2;
- 011's `spec.md`, `research.md` (Findings 14–19, D-TG-182…199, §2 runs), its four contracts;
- the plan of record, the v2 addendum, and 008's metric and panel contracts.

**Probes run**:
- read-only counts on the development database (one `BEGIN READ ONLY … ROLLBACK`);
- a pure-function probe of rule set v1 over the labelled real sets outside the repository.

Both printed counts and literal names only, never message text.

---

## 0 — The answer in one page

**Recommendation: proceed with changes.** The hybrid is the right *target*, and it is the only option of the
three that works on the population where the noise is. It cannot deliver its benefit as proposed, for two
reasons found in the code and the evidence.

1. **Rule-opened items have no attention judgement today, by design.**
   - AE2 (`attention_exclusion`, `app/domain/moderation/attention_judgement.py:36-49`) excludes every message
     whose own words open rule set v1. It records `rule_opens` and makes no call. Its rationale was that "the
     judgement can never be read" (D-TG-186).
   - The hybrid's whole input is exactly that population.
   - On the development database, **19 of 19** rule-opened items have no attention record on any burst member.
2. **No instruction exists whose answers mean Policy D′.**
   - `attention_v1` encodes Policy D, under which most of the operator's motivating examples are `asking`. On
     exactly those items it would advise "keep open".
   - Showing it would contradict the operator's own D′ guidance on the same row.
   - Moreover, **no qualification run has ever sent a rule-opened line to the model**: the scorer returns before
     the call (`app/scripts/qualification/attention.py:336-338`, `:365-367`). So the hybrid's input population
     is unmeasured for every wording, frozen or candidate.

**What does fit, with no schema change:**
- The judgement is per message, immutable, and carries its own `created_at`.
- Items reach their burst members through `telegram_messages.attention_item_id`. This is the same join C1 and
  C6 already use for classifications.
- The human's dismissal reason is already stored in `close_reason`.

So display, measurement and agreement tracking need only:
- a contract amendment (lift AE2);
- one more contracted SQL reading (like C6);
- one new figure (like C1);
- one dated display setting.

**What the proposal should change:**
- **Measure blind before showing anything.** Advice that moderators can see contaminates the very labels you
  want to evaluate it with.
- **Show the intent, not a suggested reason or a pre-selected button.** `intent ≠ asking` maps to several
  reasons, or to none (§4.5).
- **Derive "uncertain" from stored facts, not from a new model output or column.** It covers an incomplete
  reading, a multi-message burst, or `other`.
- **Qualify the filter role on its own terms.** A filter's dangerous error is the opposite of an opener's: a
  *miss*, meaning `asking` read as not-asking, becomes a wrong "dismiss" hint.

**Main architectural finding.** AE2 makes the rule-opened population invisible to the attention judgement, in the
live path and in qualification alike. Lifting it changes no opening behaviour (§4.3), but it is a contract change
and it shifts two figures' meaning from a dated point.

**Biggest risk.** A wrong "not asking" reading on a real question, followed by a moderator who trusts it. A
dismissed item leaves the unanswered figure entirely (M10). The miss becomes invisible: no KPI, no expiry and no
operator-added item records it.

**Recommended next step (no code).** Run rules-only and dismiss with reasons, as planned. Every reasoned
dismissal made *now*, before any model reading is visible, is uncontaminated ground truth for rule-opened items.
In parallel, the operator labels a sample of real **rule-opened** messages under D′ (outside the repository). It
should have enough rule-opened `asking` lines to gate misses (§9). Only then is a filter-feasibility measurement
(§12, phase B) worth running.

---

## 1 — Current state, verified

| # | Finding | Where |
|---|---|---|
| F1 | AE2 excludes a message whose own normalised words open v1 (`evaluate([facts.text])`), recording `excluded/rule_opens` with no call. Only the words are evaluated, not the mention or reply signals. | `domain/moderation/attention_judgement.py:36-49`; `application/moderation/attention_judgement.py:271-279` |
| F2 | Dispatch: `derive_message` sends `judge_attention` for every newly inserted message at ingest, with no settle window, before `classify_message`. Re-derivation sends nothing (L1). | `application/moderation/messages.py:294-297` |
| F3 | With `MODERATION_ATTENTION_PROMPT_VERSION` blank, `judge_one` returns `no_prompt`: no claim, no call, no row (P4). **Both settings are blank today, so nothing is being judged at all.** | `attention_judgement.py:249-251`; `.env` (verified 2026-10-09) |
| F4 | The judgement row is one per message (`uq_attention_judgement_current`), immutable, with `intent`, `needs_response`, `prompt_version`, `model_profile_id`, `path` and `created_at`. It has no confidence and no text. | `models_moderation.py:895-958` |
| F5 | `attention_items.attention_judgement_id` means *the judgement that opened this item*. `ck_attention_ai_link` forbids it on `rule` and `operator` items. **It must not be reused to attach advice.** | `models_moderation.py:1030-1045` |
| F6 | `open_item` consults judgements only in the `elif` after the rules decline (`_model_proposal`). A rule-opened burst never reads one: `source='rule'`, `rule_version=1`, and `opened_at`/anchor come from the burst alone. | `application/moderation/attention.py:364-385` |
| F7 | Item ↔ members: `telegram_messages.attention_item_id` is set by `open_item` and never cleared. C1 and C6 already join `m.attention_item_id = ai.id OR m.message_id = ai.telegram_message_id`. | `attention.py:419-427`; `ClassificationMetrics.php:69-88, 316-340` |
| F8 | The queue already shows one model column: **"Model's view"**, the *classification's* category and confidence (C6). Q1–Q2 make it display-only: it never filters, sorts or hides a row. Dismissals are three row actions through the guarded `closeIfOpen`, with one shared confirmation stating each reason (K2). There is no bulk action. | `LiveAttentionQueue.php:140-185, 232-239` |
| F9 | D-TG-197 explicitly **deferred C1/C2 attention rows** ("AE2 skips most rule-opened members, so these would be near-empty"). The hybrid's agreement figure is exactly that deferred C1-for-attention. | `research.md` D-TG-197 |
| F10 | Every dismissal figure counts `status='dismissed'` whatever the reason (K5). The per-reason columns on C7/C9 are diagnostic, and no gate reads them (K10). Dismissed items leave the FRT and unanswered calculations (M3, M10); expired items stay unanswered (M11). | `dismissal-reasons.md`; `AttentionMetrics.php:22-117` |
| F11 | The qualification scorer gives a rule-opened line opener `rule` and **returns before the model call**. The opener gates (A1–A9) are computed on rule-declined lines, and the scope and held-out fixture tests require lines that "reach the model". | `scripts/qualification/attention.py:330-338, 360-367, 593` |
| F12 | Dev DB (read-only, 2026-10-10): 64 messages; 19 `rule` items (10 answered, 7 dismissed `message_removed`, 1 `not_a_question`, 1 expired); 0 `member_discussion` so far; 1 attention judgement in total (`attention_v1`, `asking`); **0 of 19 rule items with any attention record**. Development traffic, not evidence of production rates. | probe |

### What the labelled real data says about the noise (pure-function probe, no model, no text)

`real-attention-fresh-v1.jsonl` has 37 lines under D′ labels. The operator curated it around the
outside-institution problem, so it is **not a random sample**.

| | asking | discussion | informing | other intents | total |
|---|---|---|---|---|---|
| Rule-opened | 2 (1 clear, 1 ambiguous) | 23 | 2 | 0 | **27** |
| Rule-declined | 1 | 0 | 7 | 2 | 10 |

On the 25 rule-opened non-`asking` lines:
- **17 carry `؟`/`?`.** They are grammatically real questions; what makes them not the team's is *whose* question
  it is (D0, D3).
- **15 open on a single signal:** `؟` 7, `هل` 3, `من` 3, `ابغي` 1, `كيف` 1.
- **Removing `من`** (Finding 14's trap; it is also the preposition "from") would decline 3 of the 25.
- **Removing `هل`** would decline 3 more, but `هل` is the yes/no interrogative itself.

In the two original real tuning sets, all 7 rule-opened lines are `asking` (6 clear, 1 ambiguous).

*Consequence:*
- **The motivating noise is semantic, not lexical.** A rule change can trim a few lexical opens. It cannot decide
  whose question it is.
- **Today's labelled rule-opened positives are 7 clear lines** across all real sets. That is far too few to gate
  a filter's misses (§9).

---

## 2 — Code paths and files involved

| Concern | File | Role in the hybrid |
|---|---|---|
| Rule set v1 | `apps/ai-api/app/domain/moderation/attention.py` (`evaluate`, literals, `RULE_VERSION`) | Unchanged. It remains the candidate generator. |
| Burst + opening | `apps/ai-api/app/application/moderation/attention.py` (`assemble_burst`, `open_item`, `_model_proposal`, `request_rejudgement`) | Unchanged. |
| Eligibility | `apps/ai-api/app/domain/moderation/attention_judgement.py` (`attention_exclusion` AE1–AE2) | **AE2 lifted** (phase C). |
| Judge | `apps/ai-api/app/application/moderation/attention_judgement.py` (`judge_one`, W2) | Unchanged code. W2 stays harmless (§4.3). |
| Actor / queue | `apps/ai-api/app/workers/tasks/moderation/judge_attention.py` (`moderation_attention`, priority 0) | Unchanged. It carries more calls (§10, R7). |
| Dispatch | `apps/ai-api/app/application/moderation/messages.py` (`derive_message`) | Unchanged. |
| Records | `apps/ai-api/app/infrastructure/models_moderation.py` (`message_attention_judgements`, `message_attention_attempts`, `attention_items`) | No DDL. `rule_opens` stays in the CHECK as historical vocabulary. |
| Figures (Python) | `apps/ai-api/app/application/moderation/metrics.py` | New C11 (agreement); dated notes on C10a/C10b. |
| Qualification | `apps/ai-api/app/scripts/qualification/attention.py`, `qualify_moderation.py` | New filter-role scoring for rule-opened lines (phase B). |
| Queue | `apps/ai-control/app/Filament/Pages/LiveAttentionQueue.php` | One display column (phase D). The actions are unchanged. |
| Figures (PHP) | `apps/ai-control/app/Filament/Pages/Concerns/{AttentionJudgementMetrics,ClassificationMetrics,AttentionMetrics}.php` | The C11 mirror. Everything else is unchanged. |
| Contracts | 011 `contracts/attention-judgement.md` (§2 AE2, §10 N6, §11), `attention-metrics.md` (C10, new C11), `qualification.md`; 008 `control-panel-classification.md` Q1–Q2; 006 `control-panel-attention.md` | Dated amendments, in the milestone that implements them. |

---

## 3 — Is the hybrid technically compatible?

| Layer | Compatible today? | What it needs |
|---|---|---|
| Rule opening, timing, attribution | Yes, untouched | Nothing. The hybrid writes nothing to `attention_items`. |
| Judging rule-opened messages | **No** (AE2) | Lift AE2: a contract amendment plus a one-line change to a pure function, with tests. No DDL. |
| Storing the reading | Yes | Nothing. One row per message already carries intent, provenance and time. |
| Linking a reading to an item | Yes, through burst membership | A contracted item-level SQL reading (§5.2), as C6 does for classifications. **Not** `attention_judgement_id` (F5). |
| Display | Yes, with one amendment | One display-only column under Q1–Q2's rules, and a dated display setting. |
| Ground truth | Yes | `status`, `close_reason`, `first_response_kind` and `closed_at` already hold the human label. |
| Agreement figure | Yes | New C11, the deferred "C1 for attention" (F9). |
| A wording that means D′ | **No** | None exists (cycle 2 stopped). `attention_v1` means Policy D. |
| Evidence on the input population | **No** | No run has ever judged a rule-opened line (F11). |
| Auto-dismissal | Not now, and not without schema | Out of scope (§9, §12 phase E). |

**Verdict: architecturally compatible; blocked on an instruction and on evidence, not on design.**

---

## 4 — Answers to the ten questions

### 4.1 Can rule-opened items already receive a judgement?

Mostly no. AE2 excludes any message whose own words open v1 (F1), and the opener's own words are what open a
rule item. The judge's own docstring says so: such a message's judgement "could never be read".

A rule item's burst can still carry judgements on *other* members in three cases:
- a member whose words do not open by themselves, such as a greeting before the question;
- every member, when the burst opens only on `replies_to_moderator` or `mentions_moderator`, which AE2 does not
  see;
- a member edited inside the settle window.

These are partial and incidental. Separately, nothing is judged at all while the instruction setting is blank
(F3).

### 4.2 Is the judgement stored safely for display on a rule-opened item?

Yes:
- **It is per message,** immutable, one current row, with `created_at`, model and instruction (F4). Nothing
  needs to be written to the item.
- **The item reaches its members** through `telegram_messages.attention_item_id`, which is write-once (F7).
- **A burst is not a message.** An item can have several members, each with its own reading or none. The item's
  reading must therefore be *derived* by one contracted query (§5.2), never stored on the item.
- **Do not use `attention_items.attention_judgement_id`.** It is the opener's provenance, and the CHECK forbids it
  on rule items (F5).

### 4.3 What assumes "rule-opened → no judgement needed", and what changes?

| Assumption | Where | Change for the hybrid |
|---|---|---|
| AE2 exclusion | `attention_exclusion`; contract §2 AE2; D-TG-186 | Remove the `evaluate` branch, with a dated amendment. `rule_opens` stays a valid historical CHECK value (no migration), and old exclusion rows are kept. |
| "Judgement can never be read" | D-TG-186; contract §11 "Rule-opened peer questions are outside the model's reach" | Superseded by a dated note: it is now read as advice and measurement, never by `open_item`. |
| Qualification never calls on rule-opened lines | `scripts/qualification/attention.py:336-338, 365-367` | Keep it for the opener gates (A1–A9 are about opening). Add a separate filter-role score over rule-opened lines (§9). |
| C10a's `rule_opens` exclusions; C10b's M29 ("a rule-opened member is AE2-skipped") | `attention-metrics.md` | Dated notes. From the change date, `rule_opens` stops growing and C10b's intents include rule-opened messages. Eras are not compared across the date. |
| C1/C2 attention rows deferred | D-TG-197 | Becomes C11 (§7). |

**What does *not* change when AE2 is lifted** (verified in code):
- `open_item` reads judgements only after the rules decline (F6), so no item opens, changes source or changes
  time.
- W2 may call `request_rejudgement` for a rule-opening `asking` message while the opener's switch is set. That
  call returns `False` whenever the message's burst is covered (`attention_item_id` set) or not yet evaluated
  (`attention.py:489-495`). Since such a burst always opens by rule, it is a no-op, and the switch is blank
  anyway.
- **One gap closes as a side effect:** the "edit removes an AE2-skipped member's only rule signal" limitation
  (§11).

### 4.4 Is `intent`/`needs_response` enough, or is a separate `attention_decision` needed?

**Intent is enough. No new field, column or model output.**
- **`needs_response` is the single derivation (S2, N2).** A stored `attention_decision` mapping `discussion →
  member_discussion` would be a second derivation of the same intent, which N2 forbids, and the mapping is not
  one-to-one (§4.5).
- **The only information `attention_decision` would add is "uncertain",** and the model cannot supply it: the
  judgement deliberately has no confidence (008 measured fact 2: self-reported confidence barely moves).
  "Uncertain" is better *derived at item level* from stored facts:
  - a burst member unjudged, failed, or excluded as `media` or `no_text`, where the request may be in an image;
  - a multi-message burst (L-B1, §10 R4);
  - the intent `other`.
- **The decision itself is the moderator's, and it is already stored** (`close_reason`).
- **When auto-dismissal is ever built,** *that* needs a stored record of what the system did and on which
  judgements (§6). That is a different thing from a decision field on the judgement.

### 4.5 Intents → moderator-facing readings

The mapping is many-to-one in both directions, so the panel should show the intent in plain words and let the
moderator pick the reason. Each row is a *reading*, not a recommendation.

| Intent (item-level, §5.2) | Panel reading | Nearest reason, if any | Why not automatic |
|---|---|---|---|
| `asking` (any member) | "Model: needs the team" | none, keep | — |
| `discussion` | "Model: members' discussion" | Member discussion | Matches K2's wording ("a real question or discussion between members; no moderator was needed"). Still, D7 says unclear-whose leans `asking`, and the model sees no reply context (D8). |
| `informing` | "Model: information / an answer" | either | D4, a member answering a member, sits inside a discussion. A bare outside-institution statement is "not a real question". The moderator decides. |
| `social` | "Model: social" | Not a real question | Usually. A rule-opened social line opened on `؟` ("how are you all?"). |
| `offering` | "Model: an offer or promotion" | **none: check the classification** | May be an advert. The right act is TG-M4's "Open incident", then a dismissal. The classification (Model's view) is the authority on adverts. |
| `other` | "Model: unclear" | none | No reading to act on. |
| incomplete / not judged | "Model: incomplete" / "not judged" | none | Fails open to today's behaviour. |

**Phase D shows the reading, not a reason.**
- Phase C's agreement figure (§7) cross-tabulates intent against the reason moderators actually chose. That
  measures the mapping instead of assuming it.
- If a mapping is ever shown as a hint, it is one pure Python function, written into the contract and exposed as
  a column of the reading's SQL. PHP never branches on it (the panel rule: no state computed in PHP).

### 4.6 Interactions with dismissals, per-reason figures, KPIs and response time

- **Member discussion / Not a real question:** the actions, confirmation (K2), guarded write (K3) and vocabulary
  are all unchanged. The moderator still chooses.
- **Existing dismissal figures (K5, C1, C7, C9, M24):** unchanged SQL and unchanged values on the same rows. The
  hybrid writes no item.
- **C7/C9 per-reason columns:** unchanged and still diagnostic (K10). C7's breakdown becomes *more* useful: it is
  the blind baseline (phase A) against which the seen era is compared.
- **Moderator KPIs (FRT, unanswered, oldest waiting):**
  - Unchanged definitions. Advice can only change *behaviour*, which is the point.
  - Faster correct dismissals lower `opened` and the unanswered share, correctly.
  - A *wrong* dismissal removes a real question from `opened` and `unanswered` alike (M10): an invisible miss
    (R1).
  - A moderator who trusts "discussion" and neither answers nor dismisses lets the item **expire**. It then
    counts as unanswered forever (M11) and leaves no label (R9).
- **Response time:** `opened_at`, the anchor and `responsible_moderator_id` are set by `open_item` before or
  regardless of any reading. FRT is `first_response_at − opened_at` on answered items only. Advice changes
  neither term.
- **C9 / M24 (model-opened):** untouched. The hybrid opens nothing.

### 4.7 Timing semantics: AI must not rewrite history

It cannot, structurally:
- **The reading lives in its own table.** `attention_items` takes no write from the judge. `ck_attention_ai_link`
  rejects a judgement link on a rule item, and N6 forbids the model closing, dismissing or re-dating anything.
- **The judgement is dispatched at ingest.** The item opens after the settle window
  (`MODERATION_BURST_GAP_S`, 90 s), so a reading usually exists by the time the item does. C10b's `on_time`
  (M28) measures how often.
- **A reading that lands after the moderator acted** is recorded but was not seen. §8 uses `j.created_at`
  against `ai.closed_at` / `first_response_at` to tell the two apart.
- **The queue polls every 15 s,** so "seen" is approximate to that tick. This is acceptable for a figure; it is
  not a stored fact (open question 6).

### 4.8 Can moderator confirmation become ground truth?

Yes, with known strengths, and the timing (§8) must separate *blind* from *seen* labels.

| Item outcome | Label | Strength |
|---|---|---|
| dismissed `member_discussion` / `not_a_question` | did not need the team | strong: a human chose a reason |
| answered, `first_response_kind = direct_reply` | needed the team | good |
| answered, `group_message` (rule (b): the next moderator message in the thread) | probably needed the team | **weak**: any moderator message closes the oldest open item |
| dismissed `message_removed` / other | no label | says nothing about need |
| expired, still open | no label | nobody acted |

Your example (rule-opened, model `discussion`, dismissed as Member discussion) is one *agreement* cell of C11.
The cell that matters most is the opposite: **model not-asking, item answered by direct reply**. That is the
filter's dangerous disagreement.

### 4.9 Evidence before any auto-dismissal

See §9. In short:
- a qualified D′ wording judged on **rule-opened** lines with zero clear-`asking` misses;
- a blind live period, then a seen period, each with zero confirmed dangerous disagreements over at least 100
  strong positives (rule of three: at most about 3 % at 95 %);
- restricted to single-message, complete, specific-intent items;
- and a non-terminal, auditable state, never `dismissed` directly.

### 4.10 Compared with rule changes first, a third round now, or both later

See §13. In short:
- **Rule changes:** cannot decide "whose question" (17 of 25 noisy lines are real questions). They are cheap,
  exact and worth doing later for lexical noise, on C7 evidence.
- **A third *opener* round:** the opener only *adds* items from rule-declined messages. It cannot remove one
  rule-opened item, and 7 of the operator's 8 examples are rule-opened. It does nothing for this problem.
- **The hybrid:** the only one aimed at the noisy population. A third round **re-aimed at the filter role** is
  what it eventually needs.

---

## 5 — Recommended architecture

### 5.1 The flow, as the code would actually run it

```
Telegram message ──► derive_message (insert-only)
                       │
                       ├─► judge_attention  (at ingest, no delay; queue moderation_attention, priority 0)
                       │     AE1 eligibility ── [AE2 lifted in phase C] ── model (one message, redacted)
                       │     └─► message_attention_judgements  (per message, immutable: intent, needs_response,
                       │                                        model, prompt_version, created_at)
                       │
                       └─► evaluate_attention  (after MODERATION_BURST_GAP_S)
                             assemble_burst ─► open_item  (chat_lock)
                               ├─ rule set v1 opens ─► attention_items source='rule', rule_version=1,
                               │                        opened_at/anchor/responsible from the burst  [UNCHANGED]
                               └─ rules decline ─► AI opener (switched off: MODERATION_AI_ATTENTION_FROM blank)

Live Attention Queue, one open rule item
   └─ "Model's reading" = ONE contracted SQL over the item's burst members' current judgements (§5.2)
        ├─ any member asking ..................... "Model: needs the team"
        ├─ every member read, none asking ........ "Model: <intent(s)>"  (+ "several messages" when multi)
        ├─ a member unjudged / failed / media .... "Model: incomplete"
        └─ no member judged ...................... "Model: not judged"
   moderator acts exactly as today:
        answer in Telegram │ Not a real question │ Member discussion │ Message removed │ Open incident
   └─► status / close_reason / first_response_kind / closed_at  = the human label
          └─► C11 agreement: reading × outcome, per (model, prompt_version), blind era vs seen era
```

**Where this differs from the flow proposed in the request:**
1. **The AI does not "also evaluate" a rule-opened message today.** Lifting AE2 is the prerequisite.
2. **The reading is per message.** The item's reading is an aggregation, with "any member asking → needs the
   team", mirroring the opener's O2′.
3. **"Uncertain" is derived,** not answered by the model.
4. **No branch says "suggest X dismissal".** `informing` and `offering` do not map to one reason (§4.5).

### 5.2 The item-level reading (to be contracted; sketch)

One query, in the style of C6 (`classificationLabelsForItems`), run for the current page's item ids. The same SQL
appears in Python (`metrics.py`) and PHP, and is quoted once in the contract:

```sql
SELECT ai.id AS item_id,
       count(*)                                                        AS members,
       count(*) FILTER (WHERE j.id IS NOT NULL)                        AS judged,
       bool_or(j.needs_response)                                       AS any_asking,
       count(*) FILTER (WHERE j.id IS NULL
                          AND (x.id IS NULL OR x.reason IN ('media','no_text')))  AS unread,
       array_agg(DISTINCT j.intent) FILTER (WHERE j.id IS NOT NULL)    AS intents,
       min(j.created_at)                                               AS first_read_at
FROM attention_items ai
JOIN telegram_messages m
  ON m.telegram_chat_id = ai.telegram_chat_id
 AND (m.attention_item_id = ai.id OR m.message_id = ai.telegram_message_id)
LEFT JOIN message_attention_judgements j
  ON j.telegram_chat_id = m.telegram_chat_id AND j.telegram_message_id = m.message_id AND j.is_current
LEFT JOIN message_attention_attempts x
  ON x.telegram_chat_id = m.telegram_chat_id AND x.telegram_message_id = m.message_id AND x.outcome = 'excluded'
WHERE ai.id = ANY(:item_ids)
GROUP BY ai.id;
```

The reading follows mechanically. `any_asking` gives "needs the team". `judged = 0` gives "not judged".
`unread > 0` gives "incomplete". Otherwise the reading is the intents, and `members > 1` adds "several messages".

Other exclusions (acknowledgement, moderator, service) are complete: those members carry no request. Mixed prompt
versions inside one burst are reported as incomplete, never pooled (K3).

### 5.3 Display rules (amending 008 Q1–Q2 and 006's queue contract, in the implementing milestone)

- **D-1.** A display-only column beside "Model's view", named so the two cannot be confused. For example,
  "Needs the team? (model)" next to the classification's category.
- **D-2.** It never filters, sorts, hides, colours as urgent, or pre-selects an action. The dismiss actions and
  their shared confirmation stay identical (K1–K4), and there is no "accept suggestion" button.
- **D-3.** It is shown only while a dated setting is set (e.g. `MODERATION_ATTENTION_ADVICE_FROM`), which makes
  the blind/seen boundary exact. This is a setting, not a schema change; open question 6 covers recording its
  changes.
- **D-4.** Fail-open: an attention model that is down or slow means "not judged" or "incomplete", which is
  today's queue.
- **D-5.** The words are `ModelView`-style: plain, with no percentage, no probability and no "AI recommends".

---

## 6 — Is a schema change needed?

**No, for everything recommended in phases A–D.**

| Need | Without DDL because |
|---|---|
| Judge rule-opened messages | Same table and row shape. `rule_opens` stays allowed by `ck_attention_attempt_reason` for history, and is simply no longer written. |
| Item's reading | Derived by SQL from the members (§5.2). |
| Human label | `status`, `close_reason`, `first_response_kind`, `closed_at` (existing). |
| Seen vs blind | `j.created_at` versus `closed_at`/`first_response_at`, and the dated display setting. |
| Per model and instruction | `model_profile_id`, `prompt_version` on each judgement. |

**What *would* need schema later (phase E, if ever):**
- **System-taken dismissals need a distinct actor and state.** Today `closed_by_user_id` NULL also means expiry,
  and `dismissed` is terminal: N4 forbids reopening.
- **Auto-dismissal also needs a provenance link** to the judgement(s) that drove it. `attention_judgement_id` is
  the opener's link and is forbidden on rule items.
- **A "seen" flag stored per item,** only if the setting-based boundary proves too coarse.

---

## 7 — UI and metrics implications

- **Queue:** one column (§5.3). No new action. The figures table on the queue page is unchanged.
- **New C11, "the model's reading of rule-opened items, and what the humans did":** one row per `(model,
  prompt_version, reading, outcome, era)`.
  - **Rows:**
    - reading: `asking`, `not_asking:<intent>`, `incomplete`;
    - outcome: §4.8's labels;
    - era: `blind` when no display setting was in force or the reading postdates the human act; `seen` otherwise.
  - **Counts only:** no ratio is pooled across models (K3), and there is no composite score.
  - **Headline cells, always shown:**
    - **dangerous disagreement:** reading not-asking, outcome answered by direct reply (and, separately, by
      group message);
    - **agreement:** reading not-asking, outcome a reasoned dismissal;
    - **overrides:** reading `asking`, outcome a reasoned dismissal. This shows the model's over-keep, the safe
      direction.
- **C10a / C10b:** dated notes only (§4.3).
- **C1 (classification):** unchanged. It remains a useful contrast, since the classifier already reads every
  rule-opened message (no AE2) and its needs-response is known to follow topic (TG-M5.2).
- **Classification Accuracy page:** C11 sits beside C7, whose per-reason columns are the blind human baseline.
- **Not added:** any change to FRT, unanswered, oldest-waiting, M24 or the K5 counts.

---

## 8 — Moderator feedback as evaluation data

1. **The blind era is now.** Today's reasoned dismissals on rule-opened items are labels that no model reading
   influenced. With rules-only running and Story 1 shipped, they accumulate at no cost.
2. **A blind *shadow* era follows (phase C).** Readings are recorded on rule-opened messages but **not shown**.
   C11's blind rows are the honest estimate of the filter's agreement and its dangerous disagreements.
3. **The seen era (phase D)** measures behaviour, not accuracy. If agreement jumps while direct-reply answers on
   not-asking items fall, that is anchoring, not improvement.
4. **Hand review of every dangerous disagreement.** A filter's misses are few and individually important. The
   pilot notes record each one as a model miss, a weak label (group-message close), or a labelling error.
5. **Ground truth for future qualification:**
   - **Blind-era rule-opened items with a strong label** can be sampled into a D′-labelled *filter* set, outside
     the repository and relabelled by the operator, never taken raw.
   - **Seen-era labels are never used as qualification truth.**

---

## 9 — Evidence before considering auto-dismissal (a future milestone, not assumed)

| Stage | Population | Hard gate (proposal; the thresholds are operator decisions) |
|---|---|---|
| **F-1 offline** | Labelled real **rule-opened** lines under D′. The fixed sets stay as they are; a new filter set is written. | **0** clear-`asking` lines read not-asking, per set, over at least 30 clear rule-opened positives. Report the not-asking yield on clear negatives. Today's labelled rule-opened positives number **7**, so this set must be written first. |
| **F-2 blind live** | Rule-opened items, blind era, per `(model, prompt_version)` | At least 100 strong positives (direct reply or kept-and-answered), with **0** confirmed dangerous disagreements after hand review. By the rule of three, that bounds the miss rate below about 3 % at 95 %; 30 positives would bound it only at about 10 %. M24's 10 % is an *opener* gate and is far too loose for a filter. |
| **F-3 seen live** | Same, seen era | No rise in dangerous disagreements relative to F-2, and a reported override rate. |
| **Scope for any automation** | — | Single-message items only, a complete reading, and only the intents that passed F-1 to F-3 individually (likely `discussion` and `social` first). Never `offering`, `other` or `informing` until measured separately. |
| **Form of automation** | — | A **non-terminal, reversible, separately counted** state (e.g. "parked by the model"), visible in its own list, with a random audit sample. Never `status='dismissed'` directly. It is counted apart from human dismissals in every figure, and excluded from moderator KPIs or shown separately in them. It needs the §6 schema and an N6 amendment. |

The opener's cycle-2 results bear on this only indirectly, since every validation line is rule-declined:
- **Its A3 *scope* failures do not count against a filter.** V2-A opened #5 and #7 (outside-institution lines read
  `asking`). For a filter, that is the safe "keep" error.
- **Its base-validation misses do count.** V2-A missed #4 and #27, real `asking` read otherwise. That is the
  filter's dangerous error, and it shows the risk is real.
- **D′'s own D7** ("unclear whose → `asking`") already leans the safe way for a filter.

---

## 10 — Risks and failure modes

| # | Risk | Effect | Control |
|---|---|---|---|
| R1 | **Automation bias** turns a wrong not-asking reading into a dismissal | A real question vanishes from `opened` and `unanswered` (M10): an invisible miss | Blind era first. No pre-selected action. The dangerous-disagreement cell always shown. F-2 before any display. |
| R2 | **Wrong policy in the wording**: `attention_v1` is Policy D | Advice says "keep" on the motivating cases and contradicts D′ guidance | Never run the hybrid on `attention_v1`. It needs a D′-frozen wording (phase C). |
| R3 | **Unmeasured population** (F11) | Unknown recall on rule-opened text, which differs from rule-declined text (question marks, interrogatives) | Phase B, a filter-feasibility measurement, before any production change. |
| R4 | **L-B1 inverted**: distributed intent | For an opener, L-B1 was a miss of the status quo. For a filter, it is a wrong "not asking" on a multi-message burst | "Several messages" flag. No automation on multi-message items. M30-style exact split in C11. |
| R5 | **Weak labels**: group-message closes, expiry, `message_removed` | Agreement inflated or deflated | §4.8 strengths. Separate cells for direct-reply and group-message. Hand review. |
| R6 | **Label contamination**: seen-era labels used as truth | Self-fulfilling agreement | Seen labels are never qualification truth (§8.5). |
| R7 | **Load**: every rule-opening message becomes a call on the one-thread `ai-classifier`, Attention first | Classification (and so incidents) lag under backlog. The reading is late for display. | Measure the `rule_opens` volume and C10b `on_time` in phase C. This is deployment policy (serving limits are not domain rules). |
| R8 | **Two model columns** | Confusion between the classification's view and the attention reading | Distinct names and words (D-1, D-5). |
| R9 | **Ignored items expire** | Unanswered share rises, and there is no label | The reading never implies "no action needed". Training note in the runbook. |
| R10 | **Era drift** in C10a/C10b after lifting AE2 | Misread trends | Dated notes. Eras are not compared across the date. |
| R11 | **Setting history lives in `.env`** | The blind/seen boundary cannot be reconstructed if it is toggled carelessly | Record every change in research §2 and the runbook, as was done for TG-M5.1's switch. Open question 6. |
| R12 | **Low volume** | F-2's 100 strong positives may take long | State the period, not a date. The gate is on count. |

---

## 11 — What must remain unchanged

- **Rule set v1:** its literals, `RULE_VERSION = 1`, `evaluate`, R1's stoplist precedence, bursts and anchors.
- **`open_item` and the items it writes:** `opened_at`, `source`, `rule_version`, attribution, C10 lookback,
  E2–E5, and the `uq_attention_anchor` convergence.
- **The schema:**
  - `attention_items` and its CHECKs, including `ck_attention_ai_link`: a judgement is never linked to a rule
    item;
  - `message_attention_judgements` and `message_attention_attempts`;
  - the `close_reason` vocabulary.
- **Dismissal behaviour:** the dismiss actions, K1–K12, the shared confirmation, no bulk action, and no reopen or
  re-date (N4).
- **Every existing figure's SQL and values:** TG-M3 §2–§5, C1, C7, C9′, M24, K5 and M10.
- **The six intents and the single derivation:** `needs_response_for`, S2 and N2.
- **The model's limits:** N6 (the model closes, dismisses, expires and re-dates nothing) and N7 (no burst input).
- **`attention_v1`:** its file, pin, entry, and its `QUALIFIED` evidence under Policy D, kept as history.
- **The stopped second cycle:** its evidence, sets, hashes and `research.md` §2 entries.
- **The AI opener:** `MODERATION_AI_ATTENTION_FROM` stays blank, and the opener itself is untouched.
- **Classification, incidents, the routes and TG-M4.**

---

## 12 — Phased plan and milestone boundaries

| Phase | What | Code? | Exit / decision |
|---|---|---|---|
| **A — Blind human baseline** (now, operator) | Rules-only. Dismiss with reasons. Read C7's per-reason columns monthly. Label a sample of real **rule-opened** messages under D′ (outside the repository), enough for F-1's 30 or more clear positives. | None | Operator decides whether the rule-opened noise is large enough to justify B. |
| **B — Filter feasibility** (small milestone) | A read-only scoring mode that also sends **rule-opened** lines to the model and reports misses and yield separately from A1–A9. Run it on `attention_v1` (as a baseline) and on candidate files (exit 3, no freeze) over the phase-A set. | Qualification tooling plus tests only. No live path, no schema, no settings. | Does any wording read rule-opened lines with **0** clear-`asking` misses and a useful yield? If not, stop: the hybrid is not viable with this model class. |
| **C — The filter-role instruction and blind shadow** (milestone, e.g. TG-M5.4) | Freeze a D′ wording through an approved cycle aimed at the filter role, with misses as the hard gate. This is where the next frozen attention version is created, through its own approval. Lift AE2 with dated amendments. Add C11 and the §5.2 reading (Python and PHP), with C10 notes. Turn on the instruction setting only; the reading stays **not displayed**. | Yes | F-2 met, per `(model, prompt_version)`. |
| **D — Display** (same or next milestone) | The display-only column, D-1 to D-5, and the dated display setting. Runbook and training note. | Panel only | F-3 holds over the agreed period. |
| **E — Automation** (separate milestone; **not assumed**) | A non-terminal "parked by the model" state, with provenance, audit sample, separate counts and an N6 amendment. | Schema plus contracts | Only on F-1 to F-3, the scope restrictions, and an explicit operator decision. |
| **R — Rule set v2** (independent; any time after A) | Data-driven lexical fixes from C7 per-reason data and per-literal probes (e.g. `من`). `RULE_VERSION = 2` keeps C7 rows separate. Exact and offline over every labelled set. | Yes | Its own approval. It does not address "whose question". |

Each lettered phase is separately approvable. The boundaries keep:
- the live path untouched until C;
- the queue untouched until D;
- the schema untouched until E.

---

## 13 — Compared with the alternatives

| Option | Targets the noisy population? | Cost | Risk | Verdict |
|---|---|---|---|---|
| **Change TG-M3 rules first** | Partly: lexical opens only (about 3 of 25 lines on `من`) | Low, and exactly measurable offline | Recall loss on real `من`/`هل` questions | **Later (phase R), on C7 evidence.** Not the fix for "whose question". |
| **Third *opener* qualification round now** | **No.** It only adds items from rule-declined messages. | High (one cycle) | The same D7 tension that stopped cycle 2 | **Not now.** It does not touch rule-opened noise. |
| **Hybrid (rules generate, model reads, human decides)** | **Yes** | Medium: phases B–D | R1 to R4 | **Proceed with changes, in phases A → B → C → D.** |
| **Both later** | — | — | — | Yes. R may run in parallel with C. A future opener round would reuse C's D′ wording only if it also passes the opener gates. |

---

## 14 — Open questions for the operator

1. **Phase A sample.** Who labels the real rule-opened sample under D′? How many lines can you supply (F-1 needs
   at least 30 clear `asking` among them)? Should it come from the period before or after Story 1 shipped?
2. **F-1/F-2 thresholds.** Do you accept 0 misses over at least 30 offline and at least 100 live strong
   positives? Do you want stricter or looser bounds?
3. **What counts as a strong positive?** Direct reply only, or also a group-message close confirmed by hand?
4. **Phase B scope.** Run the stopped V2 candidate files as filter candidates (they were never measured on
   rule-opened text), or only `attention_v1` as a baseline plus new wordings?
5. **Phase C instruction.** Is the filter-role cycle a new attention version under D′ (the next frozen version,
   with its own approval), and may its policy text keep D7 as is, since D7 leans the filter's safe way?
6. **Display era record.** Is a dated setting plus research and runbook entries enough to mark blind against
   seen? Or do you want the "seen" fact stored per item, which would be a schema change?
7. **Column wording and placement** beside "Model's view". Should the reading also appear on the incident or
   message pages, or only the queue?
8. **Multi-message items.** Show the reading with a "several messages" flag, or show nothing for them until L-B1
   is measured?
9. **`offering` on a rule item.** Show "check the classification", or nothing?
10. **Phase R.** Open a rule-set-v2 investigation now, in parallel, starting with `من`'s per-literal evidence?
