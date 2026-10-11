# Contract: the Attention Judgement

**Feature**: `specs/011-tg-m5-3-attention-judgement` · **Status**: durable from TG-M5.3 onwards.
- **What it replaces:** TG-M5.1's gate G1–G4 and its classification-sourced proposal
  (`specs/009-tg-m5-1-ai-attention/contracts/attention-opening.md` §1–§3).
- **What it leaves alone:** everything TG-M3's `attention-rules.md` decides, and everything TG-M5's
  `classification-pipeline.md` decides about moderation.

**The rule that carries it: one message, one question, one answer.** "Does this message need an answer, action,
clarification or decision from the team?" is asked by its own instruction, answered as one intent, recorded
once, and read by `open_item` only after the rules decline.

---

## §1 — Dispatch

- **J1.** `derive_message` sends `judge_attention(chat_pk, message_id)` for every newly inserted message. It is
  sent **before** `classify_message`, under the same condition (pipeline Q1). A duplicate delivery sends nothing.
- **J2.** `judge_attention` is a Dramatiq actor on queue `moderation_attention`. It runs `judge_one` with a
  per-task `Gateway(max_retries=0)`.
- **J3.** The **current** deployment is deployment policy, not contract (D-TG-187):
  - `ai-classifier` consumes `moderation_attention` and `moderation_classify`, with one process and one thread;
  - `judge_attention.priority = 0` and `classify_message.priority = 10`.

  So Attention runs first when both wait for the same worker. Any other topology is a compose change.
- **J4.** Neither judgement waits for, orders after, or reads the other. **The only exception is V (§6)**, read
  at opening time by `open_item`, never by either judgement.

## §2 — Eligibility

These are pure functions in `app/domain/moderation/attention_judgement.py`, the only definition:
- **AE1.** `classification.eligibility(facts)`. The same `MessageFacts` come from the same `load_facts`, which
  read the captured event (Finding 5). The reasons are E1–E8.
- **AE2.** `evaluate([facts.text])` is true: the message's own first-posted, normalised words open rule set v1.
  The result is excluded as `rule_opens`. It is exact (D-TG-186) and calls the rules' own function.
- **AE3.** An exclusion is recorded once (`uq_attention_attempt_exclusion`, `ON CONFLICT DO NOTHING`), and no call
  is made.

## §3 — The instruction and the request

- **P1.** `system` = `app/prompts/moderation/<MODERATION_ATTENTION_PROMPT_VERSION>.md`, read once at import;
  `user` = `redact(text)`. Nothing else is sent: no sender, group, time, reply target or neighbouring message.
- **P2.** The redacted string is bound only to `redacted_text` and is never logged (check 4). No line of any log
  carries message text or the model's raw output.
- **P3.** Every attention instruction is pinned by its SHA-256. A new wording is a new file, a new version and a
  new `ATTENTION_PROMPT_VERSIONS` entry. The tuple is empty until `attention_v1` is frozen (D-TG-189).
  - *(2026-10-07)* `attention_v1` was frozen, giving `("attention_v1",)`.
  - *(2026-10-09)* Under Policy D′ (§5), `attention_v2` is added when it is frozen, giving
    `("attention_v1", "attention_v2")`. `attention_v1`'s file, pin and entry stay unchanged, as history.
- **P4.** `MODERATION_ATTENTION_PROMPT_VERSION` blank, or no active `attention` profile, means: no claim, no call
  and no row.

## §4 — The answer

```json
{"intent": "asking" | "discussion" | "informing" | "social" | "offering" | "other"}
```

- **S1.** `AttentionJudgementResult` has exactly this one field, as a `Literal`. Anything else is
  `structured_output_invalid` (F3).
- **S2.** `needs_response = needs_response_for(intent)` = `intent == "asking"`. **This is the single
  derivation.** It is stored with the row and never recomputed (no CHECK, PHP, SQL or prompt restates it).
- **S3.** The intents:

| Intent | Means |
|---|---|
| `asking` | reasonably needs an answer, action, clarification or decision from the team (moderators, instructors, administration): a question or request about **the course's own** service, a problem the writer still has **with it**, or a Policy S bare statement of **the course's own** arrangement. Being grammatically a question does not decide it; lacking a question mark does not stop it |
| `discussion` | a genuine question or prompt between members, about their own experience, work, answers or opinions, **or about an outside institution**; no moderator needed |
| `informing` | states information, including a member answering another member, or a resolved status. **A bare statement or complaint about an outside institution** |
| `social` | greetings, thanks, congratulations, wishes, small talk with no question |
| `offering` | offers or promotes a service, product, group or contact |
| `other` | none of the above |

*(Amended 2026-10-09, Policy D′, §5.)* The words in bold are new. `attention_v1` states the rows without them.

## §5 — Policy D, the asking/discussion boundary

It binds the labels, every candidate wording (verbatim) and the dismissal reasons.

