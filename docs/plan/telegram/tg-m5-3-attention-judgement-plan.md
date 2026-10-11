# TG-M5.3 — A Separate Attention Judgement (Option B)

**Status:** plan, **approved by the operator on 2026-10-06 with every recommended decision** (§16, items 1–12).
**Amended and approved on 2026-10-07** (§16, items 13–19, as written). Nothing here is implemented.
`/speckit-specify` was started on 2026-10-07 at the operator's request; implementation follows only the normal
Spec-Kit sequence.

**Amendments of 2026-10-07**, from the operator's review of member discussion and multi-message bursts:
- §1, §2: scope, non-goals and the attention judgement's question.
- §3a: multi-message bursts, verified against TG-M3's code and tests.
- §5, §5a: the `discussion` intent, a tightened `asking`, and labelling Policy D.
- §8, §9: fixture keys, peer lines, reported lines and burst fixtures.
- §12, §13, §13a: the `member_discussion` dismissal reason, per-reason breakdowns and wording corrections.
- §15, §16, §17, §18 and Verification follow from these.

Each amended passage is marked *(2026-10-07)* in place.

**Addendum of 2026-10-08, approved 2026-10-09 with every recommended option:** `tg-m5-3-attention-v2-addendum.md`.
It covers Policy D′ (outside institutions are not the team's; the operator chose option (a)), `attention_v2` and a
second qualification cycle. `attention_v1` stays frozen as history. §5a, §8.3, §8.4 and §9 carry dated notes
pointing to it.

**Supersedes nothing.** `tg-m5-classify-v3-plan.md` and `specs/010-tg-m5-2-classify-v3/` stay as the historical
record of why this milestone exists. TG-M5.2 closed as *stopped under FR-216* on 2026-10-06.

## Context

TG-M5.1 lets a live prediction open a question item that rule set v1 declined. The signal is the
`needs_response` value of the same `classify_vN` call that judges adverts and abuse. Two milestones of evidence
show that one call cannot carry both judgements:

| Evidence                | What it shows                                                                                                                                                                                     |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Finding 10 (010)        | Under v1/v2, needs-response was a pure function of the *category* on all 48 attention fixtures. Topic decided, not function. e2b + v2 opens 13 of 27 clear negatives.                             |
| Finding 11 (010)        | On e2b, every wording that separated asking from informing moved the advert boundary (policy #21 → incident, real moderation #1 lost). Three rounds, no wording passed both.                      |
| Plan §16 (010)          | **P2's attention wording worked on e2b**: 0/27 clear negatives opened, 0/13 positives missed. It failed only on the advert side, because it shared the prompt.                                    |
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
  an answer, action, clarification or decision from the team?", with its own output schema and allowlist.
  Whether the text is grammatically a question does not decide it (§5, §5a).
- Immutable storage for its predictions, exclusions and failures.
- TG-M5.1's opener reads the attention judgement instead of the classification's `needs_response`.
- A model role for the task, and inactive candidate profiles for e2b and e4b.
- The qualification command, generalised into a task-agnostic core plus task suites. The attention suite is
  new; the moderation suite keeps 010's advert gates.
- A wording-selection protocol with a validation set, then a held-out set (written after the freeze) and the
  operator's fresh sample.
- The smallest metric and panel changes needed so the pilot gate (C9/M24) reads the new opener.
- *(2026-10-07)* **A third dismissal reason, `member_discussion`** ("Member discussion"), on the Live
  Attention Queue for items of every source. It comes with per-reason breakdowns beside the existing dismissal
  counts, and a correction of the wording that calls every dismissal "not a real question" (§13a).
  - It is the milestone's first story and can be deployed on its own, before any model work, so rule-opened
    peer questions start being counted at once.
- *(2026-10-07)* **Labelling Policy D** (asking vs discussion, §5a), decided before any fixture or candidate
  wording is written.

**Non-goals**
- Any change to `classify_v2`, routing, thresholds, incidents or TG-M4.
- Any change to TG-M3's rule set, bursts, settle window, attribution, matching or ageing. *(2026-10-07)* The
  only TG-M3 surface touched is the list of dismissal reasons and its figures (§13a).
- *(2026-10-07)* **Rule-side handling of peer questions.** Most peer questions carry a v1 signal (`؟`, `مين`,
  `كيف`), so the rules open them before any model is consulted (§3a).
  - The remedy would be a rule_version 2 condition, a TG-M3 change and its own milestone.
  - It is decided from the `member_discussion` count on rule-opened items, not here.
- *(2026-10-07)* **Reply context as model input**, i.e. which message a message replies to. The request stays
  pipeline P1–P5: the redacted first-posted text only. This is stated as a limitation (§5a D8).
- The deterministic no-link rule, which stays its own milestone.
- Burst-level (multi-message) model input. *(2026-10-07)* The narrower gap that remains is documented and
  measured (§3a).
- A prompt registry or `prompt_versions` table. 008 data-model §8 assigns that design to the assessment
  milestones; see §6.
- Fine-tuning, model chaining, or provisioning the production host.
- Catch-up (`path = 'catch_up'`) attention judgements. Deferred: see open decision 12.
- Reprocessing (`is_current` flips): TG-M8.

## 2. Responsibility boundaries

| Unit                                            | Decides                                                                                                    | Reads                                           | May do                                                                                    |
| ----------------------------------------------- | ---------------------------------------------------------------------------------------------------------- | ----------------------------------------------- | ----------------------------------------------------------------------------------------- |
| **Rule set v1** (TG-M3)                         | whether a burst carries an explicit question signal                                                        | burst texts, mention/reply facts                | open `source='rule'`. **First word, unchanged**                                           |
| **Moderation judgement** (`classify_v2`, TG-M5) | category, needs-moderation, severity, route                                                                | the first-posted, redacted text                 | open or list incidents. Its `needs_response` field is **measurement only again**          |
| **Attention judgement** (new)                   | whether the writer needs an answer, action, clarification or decision from the team (*amended 2026-10-07*) | the first-posted, redacted text                 | propose; `open_item` decides. Never closes, dismisses, expires, re-dates or re-attributes |
| **`open_item`** (TG-M3/TG-M5.1)                 | whether an item opens, its anchor, `opened_at`, owner                                                      | rules, then attention judgements, then the veto | the single insert                                                                         |

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

| Option                                                                  | Calls                                        | When the AI item can open                                                               | Verdict                                                                                  |
| ----------------------------------------------------------------------- | -------------------------------------------- | --------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| **Ingest, with the AE2 skip** (recommended)                             | 1 + (1 − share skipped) per eligible message | at the settle (Case A, ~1–3 s of model time)                                            | keeps TG-M5.1's usual path                                                               |
| Ingest, every eligible message                                          | 2 per message                                | at the settle                                                                           | wastes calls on certain rule-opens                                                       |
| After the settle, only when the burst's rules decline                   | fewest                                       | always late: settle + queue + up to 30 s tick (Case B); a burst's N calls queue at once | judgement logic leaks into the opener                                                    |
| Dependent: attention runs only after classification says not SPAM/ABUSE | fewer on adverts                             | waits for the other judgement on every message                                          | creates an ordering dependency between independent judgements; adverts are a small share |

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

## 3a. Multi-message bursts (added 2026-10-07)

**Verified from the code and tests on 2026-10-07. TG-M3 is not changed.**

**The probe.** Rule set v1's pure `evaluate` was run on `normalize()`d text and printed booleans only. The
messages are the operator's own illustrations, not real messages.

| Burst (one sender, one thread, gaps ≤ 90 s)                                                            | v1 opens? | Signal                                                               |
| ------------------------------------------------------------------------------------------------------ | --------- | -------------------------------------------------------------------- |
| «السلام عليكم» + «متى موعد الاختبار؟»                                                                  | yes       | the 2nd member (`متي`, `؟`); the greeting alone declines             |
| the same, without `؟`                                                                                  | yes       | `متي`                                                                |
| «السلام عليكم» + «كنت بحاول أدخل الاختبار» + «بس الرابط مش شغال»                                       | yes       | `مش شغال` is a v1 literal; the 3rd member opens the burst on its own |
| the same, ending «بس الرابط بايظ», «والرابط مش راضي يفتح», «بس الرابط لا يعمل» or «والرابط ما فتح معي» | no        | no member carries a v1 signal                                        |

**Handled today, by TG-M3.**
- **The burst.** A greeting is not an acknowledgement, so R1 does not end the evaluation. A later member's
  signal opens the burst, anchored and dated from the earliest member (B2).
- **Tests that already cover this shape:**
  - `tests/moderation/attention/test_burst.py::test_three_messages_inside_the_window_open_one_item_dated_from_the_first`
    (two lines with no signal, then a question);
  - `tests/moderation/attention/test_opening_idempotency.py::test_a_partial_burst_that_declines_then_the_full_burst_opens_dated_from_the_anchor`
    (an early run on the unsettled burst declines; the full burst opens, dated from the anchor).
- **The probe's first three bursts** are opened by the rules. TG-M5.3 changes nothing for them.

**Handled by TG-M5.3, with no burst-level input.** In the probe's fourth burst, each member's first-posted words
are judged on their own.
- **Which member opens it:** `open_item` opens on the earliest member whose judgement passes, and anchors the
  item at the burst's earliest member (§3, TG-M5.1 O2).
  - This behaviour is already tested:
    `tests/moderation/classification/test_ai_attention.py::test_opened_at_is_the_bursts_earliest_member_even_when_the_model_flagged_a_later_one`.
    TG-M5.3 re-points it at the attention judgement.
- **Why it opens:** «بس الرابط بايظ», read alone, is a problem the writer still has, so it is `asking` (§5).
- **So:** intent spread over several messages is covered whenever **any one member, read alone, is `asking`**.
- **Cost note:** the greeting is neither excluded (it is not an acknowledgement) nor AE2-skipped (its own words
  do not open), so it gets its own attention call, even in a burst a later member opens by rule. This is
  accepted: at ingest the burst is not yet settled, and skipping on a partial burst would be a second
  definition of the rules.

**L-B1, the remaining limitation.** A request is spread across members, and **no single member is `asking`
when read alone**.
- **Example:** «كنت بحاول أدخل الاختبار» + «امبارح وبرضه النهارده» + «😢».
  - **Fixture caution:** «من امبارح» would not do here. `من` is a v1 literal (TG-M3 §2.1 keeps it on purpose),
    so the rules would open the burst.
  - **Every L-B1 fixture must be checked with `evaluate`.**
- **No model opens such a burst.** The rules decline it, and every member's judgement is `informing`,
  `social` or `other`. Hand-opening covers it.
- **Not addressed in TG-M5.3:** there is no burst-level model input (§1).

**Measured, so a follow-up milestone is decided on evidence:**
1. **Before the pilot:** burst fixtures in the qualification attention suite, reported and never gated
   (§8.2, §8.4). They put a number on L-B1 and on the per-member coverage above.
2. **During the pilot:** C10 reports operator-added items (the misses a person noticed), split by their anchor's
   attention status and by single- vs multi-message burst (§13).
   - **Multi-message is exact.** The test is whether the anchor's sender has another message in the same chat
     and thread within `MODERATION_BURST_GAP_S` of the anchor. Under TG-M3 §1, every member of a burst of
     two or more has such a neighbour.
   - **Who classifies the misses:** the operator reviews the multi-message misses and records which were
     distributed intent in the pilot notes.
   - **Deferred:** an automatic count of misses where every burst member was judged non-asking needs bursts
     rebuilt in SQL, because hand-opening stamps only the chosen message.

## 4. Data model (one additive revision)

**Options compared**

| Option                                                                                          | Immutability                                                 | Idempotency                                       | Versions                                             | Catch-up                | Metrics / panel                                                                                                           | Future tasks                                                                                                                   | Verdict                                                      |
| ----------------------------------------------------------------------------------------------- | ------------------------------------------------------------ | ------------------------------------------------- | ---------------------------------------------------- | ----------------------- | ------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------ |
| **A. A typed sibling table, `message_attention_judgements`, plus `message_attention_attempts`** | the same insert-only discipline as `message_classifications` | `uq … WHERE is_current`, `ON CONFLICT DO NOTHING` | `model_profile_id`, `model_run_id`, `prompt_version` | `path` + check, as 0007 | typed columns; the existing queries are untouched                                                                         | per-message Telegram judgements reuse the pattern                                                                              | **recommended**                                              |
| B. A generic `ai_judgements(task, output jsonb, …)`                                             | possible                                                     | possible                                          | yes                                                  | yes                     | jsonb extraction everywhere, no check constraints; `message_classifications` stays separate anyway, so two patterns       | assessment outputs are artefacts with a review lifecycle, not per-message judgements, so it would only ever hold Telegram rows | reject now; revisit if a third per-message judgement appears |
| C. A `task` discriminator on `message_classifications`                                          | yes                                                          | `uq_classification_current` must widen            | yes                                                  | yes                     | every C1–C9 query and panel read must add a filter; category, severity and needs_moderation would have to become NULLable | no                                                                                                                             | reject: high regression risk on shipped figures              |
| D. Attention columns added to `message_classifications` later                                   | **breaks**: the row is updated after the second call         | —                                                 | —                                                    | —                       | —                                                                                                                         | —                                                                                                                              | reject                                                       |

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
    - checks on `intent` (the six values of §5, *amended 2026-10-07*) and on `path ∈ {live, catch_up}`
      (catch-up is deferred, but the shape is kept so it needs no later migration);
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

**Recommended** (open decision 2; *amended 2026-10-07*, decision 16):

```json
{"intent": "asking" | "discussion" | "informing" | "social" | "offering" | "other"}
```

| `intent`     | Means                                                                                                                                                                                                                                                                                                                                                              | `needs_response` |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------- |
| `asking`     | The message reasonably needs an **answer, action, clarification or decision from the team** (moderators, instructors, administration): a question or request about the service, a problem the writer still has, or a Policy S bare course statement. Being grammatically a question does not make a message `asking`, and lacking a question mark does not stop it | true             |
| `discussion` | A genuine question or prompt **between members**, about their own experience, work, answers or opinions, that needs no moderator                                                                                                                                                                                                                                   | false            |
| `informing`  | States information, including a member answering another member, or a resolved status                                                                                                                                                                                                                                                                              | false            |
| `social`     | Greetings, thanks, congratulations, wishes, small talk with no question                                                                                                                                                                                                                                                                                            | false            |
| `offering`   | Offers or promotes a service, product, group or contact                                                                                                                                                                                                                                                                                                            | false            |
| `other`      | None of the above                                                                                                                                                                                                                                                                                                                                                  | false            |

`needs_response = (intent == "asking")`, derived in `app/domain/moderation/…`. **It stays the single
derivation**: no second definition in SQL, PHP, the prompt or a CHECK constraint. There is no confidence
field. Policy D (§5a) is the labelling policy for the `asking`/`discussion` boundary.
- **Why an enum and not a boolean.** The model must name what the message *does*. This is the
  function-over-topic distinction Finding 10 asks for, and it yields a "why" for metrics and dismissals.
  `offering` gives adverts an explicit non-asking bucket, without the attention task judging whether a
  message breaks a rule.
- *(2026-10-07)* **Why `discussion`.** Without it, a peer question has nowhere to go but `asking`. Its form
  would decide over its function, which is Finding 10's error in a new place. `discussion` gives peer
  questions the same explicit non-asking bucket that `offering` gives adverts. It also matches the panel's
  new "Member discussion" dismissal (§13a), so a model error and its human correction use one word.
- **Why no confidence.** Finding 2: self-reported confidence was 0.90–1.00 on everything. The controls are
  the benchmark and the pilot's dismissal rate (M24). Dropping the field also removes a floor gate, TG-M5.1's
  G3, which only existed because FR-030 bound the classification's confidence.
- **The boolean schema is held in reserve.** It is used only if the enum underperforms in the selection round
  (§8.3).

## 5a. Policy D: asking vs discussion (added 2026-10-07)

> *(2026-10-09)* **Superseded for new labels and wordings by Policy D′** (`tg-m5-3-attention-v2-addendum.md` §3;
> spec FR-310). It adds D0, the team's responsibility: outside institutions are not the team's. It narrows D2 and
> D5 to the course's own service, widens D3 to outside-institution questions, and makes D7 cover "the course's or
> an outside body's?". The table below is Policy D as confirmed on 2026-10-07. It governs `attention_v1` and its
> evidence.

This is a labelling policy, in the same family as 010's Policy S.
- **When it is fixed:** before any fixture, candidate wording or held-out line is written.
- **Who applies it:** the operator's labels, every candidate wording (verbatim, §8.3) and the dismissal
  reasons (§13a).
- **Where it is recorded:** the spec records it as a `/speckit-clarify` clarification. The operator confirms
  or edits it there.

| #   | Case                                                                                                                                                                                                                                                                                                                | Label                                                      | Illustration                                                                                                                                                           |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| D1  | **The expected answerer decides, not the addressee.** Classify by who should reasonably provide the useful or authoritative answer, not simply by who the message is addressed to. *(Reworded and confirmed by the operator, 2026-10-07; first wording: "The subject and the answerer decide, not the addressee.")* | —                                                          | «يا شباب التسجيل فتح؟» → `asking` · «يا شباب مين اختبر اليوم؟» → `discussion` · «يا أحمد رابط المحاضرة فين؟» → `asking` · «يا أحمد كيف حليت السؤال 15؟» → `discussion` |
| D2  | A **peer-addressed service question**: schedule, exam arrangements, access, links, the platform, materials, recordings, registration, payment, certificates, group rules                                                                                                                                            | `asking`                                                   | «يا شباب الاختبار اتأجل ولا لا» · «يا جماعة حد عنده رابط المحاضرة»                                                                                                     |
| D3  | A **named-peer or peer-group question about the members' own experience, work, answers or opinions**                                                                                                                                                                                                                | `discussion`                                               | «يا أحمد كيف حليت السؤال 15؟» · «يا شباب مين اختبر اليوم؟» · «حد خلص الواجب»                                                                                           |
| D4  | A **member answering another member**                                                                                                                                                                                                                                                                               | `informing`                                                | «أنا حليته بالطريقة الثانية»                                                                                                                                           |
| D5  | A **peer-addressed problem check**: the writer has, or suspects, a service problem                                                                                                                                                                                                                                  | `asking`                                                   | «الرابط شغال عندكم؟» · «حد المنصة فاتحة معاه»                                                                                                                          |
| D6  | A **course-content question with no addressee**: whether course content is the team's to answer is not yet decided                                                                                                                                                                                                  | `asking`, `label_class: ambiguous` (reported, never gated) | «ما فهمت السؤال 15 في الواجب»                                                                                                                                          |
| D7  | **Tie-break:** when it is unclear whether the team is needed, choose `asking`                                                                                                                                                                                                                                       | `asking`                                                   | —                                                                                                                                                                      |
| D8  | **Limitation: reply context is invisible.** The model sees words only: forms of address («يا أحمد», «يا شباب») and the `«مستخدم»` placeholder for a redacted @handle. It does not see which message is being replied to, or by whom                                                                                 | D7 applies                                                 | «كيف حليته؟», sent as a bare reply to a peer                                                                                                                           |

- **Why D7 leans to `asking`.** A wrongly opened item costs one "Member discussion" dismissal. A missed need
  costs a member left unanswered. This is Policy S's direction ("avoiding missed real questions is preferred"),
  applied to the addressee.
- **The illustrations show the policy, not fixture lines.** Several of them carry a v1 signal (`؟`, `كيف`,
  `مين`). Fixture `peer` lines in the in-repo sets must be rule-declined (§8.1).
- **Most D3 messages never reach the model.** In their usual form they carry a v1 signal (D3's first two
  illustrations open by rule; §3a), so rule set v1 opens them first.
  - **In TG-M5.3:** the `discussion` intent decides only peer questions with **no** v1 signal.
  - **For the rule-opened ones:** the dismissal reason (§13a) is what lets an operator mark them and lets the
    figures count them (§1, non-goals).

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

**Fixture keys** *(added 2026-10-07)*. These are additions to `needs_response`, `category`, `label_class` and
`tracked`:

| Key      | Values                                                  | Required on                                                                                                                                                                    | Validation                                                                                                                                                                                                                           |
| -------- | ------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `intent` | the six of §5                                           | every line written for TG-M5.3 (validation, held-out, burst, fresh sample); added to existing tuning lines where the operator's T031 pass touches them, at least on peer lines | unknown value → the run is `INCOMPLETE`; `intent == "asking"` must equal the line's `needs_response` label (one derivation, also in the fixtures)                                                                                    |
| `peer`   | `true`                                                  | lines addressed to members (D2, D3, D5)                                                                                                                                        | in the in-repo validation and held-out files, every `peer` line must be **rule-declined**: `evaluate([normalize(text)])` is false. A fixture test enforces it, since a rule-opened line never reaches the model and so tests nothing |
| `burst`  | a list of 2–5 texts, in posting order, replacing `text` | burst fixtures only (§8.4)                                                                                                                                                     | scored as in §8.2; never gated                                                                                                                                                                                                       |

### 8.2 Gates

**The attention suite** (every judgement takes the real path: rules first, then AE1/AE2, then the model, then
A1–A2):

| #   | Gate                                                                                                  | Passes when                                                                                                       |
| --- | ----------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| A1  | Tuning: clear negatives model-opened                                                                  | = 0                                                                                                               |
| A2  | Tuning: clear positives missed                                                                        | = 0                                                                                                               |
| A3  | Validation: clear negatives model-opened / rule-declined clear positives missed                       | ≤ 1 / ≤ 1                                                                                                         |
| A4  | Held-out: the same                                                                                    | ≤ 1 / ≤ 1 of ≥ 10                                                                                                 |
| A5  | Fresh sample: the same                                                                                | ≤ 1 / ≤ 1 (required for `QUALIFIED`)                                                                              |
| A6  | Violations answered `asking` (every moderation-set line with needs_moderation true; no veto credited) | threshold set in the spec (proposed ≤ 1, lines reported)                                                          |
| A7  | Repeat                                                                                                | 0 differing lines, `--repeat` ≥ 2                                                                                 |
| A8  | Latency                                                                                               | p95 single call ≤ 10 s. The per-message estimate (§10) is reported for the serving mode of the host the run is on |
| A9  | Errors                                                                                                | = 0                                                                                                               |
| —   | Ambiguous (Policy S); intent agreement                                                                | reported, never gated                                                                                             |

*(2026-10-07)* **The gates and thresholds are unchanged.**
- Rule-declined peer-discussion lines (D3) are clear negatives. They count under A1, A3, A4 and A5.
- Rule-declined peer-addressed service and problem-check lines (D2, D5) are clear positives. They count under
  A2, A3, A4 and A5.
- Three **reported lines, never gated**, are added per set:

| Line                            | Shows                                                                                                                                                                                                                                                                                          |
| ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Asking vs discussion**        | four counts: label `asking` answered `discussion` (a miss caused by the new intent); label `discussion` answered `asking` (an open caused by it); `peer` lines correct; `peer` lines judged. Plus each disagreeing line's set and number, never its text                                       |
| **Clear negatives rule-opened** | the rule baseline on the set: negatives the rules open before any model is asked, `peer` lines counted apart. This is where rule-opened peer discussion shows up                                                                                                                               |
| **Burst fixtures**              | per burst line: the opener (`rule` / `model` / `none`), the member that opened it, and the expected outcome. Scored on the real path: `evaluate` over all members; else AE1/AE2 and the model per member; it opens if any member is `asking`. The L-B1 lines (§3a) are expected to show `none` |

**The moderation suite:** 010's Q5–Q7 and Q10–Q12 unchanged, plus repeat and errors, over `classify_v2` and the
moderation profile. Q1–Q4 and Q9 move to the attention suite as A1–A5.

**The production rule (R1 restated):** `MODERATION_AI_ATTENTION_FROM` may be set only when the active attention
profile + `MODERATION_ATTENTION_PROMPT_VERSION` is `QUALIFIED` on that host. Any change to the moderation pair
requires a `QUALIFIED` moderation suite.

### 8.3 Wording selection: is the distinction learned, or are nouns memorised? (open decision 8)

> *(2026-10-09)* **The second cycle** (`attention_v2` under Policy D′) follows the addendum's §6.3–§6.4. There are
> three candidates, each `attention_v1` with only the policy sentences replaced; they differ in where D0 sits
> (V2-A > V2-B > V2-C). The rest of this section describes the first cycle, which froze `attention_v1`.

The candidates are fixed **before any run**, all with the §5 schema. *(2026-10-07)* **All three carry the same
words** for:
- the six intent definitions;
- Policy D's D1–D7, including the D7 tie-break.

The policy is not a variable between candidates. Only the noun question below is.

| Candidate                         | Content                                                                                                                                                                       |
| --------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **W1, generic**                   | asking / informing / mixed / Policy S / social / offering; no domain nouns                                                                                                    |
| **W2, P2-derived**                | P2's measured Asking/Informing paragraphs (010 research §2), adapted to the single task, with P2's noun lists as measured                                                     |
| **W3, generic + domain glossary** | W1 plus one sentence naming what the *service* provides (lectures, recordings, links, books, exams, registration, the platform). A glossary of the domain, not fixture topics |

1. **Selection round, run once.**
   - **Matrix:** each candidate × {e2b, e4b}, `--repeat 2`, on the tuning sets plus a new **validation set**.
   - **The validation set:** synthetic, about 40 lines, on topics outside **both** the tuning vocabulary and
     the held-out list. For example: app installation, attendance/absence, study-plan changes, mock-exam
     access, audio/video quality, account name change, refund status, mentor contact.
     - *(2026-10-07)* **About 12 of the lines are `peer` lines, all rule-declined:**
       - at least 6 peer-discussion negatives (D3);
       - at least 3 peer-addressed service positives (D2);
       - at least 1 peer problem check (D5);
       - at least 2 unaddressed course-content lines (D6, ambiguous).
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

> *(2026-10-09)* **For the second cycle** (addendum §6.1):
> - tuning gains `real-attention-fresh-v1.jsonl`, T077's sample relabelled under D′;
> - validation gains `attention_validation_scope_fixtures.jsonl` and the v1 held-out set, renamed
>   `attention_heldout_v1_fixtures.jsonl` and kept byte-identical. A3 is judged per validation set;
> - a new held-out set and a new fresh sample are written.

| Set                                                         | Kind       | Role                                    | Status                                                                                                                                                                                                                                                                                                |
| ----------------------------------------------------------- | ---------- | --------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `real-attention*.jsonl` (operator's, outside Git)           | attention  | tuning                                  | exists. **T031's annotations are needed first** (ambiguous lines, plan §13). *(2026-10-07)* The same pass adds `intent` and `peer` to any peer line, under Policy D                                                                                                                                   |
| `attention_smoke_fixtures.jsonl`                            | attention  | tuning                                  | exists, annotated. *(2026-10-07)* It has peer-addressed informing and social lines (#10, #11, #14) but **no peer question**. It stays unedited: new peer lines go to the validation and held-out sets                                                                                                 |
| `attention_validation_fixtures.jsonl`                       | attention  | validation (selection)                  | new, written before the selection round. *(2026-10-07)* It includes the peer lines of §8.3                                                                                                                                                                                                            |
| `attention_burst_fixtures.jsonl`                            | attention  | **reported only** (never gated)         | *(2026-10-07)* new, written with the validation set. About 8 lines: §3a's first and third bursts (expected `rule`); at least 3 of §3a's fourth-burst variants (expected `model`); at least 2 L-B1 lines (expected `none`, documenting the limitation); 1 greeting + peer discussion (expected `none`) |
| `attention_heldout_fixtures.jsonl`                          | attention  | held-out                                | new, **written after the freeze**; 010 data-model §3's grid and topics, which were never written. *(2026-10-07)* It includes peer lines (§9)                                                                                                                                                          |
| `fresh-attention.jsonl` (operator's)                        | attention  | fresh sample                            | operator; labelled before any run. *(2026-10-07)* `intent` on every line; real peer discussion and peer-addressed service questions included as they occur (§9)                                                                                                                                       |
| `real-moderation.jsonl`, `moderation_smoke*_fixtures.jsonl` | moderation | moderation suite; **also attention A6** | exist; tracked #1 and #11 unchanged                                                                                                                                                                                                                                                                   |

## 9. Held-out and fresh real sample

> *(2026-10-09)* **For the second cycle,** the held-out topics and minimums are the addendum's §6.6, fixed before
> any v2 candidate, and the fresh sample is §6.7's. T077's sample (37 lines run, later cut to 30) is never a fresh
> sample again. The text below describes the first cycle.

- **Held-out:** written only after `attention_vN` is pinned, run once on the chosen pair, never edited
  afterwards, and a failure is reported as it stands (010 X2/X4). Its topics (certificate, grades, homework
  submission, payment receipt, group link, exam hall, meeting app, timetable file) differ from the tuning and
  validation vocabulary. At least 10 rule-declined clear positives; at least 80% without a question mark.
  - *(2026-10-07)* **Peer lines, all rule-declined and on the same topics:**
    - at least 3 peer-discussion negatives (D3);
    - at least 2 peer-addressed positives (D2 or D5). These count toward the 10.
- **Fresh sample:** 20–30 real messages, labelled by the operator before any run, never tuned against.
  Required for `QUALIFIED`, as 010 Q9.
  - *(2026-10-07)* **Labels:** every line carries `intent` under Policy D.
  - **Peer coverage:** the operator includes real peer discussion and peer-addressed service questions as the
    groups provide them, aiming for at least 3 of each.
  - **Rule-opened lines:** real peer lines that the rules open are kept. They appear in the "clear negatives
    rule-opened" line, not in the gates.
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
- *(2026-10-07)* **The exceptions** (§13a), all on the operator-correction side, never the rule side:
  - the dismissal reasons gain `member_discussion`;
  - the rule-set accuracy figure (§5) gains an additive per-reason breakdown;
  - M10's rationale is reworded.
- Rule set v1's literals and conditions and `RULE_VERSION` are untouched, so no TG-M3 rule or burst test
  changes.

**TG-M5:** `classify_v2` and its route, incidents and possible violations are unchanged. Its `needs_response`
returns to measurement only: `classify_one` stops calling `request_rejudgement`. Contract R13/N1/F6 get a
dated re-amendment.

**TG-M5.1** (`attention-opening.md` gets a dated amendment, not a rewrite):

| Item                            | Change                                                                                                                                 |
| ------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| G1–G4                           | replaced by A1 `path='live'`, A2 `needs_response` (derived from `intent`), and V, the SPAM_OR_AD/ABUSE veto. G3 lapses (no confidence) |
| G5–G6 `within_attention_window` | unchanged. The judgement's `created_at` is compared with the switch and the item's age                                                 |
| O1–O5                           | unchanged, except O3: the item carries `attention_judgement_id`                                                                        |
| I1–I4 reconciliation            | unchanged mechanism, now called from the attention judgement's transaction                                                             |
| L1–L3 live vs catch-up          | unchanged: only live judgements pass; switching on never reaches back (G5)                                                             |
| T1–T4                           | unchanged                                                                                                                              |
| §9 limitations                  | *(2026-10-07)* gains L-B1 (§3a): a request spread over burst members, none of them `asking` alone, is not opened by the model          |
| D1–D2 dual purpose              | now two judgements: an incident and a question item can both open; adverts and abuse are vetoed on the question side                   |
| `source='ai'`                   | unchanged meaning; the link column depends on era (the §4 check)                                                                       |
| No backfill                     | unchanged. Historical items keep their classification link; nothing is re-derived                                                      |

**Removed, not kept as a fallback** (open decision 9): the classification-sourced proposal. It never
qualified (Finding 10), and two sources would be two definitions of "the model proposes".
- **The deploy-time consequence:** once TG-M5.3 deploys with `MODERATION_ATTENTION_PROMPT_VERSION` blank, AI
  opening stops, even where `MODERATION_AI_ATTENTION_FROM` is set. That affects development, where the switch
  is set today.

## 13. Observability and metrics

- **C9** (model-opened questions, the M24 pilot gate):
  - groups by the *opening* judgement's (model, prompt);
  - unions the history (classification-linked, TG-M5.1) with the new rows (attention-linked, TG-M5.3);
  - each era has its own rows, never pooled (K3);
  - *(2026-10-07)* gains the per-reason dismissal breakdown of §13a. M24's definition is unchanged.
- **C6** (the queue label): shows the attention judgement's intent on the item's earliest `asking` member. The
  classification's category stays available.
- **C1/C2:** attention-judgement rows are added beside the classification rows, grouped by attention prompt.
  - **Limit:** rule-opened members are mostly AE2-skipped. The attention model's agreement on rule-opened
    questions therefore comes from the benchmark, not production. This is stated on the page.
- **New, C10 (coverage and timeliness):**
  - each eligible message's attention status: judged / excluded (reason, including `rule_opens`) / failed /
    not yet;
  - the share of judgements landing before the settle, per model;
  - *(2026-10-07)* **judged, by intent**: the six-value count per (model, prompt), so `discussion` volume is
    visible;
  - *(2026-10-07)* **operator-added items** (the misses a person noticed), split two ways:
    - by their anchor's attention status: judged `asking` / judged non-asking, by intent / excluded, by
      reason / failed / none;
    - by **single- vs multi-message burst**: the exact neighbour test of §3a, a same-sender, same-chat,
      same-thread message within `MODERATION_BURST_GAP_S` of the anchor.

    This is L-B1's pilot measure.
- **The panel:** the SQL above in the existing pages. No state, gate or derivation is computed in PHP; it reads
  stored `needs_response`, `intent` and links. `DatabaseTransactions` tests, as before.

## 13a. Dismissal reasons and their figures (added 2026-10-07)

**The new reason.** A third row action on the Live Attention Queue, for items of every source (`rule`, `ai`,
`operator`), beside the existing two.

| Action label                  | `close_reason`      | Means                                                                                     |
| ----------------------------- | ------------------- | ----------------------------------------------------------------------------------------- |
| Not a real question           | `not_a_question`    | not a question or request at all: there was never anything to answer                      |
| **Member discussion** *(new)* | `member_discussion` | a real question or discussion **between members**; no moderator was needed (Policy D, D3) |
| Message removed               | `message_removed`   | the operator's own judgement that the message is gone (TG-M3 P7, unchanged)               |

- **Status and the write.** `status = 'dismissed'`, through the same guarded write (TG-M3 C8), with confirmation
  and no bulk action (P5). The confirmation text states the meaning in the table above, so the two
  question-like reasons stay distinct.
- **No migration.** `close_reason` is `varchar(40)` with no CHECK (revision `0005`), and FR-051 already reads
  "at minimum" two reasons. A dated note on FR-051 lists the third.
- **Why it matters even before any model work.** A peer question that rule set v1 opens stays open until it
  expires, because only a moderator's message closes an item (TG-M3 §4). Expired items stay in the unanswered
  count for good (M11). Dismissing it takes it out of the unanswered count and the response-time figures
  (M10), which is correct.

**Every existing count is unchanged.** Every figure that counts `status = 'dismissed'` keeps counting it for
**every** reason, so each stays comparable with its own history:
- unanswered and opened (TG-M3 M9–M10);
- rule precision (TG-M3 §5 and C7);
- C1's `rule_dismissed` label;
- C9's `model_dismissed`, including **M24, the pilot gate: dismissed (any reason) ÷ opened**.

The breakdown below is diagnostic only. It never moves a gate.

**The per-reason breakdown is additive.** It sits beside each dismissal count:
- `dismissed_not_a_question`, `dismissed_member_discussion`, `dismissed_message_removed`, and
  `dismissed_other` (operator text, or a reason not listed);
- **on:** C7, the rule baseline (per `rule_version`), and C9, questions the model opened (per opening
  judgement, both eras);
- **tested:** the parts sum to the existing count, in Python and PHP, over one hand-computed scenario.

**Reading the breakdown:**
- `member_discussion` **on model-opened items** → the `asking`/`discussion` boundary of `attention_vN`
  (Policy D).
- `member_discussion` **on rule-opened items** → evidence for, or against, a later rule_version 2 milestone (§1
  non-goals).
- `not_a_question` → the `asking`/`informing` boundary, Policy S.

**Wording corrections.** The existing text calls every dismissal "not a real question". It is already wrong,
because `message_removed` is counted too, and a third reason makes it worse. These lines change in 011:

| Where                                                                                  | Today                                                                    | Becomes                                                                                                                         |
| -------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------- |
| `apps/ai-control/resources/views/filament/pages/classification-accuracy.blade.php:145` | "Model-opened, dismissed as not a real question: n / N"                  | "Model-opened, dismissed (any reason): n / N", then "not a real question a · member discussion b · message removed c · other d" |
| the same page, rule baseline (lines 49–62)                                             | "Rule-dismissed"                                                         | "Rule-dismissed (any reason)" and the same breakdown; precision unchanged                                                       |
| `apps/ai-control/tests/Feature/ModelOpenedQuestionsTest.php:124–132`                   | asserts `model_questions`' exact shape and the old sentence              | the shape gains the breakdown; asserts the new sentence                                                                         |
| `specs/008-…/contracts/control-panel-classification.md` §4, TG-M5.1 note               | "dismissed as not a real question · answered · still unanswered"         | "dismissed (any reason), with its per-reason breakdown · answered · still unanswered"                                           |
| `specs/009-…/quickstart.md` §5                                                         | "the **dismissed as not a real question** ratio is the operational gate" | "the **dismissed (any reason)** ratio is the operational gate; its breakdown says why"                                          |
| `specs/006-…/contracts/attention-metrics.md` M10                                       | "They were never real questions."                                        | "None of them needed a moderator's answer: not a real question, a member discussion, or a removed message."                     |

## 14. Migration, rollout, rollback

*(2026-10-07)* **First, on its own:** the `member_discussion` reason, the breakdowns and the wording corrections
(§13a).
- It needs no migration, no model and no switch, and can deploy before step 1.
- Rolling it back removes the action. Rows already dismissed with that reason keep it, and stay counted as
  dismissed.

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

| Risk                                                                                                        | Mitigation                                                                                                                                                                                   |
| ----------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Overfitting** the wording to about 60 tuning lines                                                        | Candidates fixed before running; one selection round + ≤ 1 revision; an off-vocabulary validation set; held-out written after the freeze and run once; a fresh real sample; a stop condition |
| **Noun memorisation** (the #15 lesson)                                                                      | W1 vs W3 vs W2 compared on validation topics outside every list (§8.3)                                                                                                                       |
| **Coupling** through the veto                                                                               | One-way, read-only, two categories. A6 measures the attention judgement alone; the veto is never credited                                                                                    |
| **Late judgements** under backlog                                                                           | The current scheduling policy (Attention first on a shared constrained lane); concurrent serving where available; the C10 timeliness figure; Case B reconciliation is already correct        |
| **Serving limits leaking into the domain** (lane, Mac memory)                                               | Independence is the contract; ordering, concurrency, threads and model placement are deployment policy, labelled as current, changeable without a contract change                            |
| **The one-message benchmark vs real bursts**                                                                | Unchanged from TG-M5.1 (D-TG-171); the pilot's dismissal rate is the backstop. *(2026-10-07)* Partly measured now: burst fixtures (reported) and C10's multi-message misses (§3a)            |
| *(2026-10-07)* **`discussion` swallows real needs** (peer-addressed service questions, peer problem checks) | Policy D's D2, D5 and D7 in every candidate, verbatim; A2 = 0 on tuning; rule-declined peer positives in validation, held-out and fresh sample; the asking-vs-discussion line                |
| *(2026-10-07)* **Peer-discussion volume is mostly rule-opened**                                             | Not the model's to fix in TG-M5.3. Counted by `member_discussion` on rule items; a rule_version 2 milestone only if that count justifies one                                                 |
| *(2026-10-07)* **Reply context is invisible to the model** (D8)                                             | The D7 tie-break; a stated limitation                                                                                                                                                        |
| *(2026-10-07)* **Distributed intent** (L-B1)                                                                | Documented; burst fixtures; C10's operator-added split by burst size; a follow-up milestone only on that evidence                                                                            |
| *(2026-10-07)* **The breakdown and the existing counts diverge**                                            | A sum-of-parts test on both sides; existing definitions untouched                                                                                                                            |
| **An edit removes the signal of an AE2-skipped message**                                                    | Stated limitation; rare; hand-opening                                                                                                                                                        |
| **Model swapping** if the two tasks need different models                                                   | Same-model preference; memory checked during qualification                                                                                                                                   |
| **Label ambiguity** (Policy S)                                                                              | Ambiguous lines are reported, never gated; T031 annotations; label reviews stay the operator's                                                                                               |
| **A metrics discontinuity** (C9 eras)                                                                       | Per-era rows; no pooling                                                                                                                                                                     |
| **Prompt injection**                                                                                        | §6's stack; the capability bound is the real control                                                                                                                                         |

## 16. Decisions: approved 2026-10-06, every recommended option

1. **Storage:** typed sibling tables (recommended) vs a generic judgements table.
2. **Output:** an `intent` enum with derived `needs_response` and no confidence (recommended), vs a boolean.
   *(Extended by decision 16.)*
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

### Amendments of 2026-10-07: approved 2026-10-07, as written

These come from the operator's 2026-10-07 review. The operator approved items 13–19 as written, and confirmed
two points:
- **D6 stays** "a course-content question with no addressee → `asking`, marked ambiguous". It is revisited
  only if pilot data shows most of these are peer discussion.
- **The wording correction is not applied separately.** It ships inside 011's first story, together with
  `member_discussion` and the per-reason breakdowns.

13. **Dismissal reason `member_discussion`**, labelled "Member discussion".
    - It is distinct from "Not a real question", and the status stays `dismissed`.
    - It applies to items of every source.
    - It is 011's first story, deployable on its own with no migration (§13a, §14).
14. **Existing counts unchanged; breakdowns added.**
    - Every figure that counts dismissals keeps counting every reason: rule precision, unanswered/opened, C1,
      and C9/M24.
    - Per-reason breakdowns are added to C7 and C9, diagnostic only, with a sum-of-parts test.
15. **Wording correction:** "dismissed as not a real question" becomes "dismissed (any reason)" plus the
    breakdown. It applies on the panel, 008's panel contract, 009's quickstart and TG-M3's M10 (§13a table).
16. **Intent schema:**
    - It gains `discussion`.
    - `asking` is tightened to "needs an answer, action, clarification or decision from the team".
    - `needs_response = (intent == "asking")` stays the single derivation (§5).
17. **Policy D** (D1–D8, §5a) is fixed before any fixture or candidate wording, and recorded in the spec as a
    clarification. Its key rules:
    - peer-addressed service questions and peer problem checks → `asking`;
    - named-peer academic or experience questions → `discussion`;
    - unaddressed course-content questions → `asking`, ambiguous;
    - unclear → `asking`.
18. **Qualification coverage:**
    - the `intent`, `peer` and `burst` fixture keys;
    - rule-declined peer lines in validation (about 12) and held-out (at least 5), enforced by a fixture test;
    - peer lines and `intent` in the fresh sample;
    - three reported lines: asking vs discussion, clear negatives rule-opened, and burst fixtures;
    - gates and thresholds unchanged (§8).
19. **Bursts:**
    - TG-M3 burst logic stays unchanged; the greeting + later question case is already handled (§3a).
    - There is no burst-level model input.
    - L-B1 is documented in 009 §9 and measured by burst fixtures and C10's operator-added split.
    - A follow-up milestone is considered only on that evidence.

## 17. Next Spec-Kit step after approval

1. **Operator:**
   - T031's annotations of the external attention sets (ambiguous lines; real moderation #1 `no-link-rule`).
     *(2026-10-07)* The same pass adds `intent` and `peer` to peer lines under Policy D.
   - The fresh sample can follow, but must exist before `QUALIFIED`.
   - *(2026-10-07)* Confirm or edit Policy D (§5a) before any fixture is written.
2. **`/speckit-specify`:** "TG-M5.3 per `docs/plan/telegram/tg-m5-3-attention-judgement-plan.md`, with the
   approved decisions *and the 2026-10-07 amendments*", giving `specs/011-tg-m5-3-attention-judgement/`.
3. **`/speckit-clarify`** for whatever §16 left open (*including Policy D*), then `/speckit-plan`. The contracts:
   - `attention-judgement.md`: AE1–AE2, A1–A2, V, the six-intent schema, Policy D, and failures;
   - `qualification.md` v2: the core plus suites, gates A1–A9, the fixture keys, and the reported lines;
   - dated amendments to the shipped contracts listed in §18.
4. **`/speckit-tasks`**, then implementation, which starts only on the operator's go-ahead.
   - *(2026-10-07)* **Story order:** §13a first (deployable alone), then the model work.

## 18. Planned contract amendments (added 2026-10-07)

**What exists today:** nothing below is written yet. Each item becomes a dated "Amended by TG-M5.3" note in
011, in the style of the existing TG-M5.1 notes, and none rewrites the original text.

| Contract                                                                | Section                        | Amendment                                                                                                                                                                             |
| ----------------------------------------------------------------------- | ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `specs/006-tg-m3-response-tracking/spec.md`                             | FR-051                         | note: the reasons offered are `not_a_question`, `member_discussion`, `message_removed` (FR-051's "at minimum" is satisfied, not changed)                                              |
| `specs/006-…/data-model.md`                                             | `attention_items.close_reason` | `not_a_question` \| `member_discussion` \| `message_removed` \| `expired` \| operator text. No constraint, no migration                                                               |
| `specs/006-…/contracts/control-panel-attention.md`                      | §2 Actions                     | new row "Dismiss (member discussion) \| row \| as above, `close_reason='member_discussion'`"; the three meanings of §13a in the action's confirmation; P5 and P8 unchanged            |
| `specs/006-…/contracts/attention-metrics.md`                            | §3 M10                         | the rationale reworded (§13a table); the SQL is unchanged                                                                                                                             |
| `specs/006-…/contracts/attention-metrics.md`                            | §5                             | additive per-reason columns beside `rule_dismissed`; precision stays `1 − rule_dismissed ÷ rule_opened`; M15 unchanged                                                                |
| `specs/008-tg-m5-ai-classification/contracts/classification-metrics.md` | C7                             | quotes §5 with the same additive columns                                                                                                                                              |
| `specs/008-…/contracts/classification-metrics.md`                       | §8a C9, M24                    | additive per-reason columns. M24: "`model_dismissed` (any reason) ÷ `model_opened`, unchanged; the breakdown is diagnostic and never moves the gate". The era union is already in §13 |
| `specs/008-…/contracts/classification-metrics.md`                       | new section, C10               | the judged-by-intent counts, and the operator-added split by anchor status and single/multi-message burst (§13)                                                                       |
| `specs/008-…/contracts/control-panel-classification.md`                 | §4                             | the TG-M5.1 note's wording (§13a); "Rule set baseline" gains the breakdown                                                                                                            |
| `specs/009-tg-m5-1-ai-attention/quickstart.md`                          | §5                             | the gate's wording (§13a)                                                                                                                                                             |
| `specs/009-…/contracts/attention-opening.md`                            | §9 limitations                 | L-B1 (§3a), beside the §12 table's other changes                                                                                                                                      |
| new `specs/011-…/contracts/attention-judgement.md`                      | —                              | the six intents, the single derivation, and Policy D D1–D8                                                                                                                            |
| new `specs/011-…/contracts/qualification.md` v2                         | —                              | the `intent`/`peer`/`burst` keys and their validation; the three reported lines; the peer coverage minimums                                                                           |

**The code and tests these touch** (for `/speckit-tasks`, not now):
- **Panel:**
  - `apps/ai-control/app/Filament/Pages/LiveAttentionQueue.php`: the action;
  - `apps/ai-control/app/Filament/Pages/Concerns/ClassificationMetrics.php`: the breakdowns in
    `classificationRuleBaseline` and `classificationModelOpenedQuestions`;
  - `apps/ai-control/resources/views/filament/pages/classification-accuracy.blade.php`.
- **Panel tests:**
  - `AttentionDismissTest.php`: the reason is recorded; a second dismissal is a no-op;
  - `ModelViewDisplayTest.php:207–208`: the action exists;
  - `ModelOpenedQuestionsTest.php:124–132`.
- **API tests:**
  - `apps/ai-api/tests/moderation/classification/test_metrics_model_opened.py`, and the C7 figure test if it
    asserts exact columns;
  - the qualification scoring tests: keys, reported lines, burst scoring;
  - the rule-declined `peer` fixture test;
  - the intent-derivation unit test (`discussion` → false).
- **No TG-M3 rule, burst or literal test changes.**

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
  - *(2026-10-07)* the `member_discussion` action through the guarded write, its breakdowns summing to the
    unchanged dismissal counts, and the corrected wording;
  - *(2026-10-07)* `discussion` deriving `needs_response = false`, and the fixture validation (`intent` agrees
    with the label; every in-repo `peer` line is rule-declined);
  - every TG-M3, TG-M4, TG-M5 and TG-M5.1 suite unchanged in outcome, apart from the asserted wording and
    breakdown shape (§18).
- **The qualification runs:**
  - the selection matrix, the freeze, the held-out run once, and the fresh sample, with counts recorded in
    011's research;
  - 010's C2/C3 checks (no rows written, no Arabic characters in output) on every run.
- **The development shadow week:** the C10 coverage and timeliness figures, then the pilot's M24.
