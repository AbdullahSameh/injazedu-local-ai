# Contract: The Classification Pipeline

**Feature**: `specs/008-tg-m5-ai-classification` · **Status**: durable from TG-M5 onwards — TG-M8 adds
reprocessing (a new prediction and an `is_current` flip) and a human verdict beside predictions; neither
changes anything here. **Amended 2026-10-01** (spec clarification session 2026-10-01): §2a adds an opt-in
second instruction; P3, O5 and C4 follow it. Nothing in eligibility, routing, opening, failure or idempotency
changed.

This is **the** TG-M5 contract: which messages reach the model, exactly what the model is given, what a
prediction is, how it is routed, how a confident one opens an incident, how failure is handled, and what no
code path may ever do. Its storage half lives in `data-model.md`; its arithmetic half in
`classification-metrics.md`; its screens in `control-panel-classification.md`.

**The rule that carries all of it: a prediction is a claim.** It is recorded once, with its provenance, and
never changed. The model may open an incident; it may never judge, dismiss, acknowledge, resolve or close
anything.

---

## §1 — Enqueueing

- **Q1.** `derive_message` sends `classify_message(telegram_chat_id, message_id, path="live")` for every
  newly inserted message, **after** its insert has committed — no settle window (FR-001). A duplicate
  delivery (`inserted_id is None`) sends nothing.
- **Q2.** `derive_message(…, schedule_classification=False)` sends nothing; `rederive_chat` always passes it.
  A re-derived message is history, and history is classified only by the catch-up command (§10), which
  never opens anything (D-TG-149).
- **Q3.** `classify_message` is declared on queue **`moderation_classify`**, consumed only by the
  `ai-classifier` service (one process, one thread). `ai-worker` consumes `default` only. A classification
  backlog therefore never occupies a thread that capture-derivation, question tracking or evidence needs
  (FR-022, Finding 4).
- **Q4.** Nothing else enqueues classification: no tick, no sweep, no screen.

---

## §2 — The instruction — `classify_v1`

`app/prompts/moderation/classify_v1.md`, byte for byte. Its version is its filename stem, stored on every
prediction; its SHA-256 is pinned by `tests/moderation/classification/test_prompt_pinned.py`. Changing the
words means a new file and a new version, never an edit (D-TG-136). It lives nowhere else and is never sent
to any external tool (FR-009).

```text
You classify ONE message posted in a student group of an online exam-preparation course. Students write in Arabic (Modern Standard, Saudi or Egyptian dialect), English, or a mix. The text has been normalised (for example ة is written ه and أ is written ا). Personal details were replaced before you see the message: «رابط» is a link, «رقم» is a phone number or long number, «بريد» is an email address, «مستخدم» is a username.

Choose exactly one category:
- QUESTION_COURSE: a question about the course itself — lecture times, links, content, materials, exams.
- QUESTION_ACCESS: a problem reaching what was paid for — payment made but the course or book is not showing, cannot log in, cannot open something.
- COMPLAINT: dissatisfaction or criticism of the course, the service or the team.
- CHITCHAT: greetings, thanks, emoji, social talk.
- SPAM_OR_AD: advertising, selling, promoting another course, group, channel or service, investment or money offers.
- ABUSE: insults, harassment, threats or inappropriate content.
- OTHER: none of the above.

Then decide:
- needs_response: true only if the writer asks a question or reports a problem that a moderator should answer. Always false for SPAM_OR_AD, ABUSE and CHITCHAT.
- needs_moderation: true if a moderator should act against the message itself (SPAM_OR_AD and ABUSE usually do).
- severity: none, low, medium or high — how much harm or urgency the message carries.
- confidence: a number from 0.0 to 1.0 for how sure you are of the category.

Answer with the JSON object only.
```

Validated in research probe 4 against `gemma4:e2b-it-qat` with reasoning off: 12/12 clear synthetic fixtures
correct, identical on repeat, `finish_reason = stop` in every call.

---

## §2a — The second instruction — `classify_v2` *(amendment 2026-10-01, opt-in)*