### §5′ — Policy D′ (in force from 2026-10-09)

The operator chose option (a) on 2026-10-08: outside institutions are not the team's. The exact text was approved
on 2026-10-09 (spec FR-310 and Clarifications; `docs/plan/telegram/tg-m5-3-attention-v2-addendum.md` §3). It binds
`attention_v2` and every label written from 2026-10-09.

| # | Case | Label |
|---|---|---|
| **D0** | **The team's responsibility.** The team answers for the course's own service and for course content. The course's own service is its schedule and sessions, its tests and their arrangements, access, links, the platform, materials, recordings, registration and payment with the course, its certificates, and the group's rules. An outside institution's service or process is not the team's: a university, a national testing or licensing body, a ministry or another government portal. This holds even for the exams the course prepares students for. Their registration, appointments, results and licences belong to the outside body; what they test is course content. | — |
| D1 | **The expected answerer decides, not the addressee or the form.** A message is `asking` only when the team is reasonably expected to give the useful answer, action, clarification or authoritative guidance. A question, a described problem, an education topic, or an address to the group ("does anyone know?") does not by itself make a message `asking`. | — |
| D2 | A peer-addressed question about the course's own service (D0) | `asking` |
| D3 | A question between members whose useful answer comes from the members' own experience, work, answers or opinions, or from what members know of an outside institution, including help with an outside institution's site or system | `discussion` |
| D4 | A member answering another member | `informing` |
| D5 | A peer-addressed problem check about the course's own service | `asking` |
| D6 | A course-content question with no addressee | `asking`, `label_class: ambiguous` |
| D7 | When it is unclear whether the team is needed, including whether the subject is the course's own service or an outside institution's, choose `asking` | `asking` |
| D8 | Reply context is not visible to the model | D7 applies; a stated limitation |

**Policy S's scope narrows with it.** A bare statement asks for confirmation only when it is about the course's
own arrangement. A bare statement or complaint about an outside institution is `informing`.

**Why D7 still leans to `asking`.** A message that does not say whose registration, test or results it means may
be about the course's own service. A missed question costs a member left unanswered; a wrong opening costs one
dismissal.

D′'s added illustrations are synthetic, and each is rule-opened by its `؟`:
- «يا شباب نتائج الجامعة طلعت؟» → `discussion`: an outside institution.
- «يا شباب نتائج الاختبار التجريبي طلعت؟» → `asking`: the course's own test.

**Rule-opened messages are unchanged.** An outside-institution question that carries a v1 signal opens by rule
before any model is asked. It is dismissed as "Member discussion", whose wording (`dismissal-reasons.md`) already
covers it.

### §5 as confirmed on 2026-10-07: Policy D, history

**Confirmed by the operator on 2026-10-07** (T070, spec FR-310 and Clarifications), with D1 reworded; D2–D8 as
written. It governs `attention_v1` and its T071–T077 evidence.

| # | Case | Label |
|---|---|---|
| D1 | **The expected answerer decides, not the addressee.** Classify by who should reasonably provide the useful or authoritative answer, not simply by who the message is addressed to | — |
| D2 | A peer-addressed service question: schedule, exam arrangements, access, links, the platform, materials, recordings, registration, payment, certificates, group rules | `asking` |
| D3 | A named-peer or peer-group question about the members' own experience, work, answers or opinions | `discussion` |
| D4 | A member answering another member | `informing` |
| D5 | A peer-addressed problem check | `asking` |
| D6 | A course-content question with no addressee | `asking`, `label_class: ambiguous` |
| D7 | Unclear whether the team is needed | `asking` |
| D8 | Reply context is not visible to the model | D7 applies; a stated limitation |

D1's illustrations (the operator's, 2026-10-07). They show the policy and are not fixture lines; each carries `؟`,
so rule set v1 opens it first:
- «يا شباب التسجيل فتح؟» → `asking`: the team is the authority on registration.
- «يا شباب مين اختبر اليوم؟» → `discussion`: the answer comes from members' own experience.
- «يا أحمد رابط المحاضرة فين؟» → `asking`: the subject is an official service or resource.
- «يا أحمد كيف حليت السؤال 15؟» → `discussion`: the requested answer is Ahmed's own work or experience.

## §6 — Opening

`open_item`, under `chat_lock`, after rule set v1 declines. It runs only when `ai_attention_from_settings` returns
a switch, which requires **both** `MODERATION_AI_ATTENTION_FROM` and `MODERATION_ATTENTION_PROMPT_VERSION` to be
set (D-TG-199):

- **A1.** The judgement is current and `path = 'live'`.
- **A2.** `needs_response` is true, read from the row (`judgement_proposes`).
- **G5–G6.** `within_attention_window(recorded_at = created_at, …)`, unchanged.
- **V.** The member's current classification, if any, has `category ∉ {SPAM_OR_AD, ABUSE}`.
  - **A missing classification does not veto.** The judgements are independent; a missing classification is not
    evidence of an advert.
  - `CHITCHAT` is never vetoed.