`app/prompts/moderation/classify_v2.md`, byte for byte, pinned by the same test as §2 (D-TG-162). Same schema,
same seven categories, same four values: `taxonomy_version` stays `1`. It differs from §2 in four ways:
- it states the group's rule;
- it says to judge a message by what it is for, not by its greeting;
- it defines CHITCHAT by purpose rather than by surface;
- it spells out what an offer looks like without a price, a link or the word "sale".

```text
You classify ONE message posted in a student group of an online exam-preparation course. Students write in Arabic (Modern Standard, Saudi or Egyptian dialect), English, or a mix. The text has been normalised (for example ة is written ه and أ is written ا). Personal details were replaced before you see the message: «رابط» is a link, «رقم» is a phone number or long number, «بريد» is an email address, «مستخدم» is a username.

The group's rule: it is only for this course. Members may not advertise, sell or promote anything from outside it, paid or free, and may not ask others to contact them or anyone else outside the group to get something.

Judge what the whole message is for, not how it opens: a greeting, a welcome, emoji or a prayer around an offer does not make it chitchat.

Choose exactly one category:
- QUESTION_COURSE: a question about the course itself — lecture times, links, content, materials, exams.
- QUESTION_ACCESS: a problem reaching what was paid for — payment made but the course or book is not showing, cannot log in, cannot open something.
- COMPLAINT: dissatisfaction or criticism of the course, the service or the team.
- CHITCHAT: a message that is only social — greetings, thanks, congratulations, prayers, emoji — with nothing offered or promoted.
- SPAM_OR_AD: offering, selling or promoting anything from outside the course, with or without a price, a link or the word sale: other courses, classes or tutors; files, summaries, collections, designs or other study material; services of any kind, including medical excuses, sick notes, sick leave and reports; another group or channel on Telegram, WhatsApp or elsewhere; surveys or outside projects asking for participation; investment, trading, income or money offers; or asking readers to contact someone privately, on WhatsApp, at «رقم», «مستخدم» or «رابط» to get something. A question asking whether anyone has a file or summary is a question, not SPAM_OR_AD.
- ABUSE: insults, harassment, threats or inappropriate content.
- OTHER: none of the above.

Then decide:
- needs_response: true only if the writer asks a question or reports a problem that a moderator should answer. Always false for SPAM_OR_AD, ABUSE and CHITCHAT.
- needs_moderation: true if a moderator should act against the message itself — always for SPAM_OR_AD and ABUSE, and for any other message that breaks the group's rule. False for an ordinary question, complaint, greeting or comment.
- severity: none, low, medium or high — how much harm or urgency the message carries.
- confidence: a number from 0.0 to 1.0 for how sure you are of the category.

Answer with the JSON object only.
```

**Which one is sent.** `MODERATION_PROMPT_VERSION` names it: `classify_v1` (the default) or `classify_v2`. It is
validated at startup against the pinned files, and nothing else is accepted (D-TG-163). The classifier, the
catch-up command and the smoke test all read the same setting. A switch takes effect on the next classification
and revisits nothing: each prediction keeps the version it was made with, and every figure is grouped by it
(`classification-metrics.md` K3).

Measured in research probe 11 on 89 labelled messages, against the operator's 12 moderator-removed real messages
plus 77 synthetic. The figures count fixtures whose needs-moderation came back wrong:

| Instruction | Missed violations | False alarms |
|---|---|---|
| `classify_v1` | 11 | 0 |
| `classify_v2` | 1 | 0 |

On the 12 real messages alone: 9/12 → 12/12 on needs-moderation, and 9/12 → 11/12 on the exact pair.

---

## §3 — Eligibility

A pure function in `app/domain/moderation/classification.py` over the message's stored facts and its captured
event's body. First match wins (D-TG-137):

| # | Reason | Condition |
|---|---|---|
| E1 | `text_removed` | the message's text, or its captured event's payload, has been removed by retention |
| E2 | `service` | `is_service` |
| E3 | `media` | `media_kind` is set — including a caption on media; captions are later work |
| E4 | `no_text` | the captured event has no `text`, or it is blank after normalisation |
| E5 | `moderator` | `is_from_moderator` — written once at insert by TG-M2, never recomputed |
| E6 | `group_itself` | `sender_chat_id` equals the group's own platform chat id (an anonymous administrator) |
| E7 | `linked_channel` | the captured event has `is_automatic_forward: true` — the group's linked channel speaking (D-TG-139) |
| E8 | `acknowledgement` | `is_acknowledgement(text)` — **TG-M3's own stoplist matcher**, the one the rule set uses |
| — | *eligible* | none of the above — including a bot account's message and another channel's message (FR-003) |

- **E9.** An excluded message gets one `excluded` row with its reason (`ON CONFLICT DO NOTHING`), and nothing
  is sent to the model.
- **E10.** Unmeasured groups never reach here: their messages are never derived (TG-M2).

---

## §4 — The model's input

- **P1.** The text is re-extracted from the message's **own captured event** — `telegram_updates.payload` at
  `source_update_id` — through `messages.extract_text` and `normalize`, the functions message derivation uses.
  The stored, possibly edited, words are never read (FR-006, Finding 5).
- **P2.** `redact()` then replaces phone numbers and long digit runs, email addresses, links and handles with
  `«رقم»`, `«بريد»`, `«رابط»`, `«مستخدم»` — **before** anything reaches the gateway (FR-008).
- **P3.** The request is exactly two messages: `system` = the configured instruction's text (§2, or §2a when
  `MODERATION_PROMPT_VERSION = classify_v2`); `user` = the redacted text. No sender,
  name, handle, platform identifier, group, title, course, time, entity flag or neighbouring message (FR-007).
- **P4.** `StructuredRequest(schema_model=MessageClassificationResult)`, built from types imported from
  `app.application.gateway` (D-TG-132). The profile's params supply the budget, temperature and
  `reasoning_effort` — the request overrides none of them.
- **P5.** The redacted text exists only in memory for the duration of the call. It is never logged, never
  stored by this domain, and reaches `model_runs` only if `GATEWAY_CAPTURE_PAYLOADS` is on — already redacted.

```python
class MessageClassificationResult(BaseModel):
    category: Literal["QUESTION_COURSE", "QUESTION_ACCESS", "COMPLAINT",
                      "CHITCHAT", "SPAM_OR_AD", "ABUSE", "OTHER"]
    needs_response: bool
    needs_moderation: bool
    severity: Literal["none", "low", "medium", "high"]
    confidence: float          # no schema bounds — range-checked in O3
```

---

## §5 — The call and the prediction

- **O1.** The classifier's gateway is constructed per task with `max_retries=0` and M1's lane, breaker and
  accounting wired from `Settings` (D-TG-134). One gateway call is one attempt.
- **O2.** `generate_structured(req, role="moderation")`. The lane is `llm` (D-TG-131).
- **O3.** An accepted answer must have `0 ≤ confidence ≤ 1`; otherwise the task records the failure
  `confidence_out_of_range` and stores nothing (FR-012). Never clamped.
- **O4.** The confidence is quantised to three places, half-up, and **that** value is routed and stored
  (D-TG-135).
- **O5.** The prediction row records: the message, `model_profile_id` (the profile the gateway resolved),
  `model_run_id` (from the response; NULL only if M1's accounting write failed), `prompt_version` = the
  configured instruction's stem (`"classify_v1"` by default, §2a), `taxonomy_version = 1`, the five values exactly as returned (an inconsistent combination
  included — FR-014), `path`, `route`, `route_reason`, the thresholds in force (live path), and `created_at`.
- **O6.** No prediction is ever updated or deleted (FR-015). No prediction stores text (FR-016).

---

## §6 — Routing

The only definition: `route_prediction(prediction, floor, threshold, path)` in
`app/domain/moderation/classification.py`, pure. Evaluated top to bottom, first match wins (D-TG-142):

| # | When | `route` | `route_reason` |
|---|---|---|---|
| R1 | `path = catch_up` | `measurement_only` | — |
| R2 | confidence < floor | `review` | — |
| R3 | the prediction is **inconsistent** (R8) | `possible_violation` | `inconsistent` |
| R4 | needs no moderation | `none` | — |
| R5 | confidence ≥ threshold | `incident` | — |
| R6 | otherwise | `possible_violation` | `uncertain` |