- **O2′.** The first member in the burst's `(sent_at, message_id)` order to pass A1, A2, G5–G6 and V opens the
  item.
- **O3′.** The item is `source = 'ai'`, `rule_version = NULL`, `attention_judgement_id` = that judgement,
  `message_classification_id = NULL` (`ck_attention_ai_link`).
  - Its anchor, `opened_at` and attribution are TG-M3's (B2, E3, A1), as in TG-M5.1 §5.
  - TG-M5.1's O1, O4 and O5 and T1–T4 are unchanged.

## §7 — The record, idempotency and reconciliation

- **W1.** `judge_one`:
  1. resolves the `attention` profile, then claims `ai:mod:attention:msg:{chat}:{message}` in Redis
     (compare-and-delete release);
  2. checks for an existing current judgement or exclusion (`already_judged`);
  3. applies AE1–AE2, calls the model, and inserts with `ON CONFLICT (chat, message) WHERE is_current DO NOTHING`.
- **W2.** In the **same transaction** as a live insert with `needs_response` true, and only when the switch is
  set, `judge_one` calls `request_rejudgement`. TG-M5.1's I1–I4, Case A and Case B are unchanged, with
  "prediction" read as "judgement".
- **W3.** `classify_one` **no longer** calls `request_rejudgement`. The classification's `needs_response` is
  measurement only again.
- **W4.** The claim keys of the two tasks differ (`ai:mod:classify:msg` and `ai:mod:attention:msg`), so neither
  blocks the other.

## §8 — Failure and retry

- **F1.** Transient errors (`provider_unreachable`, `model_timeout`, `circuit_open`) re-raise. `judge_attention`
  reschedules itself with `attempt + 1` and a doubling delay, up to `MODERATION_CLASSIFY_MAX_ATTEMPTS`
  (`MODERATION_CLASSIFY_RETRY_BASE_S` base). After that it records one failure.
- **F2.** Final errors (`model_truncated`, `structured_output_invalid`, `model_not_available`,
  `provider_rejected`, `provider_auth`) record one failure naming the profile, and open nothing.
- **F3.** A failed attention judgement never affects classification, and the reverse also holds. The rules
  still open explicit questions while either model is down.

## §9 — Live only

- **L1.** Only `derive_message`'s live dispatch judges. `classify_chat`, `rederive_chat` and any catch-up path
  never send `judge_attention`.
- **L2.** `rederive_chat --with-attention` re-judges bursts through `open_item` as today. It reads whatever live
  judgements exist and never creates one.

## §10 — What may never happen

- **N1.** Message text, the redacted text or the model's raw output in a log line or in the record.
- **N2.** A second definition of `needs_response_for`, AE1–AE2, A1–A2 or V, whether in PHP, SQL, a prompt or a
  test helper.
- **N3.** A model item opened from a catch-up judgement, from a judgement recorded before the switch, from one
  older than the maximum item age, or from a member classified `SPAM_OR_AD` or `ABUSE`.
- **N4.** A model item with no link, with both links, or a link on a rule or operator item
  (`ck_attention_ai_link`).
- **N5.** Either judgement waiting for, ordering after, or reading the other, except V at opening time.
- **N6.** The model closing, dismissing, expiring, re-dating or re-attributing any item, or any outbound
  message, alert or bot act.
- **N7.** Burst-level input to any model.

## §11 — Limitations, stated rather than hidden

- **L-B1. Distributed intent.** A request spread over burst members, none of which is `asking` when read alone,
  is not opened by the model. It is measured by the burst fixtures and by C10's operator-added split.
- **An edit removes an AE2-skipped member's only rule signal** inside the settle window. The burst declines and
  that member has no judgement. Hand-opening covers it.
- **D8. Reply context.** A peer question sent as a bare reply has no textual cue. Such questions usually carry a
  rule signal and open by rule.
- **Rule-opened peer questions** are outside the model's reach. They are counted by the `member_discussion`
  dismissal (`dismissal-reasons.md`).
- **The attention model down:** questions only the model would catch go untracked. Judgements that land within
  `MODERATION_ITEM_MAX_AGE_S` reconcile within one tick (TG-M5.1 §9, unchanged).
- **The greeting's call.** A greeting member gets its own call even when a later member opens by rule. This is
  accepted: the burst is not settled at ingest.
- **V is read once, at opening.** A classification that lands after the item opened cannot veto it, because
  nothing retracts an item (TG-M3 E4). With Attention scheduled first on a shared lane, this is most likely
  under backlog.
  - **The control is the attention judgement itself.** A6 gates it on every violation line with no veto
    credited, and adverts have their own `offering` intent.
  - **The incident path is unaffected,** and the question item is dismissed by hand.