- **R7.** The floor and threshold are `MODERATION_CONFIDENCE_FLOOR` (0.60) and `MODERATION_INCIDENT_CONFIDENCE`
  (0.85), validated `0 ≤ floor ≤ threshold ≤ 1`, blank = default (D-TG-143). Both are stored on the prediction;
  changing either later revisits nothing (FR-017, SC-009).
- **R8.** **Consistent** means: *needs moderation* with category `SPAM_OR_AD`, `ABUSE` or `OTHER` **and** severity
  other than `none`; **or** *needs no moderation* with a category other than `SPAM_OR_AD` and `ABUSE`
  (D-TG-141). Everything else is inconsistent.
- **R9.** Exactly at the floor is not below it (R2); exactly at the threshold opens (R5).
- **R10.** `review` means *awaiting TG-M8's review queue*: nothing opens, nothing is listed, nothing alerts
  (FR-030).
- **R11.** `possible_violation` means *listed, while the message anchors no incident* (FR-031, FR-042) —
  membership is read at display time (`classification-metrics.md` C4), never stored.
- **R12.** `incident` means *open one now* (§7). If the message already anchors an incident — an operator got
  there first — nothing opens and the prediction is shown beside the operator's labels (FR-038). That outcome
  is observable, not stored: the anchor's incident does not cite this prediction.
- **R13.** The route never touches a question item. The model's needs-response judgement is measured, never
  acted on (FR-032, the second clarification).

---

## §7 — Opening an incident

- **A1.** In **one transaction**: insert the prediction (`ON CONFLICT (telegram_chat_id, telegram_message_id)
  WHERE is_current DO NOTHING`); if a row was inserted and its route is `incident`, call
  `incidents.insert_incident(session, …)` — the same insert `open_incident` uses — then commit (D-TG-153).
  Neither the prediction nor the incident can exist without the other having been decided.
- **A2.** The incident: `source = 'ai'`, `opened_by_user_id` NULL, `message_classification_id` = the
  prediction, `category` and `severity` = the prediction's, `opened_at` = the message's `sent_at`, `detected_at`
  = the database's `now()`, `responsible_moderator_id` = `responsible_at(chat, detected_at)` — TG-M4's I3 and
  I5 unchanged (FR-035, FR-036).
- **A3.** `ON CONFLICT ON CONSTRAINT uq_incident_anchor DO NOTHING`: an existing incident, in any state, wins
  (TG-M4 I2).
- **A4.** Nothing else is written or evaluated. The incident's state is TG-M4's view over evidence already
  recorded — so a sender banned before the model flagged the message opens resolved, "acted before flagging"
  (TG-M4 I6).
- **A5.** No alert, no message, no bot act (FR-040).
- **A6.** Log line: `incident opened`, `extra={"incident_id": …, "message_id": …}` — never text (FR-010).

---

## §8 — Failure and retry

- **F1.** First step of every task: resolve the `moderation` profile. `NoActiveProfileError` → the task ends
  and **records nothing** (FR-025, D-TG-152).
- **F2.** Transient — `ProviderUnreachableError`, `ModelTimeoutError`, `CircuitOpenError`: if `attempt <
  MODERATION_CLASSIFY_MAX_ATTEMPTS` (5), the task re-sends itself with `attempt + 1` and a delay of
  `MODERATION_CLASSIFY_RETRY_BASE_S × 2^(attempt−1)` (30 s, 60 s, 120 s, 240 s), and records nothing yet
  (D-TG-151).
- **F3.** Final — the last transient attempt, or `ModelTruncatedError`, `StructuredOutputInvalidError`,
  `confidence_out_of_range`, `ModelNotAvailableError`, `ProviderRejectedError`, `ProviderAuthError`: one
  `failed` row with the kind (the gateway error's `category`) and the profile. Never retried automatically;
  never labelled (FR-023, FR-024).
- **F4.** A failed message stays eligible for the catch-up command (§10), which would classify it as
  measurement only.
- **F5.** Any non-gateway exception (a database outage, a bug) propagates to Dramatiq's own `max_retries=3`,
  like every actor in the domain.
- **F6.** The model being slow, absent or broken changes nothing outside this pipeline: every question item and
  every incident lifecycle behaves exactly as with no classification model at all (FR-022, US3).

---

## §9 — Idempotency and concurrency

- **I1.** A message with a current prediction is never sent to the model again, by either path (FR-005): the
  task checks first, and `uq_classification_current` is the backstop.
- **I2.** A message with an exclusion is never re-judged; `uq_attempt_exclusion` is the backstop.
- **I3.** A per-message claim — `SET ai:mod:classify:msg:<chat pk>:<message id> <token> NX PX
  <(GATEWAY_CALL_TIMEOUT_S + 30) × 1000>`, released by an owner-checked delete — is held from the check in I1
  to the commit in A1. A task that cannot take it ends: someone else is classifying that message (D-TG-150,
  SC-007).
- **I4.** Interpreting the same captured event any number of times yields at most one prediction, one
  successful model call, and at most one incident.

---

## §10 — The operator's commands

- **C1.** `python -m app.scripts.classify_chat --chat <platform chat id> [--since YYYY-MM-DD] [--until
  YYYY-MM-DD]`: refuses an unmeasured chat; walks the chat's messages in `sent_at` order that have neither a
  current prediction nor an exclusion; runs each through the **same** classification function as the actor,
  with `path = "catch_up"`; prints `classified=<n> excluded=<reason:n,…> failed=<kind:n,…>`. Transient failures
  are recorded as failures, not re-scheduled — the operator re-runs the command (D-TG-160).
- **C2.** Every catch-up prediction is `measurement_only` (R1, `ck_classification_route_path`): it opens no
  incident and is never listed (FR-062).
- **C3.** A second run over the same window classifies nothing (SC-011).
- **C4.** `FIXTURES=<path> make smoke-moderation [ARGS="--profile <name>"]` reads JSONL from standard input —
  `{"text", "category", "needs_moderation"}` per line — normalises and redacts each text exactly as §4 does,
  classifies it through the real gateway, prints expected against predicted, and exits non-zero on any
  mismatch. Without `FIXTURES`, the shipped synthetic set is used. `--profile` pins a named profile, active or
  not (D-TG-161). `--prompt classify_v1|classify_v2` sends that instruction instead of the configured one
  (D-TG-163). Each line also shows the fixture's line number and the route the live path would take,
  computed by `route_prediction` at the configured thresholds (N7). The summary keeps the "n/total matched" line
  and adds:
  - category exact;
  - needs-moderation agreed;
  - false negatives (labelled as needing moderation, predicted not) and false positives, each with line
    numbers;
  - a route tally for violations and for legitimate fixtures (D-TG-162).

  `app/scripts/moderation_smoke_policy_fixtures.jsonl` is a second, synthetic regression set: 64 policy
  cases and near-misses, with no real student text. It writes no prediction and prints no text.
- **C5.** Neither command is reachable from a screen.

---

## §11 — What may never happen

- **N1.** A prediction opening, dismissing, closing, expiring or altering a question item.
- **N2.** A prediction acknowledging, resolving or closing an incident, or counting as evidence.
- **N3.** An `UPDATE` or `DELETE` on `message_classifications`, or a prediction rewritten "to be consistent".
- **N4.** An incident opened from a catch-up prediction, from a prediction below the threshold, or from an
  inconsistent one.
- **N5.** Unredacted text reaching the gateway; any identity, group or time reaching the model.
- **N6.** Message text — original, normalised or redacted — or the model's raw output in any log line or any
  table of this domain. Correlation keys: `message_id`, `incident_id`, `chat_id`, `update_id` — never
  `message` (D-TG-24).
- **N7.** A second definition of eligibility (§3) or routing (§6) — in PHP, in SQL, or in a test helper that
  computes an expected route instead of calling the function.
- **N8.** A clamped, repaired, defaulted or partial prediction.
- **N9.** An outbound message, an alert or a bot act of any kind.
- **N10.** A moderation module importing `httpx`, `ollama`, `openai` or `app.providers.llm` — the gateway is
  the only way to the model.
