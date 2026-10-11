# Feature Specification: TG-M5 — AI Classification

**Feature Branch**: `m5/ai-classification` *(operator-created; see Principle IV)*
**Spec Directory**: `specs/008-tg-m5-ai-classification`
**Created**: 2026-09-27
**Status**: Draft
**Milestone**: TG-M5 (sixth milestone of `docs/plan/telegram/telegram-moderation-intelligence.md` §25)
**Input**: User description: "read docs/plan/telegram/telegram-moderation-intelligence.md and check the docs/runbooks/tg-operator-prere quisites.md, the start specify Milestone number 5 "AI classification""

## Overview

TG-M3 and TG-M4 measured moderation with no model at all, and that was the point: a hand-written rule set
decided which messages deserved an answer, operators flagged violations by hand, and every one of their
corrections — a dismissed question, a question added that the rules missed, an incident opened with a
category and a severity, a flag closed as a false positive — was stored as a human act. Those rows are a
labelled record of what people in these groups actually say and what the moderation team judged it to be.
TG-M5 is the first milestone that puts a model in front of that record.

A local model reads each eligible message and proposes five things about it: which of seven kinds of
message it is, whether it needs an answer, whether it needs a moderator to act, how serious it is, and how
confident the model says it is. That proposal is a **claim**, made by a named model under a named
instruction and a named version of the vocabulary — and it is kept as exactly that. It is recorded once,
with its full provenance, and never edited, corrected in place, or overwritten. The confidence is the
model's own self-report; it is used to decide what happens next, and it is never shown or treated as a
probability.

The milestone is built around one discipline the whole domain has kept so far: **a probabilistic input is
added only where it can be measured, and only as far as it has been.** The model has an obvious advantage
over the rules — it can see intent in dialect Arabic that no pattern list anticipates — and an obvious risk:
a small local model, wrong in public, turns into a false accusation in someone's figures. So the milestone
lets the model act in exactly one place — opening an incident when it is confident and coherent — keeps it
out of everything else, and measures it against the humans' labels from its first prediction.

Seven things ship:

1. **Eligible messages are classified as they arrive, off the tracking path.** Service announcements,
   moderators' own messages, messages with no words, and bare thanks or emoji never reach the model. A slow,
   busy or absent model never delays capture, question tracking, evidence or the incident lifecycle.
2. **The model sees the words, never the person.** It is given only the normalised text of one message,
   with phone numbers, email addresses, links and handles replaced by fixed placeholders — no sender, no
   group, no name, no identifier, no time. The redaction happens before the text reaches the shared model
   layer, so no record that layer keeps can ever hold unredacted text.
3. **Every prediction is immutable and fully provenanced.** Which model, which instruction version, which
   vocabulary version, which call, what confidence, when, and what the system then decided to do with it.
   An output that is cut off, malformed or out of range produces no prediction at all — never a partial,
   repaired or defaulted one.
4. **A confident violation opens an incident on its own**, through exactly the opening step an operator's
   flag uses: dated from the platform's posting time and from the moment the model flagged it, attributed to
   the group's owner at that moment, opening directly into whatever state the evidence already recorded
   implies. The model's own delay is the system's detection latency and is never charged to a moderator.
   It fires no alert and sends nothing — alerts are TG-M6.
5. **An uncertain violation waits for a person instead of accusing anyone.** It opens no incident; it is
   listed as a *possible violation*, and an operator who agrees flags the message by hand with TG-M4's
   existing action. That flag is the operator's — with the operator's labels — and is recorded as prompted by
   the list, so the comparison never mistakes a suggestion taken for an independent agreement.
6. **The model is measured against the humans before it is trusted further.** Its judgement of whether a
   message needs an answer is **measured only**: the rule set stays the sole automatic opener of question
   items, and the model's judgement is compared with it against every human label already recorded —
   dismissed and hand-added questions, hand-opened incidents and their categories, false-positive closures —
   never pooled across models or instruction versions, every ratio shown with its counts, reproducible by
   hand. Letting the model do more is a later decision, taken on this evidence.
7. **Why a label was given is visible where the work is done.** The waiting-question queue and the incident
   screens show the model's label, its self-reported confidence, and — on the detail — the model, the
   instruction version and the vocabulary version. The classification model is chosen in the existing model
   roster, independently of the assessment model, and switching one never moves the other.

TG-M5 still **sends nothing and does nothing in any group.** No alert fires, the bot never bans, restricts,
deletes, reacts or posts, and the model never changes the state of any question or incident it did not
open — a prediction is never evidence. Every TG-M3 figure is exactly as it was. Both silence guarantees from
TG-M1 continue to hold and continue to be tested. Every automated test runs with the model scripted, no
model runtime, no platform credential and no network. The model runtime is needed only for the operator's
smoke test.

## Clarifications

### Session 2026-09-27

- Q: A prediction that a message needs moderation, with confidence at or above the floor (0.60) but below the incident threshold (0.85) — the source plan's §14.1 sends it to review and alerts nobody, while §15.6 opens a low-confidence incident with severity capped at medium. Which? → A: **No incident. It is listed as a possible violation**, on a read-only list from which an operator can flag the message by hand with TG-M4's existing opening action. The resulting incident is operator-opened with operator-chosen labels, and is recorded as prompted by the list so the comparison reports it apart from independent flags. An internally inconsistent prediction at or above the floor goes to the same list; a prediction below the floor is recorded as awaiting TG-M8's review queue and listed nowhere. Rationale: §14.1's principle — a low-confidence false accusation is worse than a delay — is kept, and the band where a small model's dialect mistakes concentrate never enters a moderator's figures on the model's word alone; yet nothing the model noticed is invisible for two milestones. Opening a low-confidence incident was rejected because every mistake would count against a moderator until someone closed it; recording without a list was rejected because a 0.84 advert would sit unseen until TG-M8.
- Q: What does the model's judgement of whether a message needs an answer do in this milestone? → A: **Measurement only.** The rule set remains the only automatic opener of question items; the model's judgement is recorded on every classified message and compared with the rule set against the operators' dismissals and hand-added questions, side by side with the rule set's own precision and recall. The model opens, dismisses, closes and expires no question item. Rationale: TG-M3 was built so that replacing the rules would be "an experiment with a baseline, not an act of faith", and this is the experiment; every TG-M3 figure stays exactly as it was, so the baseline is not disturbed while it is being compared against; and response tracking never comes to depend on the model being up. Letting the model open questions the rules missed was rejected for now because the model's precision on questions is unmeasured; replacing the rules was rejected because it would make tracking depend on the model runtime. Either becomes a decision taken on the evidence this milestone produces.

> **Amended by TG-M5.1 (2026-10-03).** The decision was taken on that evidence, for **live** predictions: one recorded at or after `MODERATION_AI_ATTENTION_FROM` may open a question item **the rule set declined**, through TG-M3's own `open_item`, on the anchor, clock and owner a rule-opened item would have — `specs/009-tg-m5-1-ai-attention/` (D-TG-164…D-TG-171). The rule set still has the first word; catch-up stays measurement only; with the switch blank, this clarification holds exactly as written.

### Session 2026-10-01

Raised by the end-to-end manual test: real adverts that moderators had removed were classified as needing no
moderation at confidence 0.90–1.00 (research §6, Finding 7).

- Q: `classify_v1` misses adverts wrapped in a greeting or emoji, and services offered through a private
  contact, so they never reach a moderator. A new instruction catches them. How does it reach live
  classification? → A: **As an opt-in second version, `classify_v2`, chosen by `MODERATION_PROMPT_VERSION`
  (default `classify_v1`).** `classify_v1` is not touched. Every prediction records the version it was made
  with, and every figure keeps the versions apart (metrics K3), so a switch revisits nothing. The operator
  smokes `classify_v2` against their own labelled messages, then switches. Rationale: FR-009 already requires a
  versioned instruction, and the operator decides when a new one is trusted, as with a model profile. Making
  `classify_v2` the only instruction was rejected because a rollback would need a code change. Changing the
  thresholds was rejected because confidence does not separate right from wrong (Finding 2): the wrong answers
  came back at 0.80–1.00.
- Q: The group allows no links from students, only from admins. Does TG-M5 enforce that? → A: **No.** It is a
  deterministic rule, not a judgement, and it does not belong in a model's instruction. A rule-opened incident
  needs an incident source TG-M4 does not have (`source = 'rule'`), a new revision and a policy on mentions,
  captions, forwards and admins. It is deferred to its own milestone (Out of Scope). Nothing in this milestone
  changes for it: whichever incident on a message opens first wins (pipeline A3, R12).
- Q: The smoke test's "n/total matched" counted an adjacent category the same as a violation the model let
  through. What does it report? → A: **Category agreement, needs-moderation agreement, missed violations and
  false alarms, each with its fixture line numbers, and the live route each fixture would take**
  (pipeline C4). The "n/total matched" line and the non-zero exit on any mismatch are kept.

### Session 2026-10-03 (TG-M5.1)

- Recorded in `specs/009-tg-m5-1-ai-attention/spec.md` → Clarifications: dual-purpose predictions open both units; a late prediction that would be born expired opens nothing; an edited member's first-posted prediction counts on E3's clock; the switch is the dated `MODERATION_AI_ATTENTION_FROM`.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - An eligible message is classified by the local model, and the prediction is kept with its full provenance and nothing else (Priority: P1)

A student posts «الكتاب مش ظاهر عندي» in a measured group. Moments later the message carries a prediction:
an access question, needs a response, needs no moderation, medium severity, confidence 0.91 — recorded with
the classification model that produced it, the instruction version and vocabulary version it was produced
under, the model call it came from, and when. Nothing about the message itself is copied into the
prediction. The prediction is never edited again.

**Why this priority**: Every other story consumes predictions. And provenance is not decoration: when a
label turns out to be wrong, "which model said this, under which instruction?" must have an answer, or
nothing about the model can ever be improved or defended.

**Independent Test**: With the model scripted and a controlled clock, record messages of every kind —
ordinary student text, a moderator's message, a service announcement, a photo with no words, a bare «شكرا»,
a message from a bot account, a message sent on behalf of another channel, a message sent on behalf of the
group itself — and confirm which reach the model, what each prediction records, and that interpreting the
same message again produces no second prediction and no second model call.

**Acceptance Scenarios**:

1. **Given** a text message from a non-moderator in a measured group, **When** it is recorded, **Then** it is
   classified without waiting for the question settle window, and exactly one prediction exists for it,
   carrying category, needs-response, needs-moderation, severity, confidence, the classification model, the
   instruction version, the vocabulary version, a reference to the model call and the moment it was made.
2. **Given** a service announcement, a message from someone recorded as a moderator when they sent it, a
   message with no text, a message sent on behalf of the group itself, or a message consisting only of
   acknowledgement words or emoji, **When** it is recorded, **Then** it is not sent to the model, and the reason
   it was excluded is recorded.
3. **Given** a message from a bot account, or one sent on behalf of a channel other than the group, **When** it
   is recorded, **Then** it is classified like any other eligible message.
4. **Given** a message that already has a prediction, **When** it is interpreted again — after a restart, a
   retry or a re-derivation — **Then** no second prediction and no second model call result.
5. **Given** a recorded prediction, **When** anything later happens to the message, its question item or its
   incident, **Then** the prediction is unchanged.
6. **Given** a model output whose confidence is above 1 or below 0, or whose category or severity is not in
   the vocabulary, **When** it is returned, **Then** no prediction is recorded and the message is counted as a
   failed classification with that failure kind.
7. **Given** a model output cut off before it finished, or not well-formed, **When** it is returned, **Then** no
   prediction — partial, repaired or defaulted — is recorded, and the message is counted as failed.
8. **Given** a prediction that contradicts itself — chit-chat that needs moderation, or a violation whose
   severity is none — **When** it is recorded, **Then** it is recorded exactly as returned.

---

### User Story 2 - What the model sees is the words, never the person (Priority: P2)

A student posts «رقمي 0551234567 وايميلي ahmad@example.com، شوفوا @ahmad_s و https://example.com». The model
receives «رقمي «رقم» وايميلي «بريد»، شوفوا «مستخدم» و «رابط»» — and nothing else: not who sent it, not the
group, not the group's title, not the course, not the time. Nothing the shared model layer records — its
call accounting, or its optional debugging capture if it is ever switched on — can contain the original.

**Why this priority**: The model does not need to know who asked, only what kind of thing was said. Keeping
identity out is what makes classification compatible with the domain's retention promise, and redacting
before the model layer rather than after it is what stops a debugging switch from becoming a privacy
regression.

**Independent Test**: Classify fixtures containing phone numbers in Latin, Arabic-Indic and Eastern digits,
email addresses, links with and without a scheme, and handles, with the model layer's debugging capture
switched on in the test, and inspect everything the scripted model received and everything the model layer
stored.

**Acceptance Scenarios**:

1. **Given** a message containing a phone number or long digit run, an email address, a link or a handle,
   **When** it is classified, **Then** each is replaced by its fixed placeholder before the text reaches the
   shared model layer, and the rest of the text — including Latin words mixed into Arabic — is intact.
2. **Given** any classified message, **When** the input given to the model is inspected, **Then** it contains
   the redacted message text and the versioned instruction, and no sender, name, handle, platform identifier,
   group, group title, course or timestamp.
3. **Given** the model layer's debugging capture switched on, **When** a message is classified, **Then** the
   captured request contains only redacted text.
4. **Given** any classification, successful or failed, **When** the logs are inspected, **Then** no log line
   contains the message text, redacted or not, or the model's raw output.
5. **Given** any prediction record, **When** it is inspected, **Then** it contains no message text.

---

### User Story 3 - When the model is slow, broken or absent, nothing the team already relies on changes (Priority: P3)

The model runtime is stopped for an afternoon. Students keep asking, moderators keep answering, spammers keep
getting banned. Every question item opens and closes exactly as it did in TG-M3; every incident an operator
flags moves through its lifecycle exactly as it did in TG-M4. When the runtime comes back, the messages that
were waiting are classified, once each.

**Why this priority**: The source plan names this as the milestone's acceptance: the model being down must
not stop response tracking. The deterministic spine is what the figures rest on; the model is an addition to
it, never a dependency of it.

**Independent Test**: Script the model as unreachable, then slow, then returning malformed output, while
questions, answers, reactions and bans flow; compare every question item, incident and figure with the same
traffic processed with no classification model configured at all.

**Acceptance Scenarios**:

1. **Given** the model runtime unreachable, **When** questions are asked and answered, **Then** every question
   item opens, closes and is timed identically to the same traffic with no classification model configured.
2. **Given** a transient model failure, **When** a classification is attempted, **Then** it is retried with
   increasing delay a bounded number of times, and succeeds or is recorded as failed — never dropped
   silently.
3. **Given** an output that is cut off or malformed, **When** it is returned, **Then** it is not retried
   automatically, because the same instruction to the same model would fail the same way.
4. **Given** a long queue of messages waiting for the model, **When** new updates arrive, **Then** their capture,
   message records, question tracking and evidence are not delayed by the queue.
5. **Given** no classification model active, **When** messages arrive, **Then** nothing is classified and every
   behaviour is exactly as TG-M4 shipped.
6. **Given** the runtime returns after an outage, **When** the waiting messages are processed, **Then** each is
   classified once, in the order it was posted.

---

### User Story 4 - A confident violation opens an incident on its own, dated twice and charged to nobody for the model's delay (Priority: P4)

A competitor's advert is posted at 10:03:10. The model classifies it at 10:03:14 as spam or advert, needs
moderation, high severity, confidence 0.93. An incident opens on that message with no operator involved: its
posting moment is 10:03:10, its detection moment 10:03:14, its opener is recorded as the model and the
prediction that opened it is linked, its category and severity are the model's, and its responsible
moderator is whoever owned the group at 10:03:14. From there it is an incident like any other: a moderator's
✅ acknowledges it, restricting the sender resolves it, and an operator can close it as a false positive.

**Why this priority**: This is the plan's stated purpose for the milestone on the violation side, and the
first behaviour anywhere in the domain that a model initiates. It is deliberately the only one.

**Independent Test**: With a controlled clock and a scripted model, produce moderation predictions across the
confidence range and every consistency combination, some on messages that already anchor an incident, some
whose sender was already banned, some in a group with no owner; confirm exactly which open an incident and
what each incident records.

**Acceptance Scenarios**:

1. **Given** a prediction that needs moderation, with confidence at or above the incident threshold, a
   category of spam or advert, abuse or other, and a severity other than none, **When** it is recorded by the
   live path, **Then** exactly one incident opens on its message, marked as opened by the model, linked to that
   prediction, with no panel account, the message's platform timestamp as its posting moment, the moment it
   was opened as its detection moment, and the prediction's category and severity.
2. **Given** a prediction at exactly the incident threshold, **When** it is routed, **Then** it opens an
   incident.
3. **Given** a prediction that needs moderation with high confidence but a question, complaint or chit-chat
   category, or a severity of none, **When** it is routed, **Then** no incident opens automatically and the
   message is listed as a possible violation.
4. **Given** a message an operator has already flagged, **When** the model's confident prediction arrives,
   **Then** no second incident exists, the operator's incident keeps its operator-assigned labels and opener,
   and the model's prediction is shown beside them.
5. **Given** a sender already banned by a moderator before the model flagged the message, **When** the
   incident opens, **Then** it opens resolved, crediting whoever performed the ban, and the enforcement is
   reported as "acted before flagging" exactly as TG-M4 defined.
6. **Given** a model-opened incident, **When** its responsible moderator is recorded, **Then** it is the
   group's primary owner at the detection moment, or absent and visible as unassigned when there was none.
7. **Given** a model-opened incident, **When** the figures are computed, **Then** the time between posting and
   the model's flag is reported as the system's detection latency, separately for model-opened and
   operator-opened incidents, and appears in no figure attributed to a moderator.
8. **Given** a model-opened incident, **When** an operator closes it as a false positive, **Then** it leaves
   every handled, missed and timing figure exactly as TG-M4 defined, and counts as one of the model's
   recorded mistakes.
9. **Given** a model-opened incident, **When** it opens, **Then** no alert fires and nothing is sent anywhere.
10. **Given** the incident threshold is changed afterwards, **When** the history is inspected, **Then** no past
    routing decision, incident or figure has changed.

---

### User Story 5 - An uncertain violation is listed for a person instead of accusing anyone (Priority: P5)

The model says an Egyptian-dialect message is probably an advert, confidence 0.72. That is not enough to put
an incident in anyone's figures. No incident opens. The message appears on a read-only list of *possible
violations* — the message, its group, when it was posted, the model's category, severity and self-reported
confidence, and why it is there rather than an incident. The operator reads it, agrees, and flags the message
with TG-M4's ordinary opening action, choosing the category and severity themselves. The incident is theirs,
and it is recorded as having been prompted by the list. The entry leaves the list. A prediction below the
floor — 0.41 — opens nothing, is listed nowhere, and is recorded as awaiting the review queue TG-M8 builds.

**Why this priority**: The source plan's own words: a low-confidence false accusation is worse than a delay.
The model's self-reported confidence is weakly calibrated, the model is small, and dialect is exactly where it
is weakest — so the band between "probably" and "confident" is where most of its mistakes will live. The list
keeps those mistakes out of everyone's figures without hiding what the model noticed.

**Independent Test**: Route predictions below the floor, exactly at the floor, inside the band, just below the
threshold, and internally inconsistent predictions at every level; confirm the recorded routing decision, that
none opens an incident, that none alerts anyone, which appear on the list, and that flagging from the list
produces an operator-opened incident recorded as list-prompted.

**Acceptance Scenarios**:

1. **Given** a moderation prediction with confidence below the floor, **When** it is routed, **Then** no incident
   opens, nothing alerts, it is not listed as a possible violation, and it is recorded as awaiting review.
2. **Given** a prediction that needs moderation with confidence at or above the floor and below the incident
   threshold, **When** it is routed, **Then** no incident opens, it is recorded as a possible violation, and its
   message appears on the possible-violations list.
3. **Given** an internally inconsistent moderation prediction at or above the floor, **When** it is routed,
   **Then** no incident opens and its message appears on the possible-violations list, marked as inconsistent.
4. **Given** a message on the list, **When** an operator flags it, **Then** an incident opens exactly as any
   operator flag does — operator-opened, with the operator's own category and severity, detected when the
   operator flagged it — it is recorded as prompted by the possible-violations list, and the entry leaves the
   list.
5. **Given** a message on the list that an operator flags directly elsewhere, **When** the list is next loaded,
   **Then** the entry is gone, and the incident is recorded as an independent flag.
6. **Given** the possible-violations list, **When** the operator looks for a control to dismiss an entry, change
   its label, or act on several entries at once, **Then** there is none; filtering by group and by posting period
   is available.
7. **Given** any routed prediction, **When** it is inspected, **Then** it records what the system did with it and
   the floor and threshold in force when it decided.

---

### User Story 6 - The model is measured against the humans' labels before it is trusted with more (Priority: P6)

The operator opens the classification figures for the pilot group and the last two weeks. Beside the rule
set's own precision and recall from TG-M3, they see, for the active model and instruction version: of the
questions the rules opened and nobody dismissed, how many the model also said needed an answer; of the ones
operators dismissed, how many the model would have wrongly flagged; of the questions operators added by hand
because the rules missed them, how many the model caught. On the violation side: of the incidents operators
flagged independently, how many the model also said needed moderation, and how often its category agreed with
the operator's; of the flags taken from the possible-violations list, the same, reported apart; of the flags
closed as false positives, how many the model would have raised; and of the incidents the model opened itself,
how many were closed as false positives. Every ratio shows its numerator and denominator.

**Why this priority**: TG-M3 was built so that replacing the rules would be "an experiment with a baseline,
not an act of faith". This is the experiment's read-out. Without it, every later decision to let the model do
more — including opening questions — is an opinion.

**Independent Test**: Load a fixed set of messages carrying human labels of every kind and scripted
predictions from two different models and two instruction versions; compare every figure with hand
computation, and confirm that nothing is pooled across models or versions and that list-prompted flags are
kept apart.

**Acceptance Scenarios**:

1. **Given** labelled questions and scripted predictions, **When** the question-side figures are computed for a
   period and group, **Then** each count matches hand computation, grouped by model, instruction version and
   vocabulary version, and shown beside the rule set's own figures for the same period and group.
2. **Given** operator-flagged incidents — independent and list-prompted — false-positive closures and
   model-opened incidents, **When** the violation-side figures are computed, **Then** each count and each
   agreement matches hand computation, and list-prompted flags are reported apart from independent ones.
3. **Given** predictions from two models, **When** the figures are computed, **Then** each model has its own
   figures and no figure combines them.
4. **Given** any ratio, **When** it is displayed, **Then** its numerator and denominator are shown with it, and
   it is labelled as an estimate over the human labels available, not as a measured accuracy.
5. **Given** messages the model judged as needing an answer where no question item exists and no human label
   exists, **When** the figures are shown, **Then** they are counted separately as unverified, never as correct
   and never as wrong.
6. **Given** the classification figures, **When** the operator looks for an average — of confidence or of
   anything else — or a single combined score, **Then** there is none.

---

### User Story 7 - Why a label was given is visible where the work is done, and the model is chosen deliberately (Priority: P7)

On the Live Attention Queue each waiting question shows the model's label and its self-reported confidence.
On the incident screens, each incident shows whether a person or the model flagged it; the detail shows the
prediction for the message — category, needs-response, needs-moderation, severity, confidence, the model, the
instruction version and the vocabulary version — beside whatever an operator assigned. Where there is no
prediction, the screen says why. In the model roster, the operator sees the active classification model and
can switch it — to a larger model for the classification role alone, say — without touching the assessment
model.

**Why this priority**: A label nobody can see changes nothing about how the team works; a label with no
provenance cannot be argued with fairly. The model choice sits with the operator because it is a cost and
quality trade-off the operator owns.

**Independent Test**: Seed messages with predictions, without predictions for each reason, and incidents of
both origins; load the queue, list and detail and confirm what each shows. Switch the active classification
model and confirm the active assessment model is unchanged, and the reverse.

**Acceptance Scenarios**:

1. **Given** a waiting question whose messages have predictions, **When** the Live Attention Queue is loaded,
   **Then** the row shows the model's category and self-reported confidence, labelled as the model's
   self-report rather than a probability, and the question item itself is exactly as the rule set opened it.

   > **Amended by TG-M5.1 (2026-10-03).** …or, for a model-opened item, exactly as TG-M5.1's `open_item` opened it.
2. **Given** a message with no prediction, **When** it is shown, **Then** the screen states why — not eligible
   and which condition, awaiting the model, failed and how, or no classification model active — and never
   leaves the space blank.
3. **Given** incidents opened by operators and by the model, **When** the list is loaded, **Then** it can be
   filtered by how each was opened.
4. **Given** an incident an operator flagged, **When** its detail is opened, **Then** the operator's labels and
   the model's prediction for the same message are both shown and clearly attributed to their authors, and a
   list-prompted flag says so.
5. **Given** the model roster, **When** the operator activates a different classification model, **Then** it
   becomes the only active classification model and the active assessment model is unchanged; **and when**
   the assessment model is switched, **Then** the classification model is unchanged.
6. **Given** the classification screens, **When** the operator looks for a control that calls the model,
   reclassifies a message, acts on many messages at once, posts, bans, restricts, deletes or reacts, **Then**
   there is none.
7. **Given** Arabic message text, **When** it is displayed, **Then** it renders in its own reading direction
   without the surrounding panel changing direction.

---

### Edge Cases

- **A question spread over several messages.** «السلام عليكم» / «أنا مشترك في الدورة» / «ولكن المحاضرة مش
  ظاهرة» is one question to the rules, but three messages to the model, each classified alone. The greeting
  alone is chit-chat; the last message alone is an access question. The question side of the comparison
  therefore judges a question item by whether the model said *any* of its messages needed an answer —
  mirroring how the rule set judges a burst.
- **The model thinks a question needs no answer.** The rule-opened question item stays exactly as it is; the
  disagreement is counted in the comparison. The model never dismisses, closes or expires anything.
- **The model thinks a message needs an answer and the rules opened nothing.** No question item opens. The
  message is counted as an unverified model-only judgement; if the operator agrees, they add the question by
  hand with TG-M3's existing action, and it becomes a labelled rule miss the model caught.

  > **Amended by TG-M5.1 (2026-10-03).** With `MODERATION_AI_ATTENTION_FROM` set, a live, qualifying prediction opens the item instead (`source = 'ai'`) — `specs/009-tg-m5-1-ai-attention/`. Blank, this edge case holds as written.
- **The model is slower than the moderator.** The moderator answered before the label landed. The label
  attaches; nothing about the question moves. On the violation side, a spammer banned before the model
  flagged the message produces an incident that opens resolved, with the enforcement counted as "acted before
  flagging".
- **The model runtime was down for two days.** When it returns, the waiting messages are classified, and a
  confident violation among them opens an incident whose detection moment is now. The two days are the
  system's detection latency, visible as such and charged to nobody; the moderator timings start at the flag.
  A message a moderator deleted silently in the meantime will receive no evidence — the certain attribution
  gap the source plan states, unchanged by this milestone and resolved the same way: an operator confirmation
  or a false-positive closure.
- **An uncertain advert sits on the possible-violations list and nobody flags it.** It stays listed while its
  message anchors no incident, and it is in nobody's figures. Recording a human verdict that it was *not* a
  violation is a review act, and belongs to TG-M8's queue; the list's period filter keeps old entries out of
  the way until then.
- **The operator flags a message from the list.** The incident is the operator's, with the operator's labels
  and a detection moment of when they flagged it; the model's earlier notice is visible beside it, but the
  moderator timings start at the operator's flag — the model's notice was never an incident. The flag is
  recorded as list-prompted, so it is never counted as the operator independently agreeing with the model.
- **Labels on screens influence people.** Once operators can see the model's labels on the queue and the
  incidents, their later dismissals and flags are no longer fully independent of the model. The strongest case
  — flagging from the possible-violations list — is recorded and reported apart; the weaker influence is a
  known limitation, written down.
- **A spammer posts something harmless, then edits it into an advert.** The model classified the words as
  first posted; edits are not re-classified in this milestone. Written down as a known limitation; an operator
  can still flag the message by hand.
- **The same advert posted in three groups.** Three messages, three predictions, and — if confident — three
  incidents, each attributed to its own group's owner.
- **A moderator posts the advert themselves** (quoting it, say). Moderators' messages are not classified; if
  it needs an incident, an operator flags it.
- **A message sent on behalf of a channel.** Classified — channel spam is exactly what TG-M4's first finding
  made capturable. If an incident opens, TG-M4's statement that no membership evidence can arrive for such a
  sender applies unchanged.
- **The model returns a confidence of 1.3, or a category nobody defined.** No prediction; a failure of that
  kind is counted. Never clamped to 1.0, never mapped to "other".
- **The model contradicts itself.** Chit-chat that needs moderation, or abuse with severity none. Recorded
  verbatim; opens nothing on its own; listed as a possible violation, marked inconsistent, when its confidence
  is at or above the floor.
- **A message whose text passed its retention window before it was classified.** It cannot be classified —
  there is nothing to send — and is recorded as not eligible for that reason. Reclassification of anything
  older than the retention window is impossible; that is the accepted cost of the retention promise.
- **A prediction from the operator's catch-up command says an old message was spam.** It is recorded and
  counted in the comparison, opens nothing and is not listed: an incident flagged weeks after the fact would be
  dated now and charged to whoever owns the group today.
- **The operator switches the classification model mid-period.** Messages before the switch carry the old
  model's predictions, messages after carry the new one's; the figures show each model separately and never
  blend them. Re-classifying the old messages under the new model is TG-M8's reprocessing.
- **The operator lowers the incident threshold.** Future predictions route under the new value. Past routing
  decisions, and the incidents they opened or did not open, stay as they were decided; a message already on the
  possible-violations list does not turn into an incident.
- **The model says a flagged message is harmless.** An operator flagged it; the model disagrees. Nothing
  changes about the incident. The disagreement is visible on the detail and counted in the comparison.
- **A bare emoji, «شكرا», or «تمام».** Excluded before the model by the same acknowledgement stoplist the rule
  set uses, so the two sides of the comparison agree on what was never a question.
- **A photo or voice note with no words.** Not classified; captions and media are later work.
- **Two workers classify the same message at once.** One prediction results and at most one incident.
- **The same message's prediction arrives after an operator already flagged it.** No second incident, no list
  entry; the prediction is shown beside the operator's labels.
- **The group is promoted to a supergroup.** Predictions belong to messages and follow them, as question items
  and incidents already do.
- **No classification model has ever been activated.** The milestone is inert: nothing is classified, every
  screen says so where a label would be, the possible-violations list is empty, and everything else behaves as
  TG-M4 shipped.

## Requirements *(mandatory)*

### Functional Requirements

#### Which messages are classified

- **FR-001**: The system MUST request a classification for every eligible message in a measured group as soon
  as the message is recorded, without waiting for the question settle window.
- **FR-002**: The system MUST treat a message as eligible only when it has text; is not a service
  announcement; was not sent by a person recorded as a moderator when they sent it; was not sent on behalf of
  the group itself; does not consist solely of acknowledgement words or emoji, as judged by the same stoplist
  the rule set uses; and whose text has not been removed by retention.
- **FR-003**: The system MUST treat messages from bot accounts and messages sent on behalf of a channel other
  than the group as eligible.
- **FR-004**: The system MUST record, for every message it does not send to the model, which eligibility
  condition excluded it, so that the share of traffic reaching the model is reportable by reason.
- **FR-005**: The system MUST classify a message at most once in this milestone: a message that already has a
  prediction MUST NOT be sent to the model again, however many times it is interpreted and by whichever path.
- **FR-006**: The system MUST classify the message's words as first posted, and MUST NOT re-classify a message
  when it is edited in this milestone.

#### What the model is given

- **FR-007**: The system MUST give the model only the message's normalised text, with every phone number or
  long digit run, email address, link and handle replaced by a fixed placeholder, together with the versioned
  instruction — and nothing else about the message: no sender, name, handle, platform identifier, group, group
  title, course, time or neighbouring message.
- **FR-008**: The system MUST redact the text before it reaches the shared model layer, so that no record that
  layer keeps — including its optional debugging capture — can contain unredacted text.
- **FR-009**: The system MUST keep the classification instruction as a versioned template under the platform's
  own control, MUST NOT hold it in any external automation tool, and MUST record its version on every
  prediction.
- **FR-010**: The system MUST NOT write message text — original, normalised or redacted — or the model's raw
  output into any log line, and MUST carry the message's identifier, and the incident's where one opens, as
  correlation identifiers on the log records of classification and routing.

#### The prediction

- **FR-011**: A prediction MUST consist of exactly: one of seven categories — course question, access question,
  complaint, chit-chat, spam or advert, abuse, other; whether the message needs a response; whether it needs
  moderation; a severity — none, low, medium or high; and a confidence between 0 and 1 inclusive.
- **FR-012**: The system MUST record a prediction only from a model output that is complete, well-formed and
  within range in every value; a cut-off, malformed or out-of-range output MUST produce no prediction — never a
  partial, repaired, clamped or defaulted one.
- **FR-013**: The system MUST record on every prediction the message, the classification model that produced
  it, a reference to the model call it came from, the instruction version, the vocabulary version, and the
  moment it was made.
- **FR-014**: The system MUST record a prediction exactly as returned, including internally inconsistent
  combinations, and MUST judge consistency only when routing, never by rewriting the prediction.
- **FR-015**: The system MUST never alter or remove a recorded prediction, and MUST allow at most one current
  prediction per message.
- **FR-016**: The system MUST NOT store message text on any prediction record.
- **FR-017**: The system MUST record on every prediction what the system decided to do with it — opened an
  incident; message already flagged; listed as a possible violation, and whether because uncertain or
  inconsistent; awaiting review; no moderation needed; or recorded for measurement only — together with the
  floor and threshold in force when it decided, and MUST NOT revisit that decision when the thresholds later
  change.

#### Running the model

- **FR-018**: The system MUST use a dedicated classification model role with exactly one active classification
  model at a time, chosen by the operator independently of the assessment generation model; activating a model
  for one role MUST NOT change the active model of the other.
- **FR-019**: The shared model layer MUST let a caller name the role whose active model it wants, and every
  existing caller MUST behave exactly as before without being changed.
- **FR-020**: Classification calls MUST pass through the machine's existing one-generation-at-a-time protection
  and its existing failure protection, and MUST NOT bypass either.
- **FR-021**: The system MUST record every classification call in the existing model call accounting,
  attributable to the classification model, so its volume, latency and failure rate are answerable per model.
- **FR-022**: The system MUST NOT let a backlog or a failure of classification delay or prevent capture, message
  derivation, question tracking, evidence recording or any incident's lifecycle.
- **FR-023**: The system MUST retry a transient model failure — the runtime unreachable, a timeout, the failure
  protection open — with increasing delay a bounded number of times, and MUST NOT automatically retry an output
  that was cut off or malformed.
- **FR-024**: The system MUST record a message whose classification ultimately failed as failed, with the kind
  of failure, MUST make the failed count visible, MUST NOT give it any label, and MUST leave it eligible for the
  operator's catch-up command to try again.
- **FR-025**: The system MUST classify nothing when no classification model is active, and every other
  behaviour MUST then be exactly as TG-M4 shipped.

#### Routing

- **FR-026**: The system MUST use two configurable confidence thresholds: a floor, defaulting to 0.60, and an
  incident threshold, defaulting to 0.85; configuration MUST refuse a value outside 0 to 1 or a floor above the
  threshold, and a blank value MUST mean the default.
- **FR-027**: The system MUST treat a moderation prediction as consistent only when its category is spam or
  advert, abuse or other and its severity is not none.
- **FR-028**: The system MUST open an incident automatically from a prediction only when all hold: it needs
  moderation; it is consistent; its confidence is at or above the incident threshold; it was made by the live
  classification path, not the operator's catch-up command; and the message anchors no incident yet.
- **FR-029**: The system MUST NOT open any incident automatically from a prediction whose confidence is below
  the incident threshold, or that is inconsistent, whatever its confidence.
- **FR-030**: The system MUST NOT open anything, alert anyone, list anywhere or display as an accusation a
  prediction whose confidence is below the floor, and MUST record it as awaiting review.
- **FR-031**: The system MUST record as a possible violation, and open no incident for, a live prediction that
  needs moderation and whose confidence is at or above the floor and below the incident threshold, or that is
  inconsistent and at or above the floor, provided its message anchors no incident.
- **FR-032**: The system MUST treat the model's needs-response judgement as measurement only: the rule set MUST
  remain the only automatic opener of question items, and no prediction MUST open, dismiss, close, expire or
  alter any question item.

  > **Amended by TG-M5.1 (2026-10-03).** A live prediction may now open (never dismiss, close, expire or alter) a question item the rule set declined, while `MODERATION_AI_ATTENTION_FROM` is set — `specs/009-tg-m5-1-ai-attention/`, FR-101…FR-108.
- **FR-033**: The system MUST NOT let any prediction acknowledge, resolve, close or alter an incident; a
  prediction MUST never count as evidence in an incident's lifecycle.

#### Incidents opened by the model

- **FR-034**: The system MUST open a model-initiated incident through the same opening step an operator's flag
  uses — the same one-incident-per-message rule under the same guard, and the same evaluation of evidence
  already recorded — so the two can never disagree.
- **FR-035**: The system MUST record on a model-opened incident that the model opened it, the prediction that
  opened it, no panel account, the message's platform send timestamp as its posting moment, the moment it
  opened as its detection moment, and the prediction's category and severity as its labels, marked as the
  model's.
- **FR-036**: The system MUST resolve a model-opened incident's responsible moderator exactly as TG-M4 does: the
  group's primary owner at the detection moment, recorded onto the incident, absent and visible as unassigned
  when there was none.
- **FR-037**: The system MUST report detection latency separately for model-opened and operator-opened
  incidents, and MUST include it in no figure attributed to a moderator.
- **FR-038**: The system MUST leave an operator-flagged incident, its labels and its opener unchanged when a
  prediction for its message arrives, and MUST show the prediction beside the operator's labels.
- **FR-039**: The system MUST subject a model-opened incident to TG-M4's lifecycle, timings, outcomes and
  false-positive closure without exception, and MUST count its false-positive closure as a recorded mistake of
  the model that opened it.
- **FR-040**: The system MUST fire no alert and send no message when an incident opens automatically in this
  milestone.

#### Possible violations

- **FR-041**: The control panel MUST provide a read-only list of possible violations within the domain's
  existing navigation group, showing for each the message text, its group, its posting moment, the model's
  category, severity and self-reported confidence, the classification model and instruction version, and
  whether it is listed as uncertain or as inconsistent, filterable by group and by posting period.
- **FR-042**: The list MUST include a possible violation only while its message anchors no incident, and MUST
  include no prediction below the floor and none made by the operator's catch-up command.
- **FR-043**: The list MUST let an operator flag a listed message using TG-M4's existing opening action, with
  the operator choosing the category and severity as for any operator flag; the resulting incident MUST be
  operator-opened in every respect.
- **FR-044**: The system MUST record, on an operator's flag made from the possible-violations list, that it was
  prompted by the list, and MUST record every other operator flag as independent.
- **FR-045**: The list MUST offer no other action: no dismissal, no change of label, no action on several
  entries at once, and no model call.

#### Measurement against human labels

- **FR-046**: The system MUST report, for a chosen period and group, separately for each combination of
  classification model, instruction version and vocabulary version, and never pooled across them:
  - on questions — of question items the rule set opened and nobody dismissed, of those operators dismissed,
    and of those operators added by hand, how many the model judged to need a response, a question item counting
    as judged so when any of its messages was; and, separately as unverified, how many messages the model judged
    to need a response where no question item and no human label exists;
  - on violations — of incidents operators flagged independently, how many the model judged to need moderation
    and how many of those it gave the same category as the operator; the same for list-prompted flags, reported
    apart; of incidents closed as false positives, how many the model judged to need moderation; of incidents the
    model opened, how many were closed as false positives; and how many possible violations are listed;
  - beside them, the rule set's own precision and recall for the same period and group, exactly as TG-M3
    defined them.
- **FR-047**: The system MUST show every ratio with its numerator and denominator, MUST label each as an
  estimate over the human labels available rather than a measured accuracy, and MUST NOT show a bare percentage.
- **FR-048**: The system MUST select messages into a period by their platform send time, inclusive at the start
  and exclusive at the end.
- **FR-049**: The system MUST NOT display an average of any kind — including of confidence — and MUST NOT
  compute any combined score for any model, moderator or group.
- **FR-050**: The system MUST produce every classification figure reproducibly by hand from stored predictions
  and human labels alone, and MUST define each figure once in the place shared by every screen that shows it.
- **FR-051**: The system MUST report, for a period and group, how many messages were classified, excluded by
  each eligibility reason, awaiting the model, and failed by each failure kind.

#### The screens

- **FR-052**: The Live Attention Queue MUST show, on each waiting question, the model's category and
  self-reported confidence for its messages, and MUST otherwise remain as TG-M4 left it.

  > **Amended by TG-M5.1 (2026-10-03).** It also shows who opened each item — Rule / Model / Operator (FR-109, `specs/009-tg-m5-1-ai-attention/`).
- **FR-053**: The incidents list MUST show how each incident was opened — by an operator or by the model — and
  MUST be filterable by it.
- **FR-054**: The incident detail MUST show the prediction for the incident's message — category, needs-response,
  needs-moderation, severity, confidence, classification model, instruction version and vocabulary version —
  and, for a model-opened incident, identify the prediction that opened it, and for an operator flag, whether it
  was list-prompted; it MUST replace TG-M4's statement that no model classification exists yet.
- **FR-055**: Wherever a prediction would be shown and none exists, the control panel MUST state why — not
  eligible and for which reason, awaiting the model, failed and of what kind, or no classification model active —
  and MUST NOT leave the space blank.
- **FR-056**: The control panel MUST label confidence as the model's self-report and MUST NOT present it as a
  probability or a percentage chance.
- **FR-057**: The control panel MUST show the classification figures on their own screen within the domain's
  existing navigation group.
- **FR-058**: The existing model roster screen MUST let the operator see and activate the classification model,
  keeping exactly one active model per role.
- **FR-059**: The control panel MUST make no model call, and MUST offer no control that classifies or
  re-classifies a message, acts on several messages or incidents at once, posts, bans, restricts, deletes, reacts
  or changes the store's shape.
- **FR-060**: The control panel MUST display Arabic content in its own reading direction per field, leaving the
  panel's language and direction unchanged.

#### The operator's commands

- **FR-061**: An operator command MUST classify, on request, the eligible messages of a named group and optional
  window that have no prediction yet and whose text is still within retention, MUST be idempotent across repeated
  runs, and MUST report how many it classified, excluded by reason, and failed by kind.
- **FR-062**: Predictions made by that command MUST open no incident, appear on no list, alert nobody, and be
  recorded as made for measurement only.
- **FR-063**: An operator smoke command MUST classify a set of labelled Arabic fixtures through the active
  classification model and report, per fixture, the expected and the predicted category and needs-moderation,
  passing only when every fixture matches; the operator's own fixtures MUST be read from outside version
  control, and a small synthetic set MUST ship with the repository.

#### Boundaries, silence and continuity

- **FR-064**: The system MUST send no outbound message, fire no alert and expose no inbound endpoint in this
  milestone, and the bot MUST perform no moderation act of any kind.
- **FR-065**: The system MUST keep the bot silent in every group, and this MUST remain covered by an automated
  test.
- **FR-066**: The system MUST keep the domain's module boundaries intact: only the model provider layer speaks
  to a model runtime, only the platform provider speaks to the platform, and no assessment-side module imports
  this domain.
- **FR-067**: The system MUST leave every TG-M3 figure and behaviour unchanged, and every TG-M4 figure and
  behaviour unchanged except that incidents may now also be opened by the model and operator flags record
  whether they were list-prompted.
- **FR-068**: The system MUST make predictions follow their messages through a platform-side group promotion,
  exactly as question items and incidents already do.
- **FR-069**: The system MUST keep predictions, routing decisions and classification failures for as long as the
  domain keeps its figures; none holds message text, so retention of text does not touch them.
- **FR-070**: The system MUST make every automated test in this milestone pass with the model scripted, no model
  runtime running, no platform credential set and no network access.

### Out of Scope (deferred to named later milestones)

- Letting the model open question items — whether to supplement the rule set or to replace it. Deferred by
  this milestone's second clarification, to be decided on the evidence its comparison produces, no earlier than
  TG-M8.

  > **Amended by TG-M5.1 (2026-10-03).** Supplementing the rule set was brought forward to TG-M5.1, for live predictions, behind a dated switch — `specs/009-tg-m5-1-ai-attention/`. Replacing the rule set remains out of scope.
- Alert rules, thresholds, the private moderators' group, the alert buttons, and any outbound message —
  **TG-M6**, including the alert wording the source plan sketches for uncertain predictions.
- The overview, team and group performance screens and the incomplete-window marker — **TG-M7**. The
  classification figures defined here are shown on this milestone's own screen and defined once for TG-M7 to
  arrange.
- The Classification Review queue — including recording a human verdict that a possible violation, or any other
  prediction, was wrong — the effective label that combines a prediction with its latest correction, correcting
  operator-assigned incident labels, and reprocessing — a new prediction for a message that already has one, the
  current-flag flip and the diff report an operator applies or discards — **TG-M8**. The immutable, versioned
  prediction built here is the thing those features act on.
- Scheduled digests and any endpoint an external tool calls — **TG-M9**.
- The job that removes message text at the end of retention — **TG-M10**. Predictions are shaped for it: they
  hold no text.
- Splitting spam from competitor adverts, or any other change to the seven categories — a later vocabulary
  version, once reviews have produced labelled examples.
- A deterministic link-policy rule — a student's message carrying a link opens an incident with `source =
  'rule'` — and redacting scheme-less links (`t.me/…`, bare domains) before the model. Both are later work: the
  first needs a TG-M4 schema and contract amendment, the second a TG-M0 text-contract amendment (the
  clarification session 2026-10-01, research §6).
- Re-classifying edited messages; classifying captions, images, voice notes or other media; classifying a
  multi-message question as one input; treating other people's follow-ups as context.
- Any bot action in a group — banning, restricting, deleting, warning, reacting or replying — and any automatic
  moderation. Excluded from the whole first version: it would destroy the very measurement the domain builds.
- Embeddings, similarity search, retrieval, or any use of the assessment domain's corpus. Excluded from this
  domain's first version.
- Comparing two models on the same messages (model A/B), fine-tuning, or any automatic retraining.
- Any composite score for any model, moderator or group.
- A full localisation of the control panel.

### Key Entities

- **Message classification (prediction)**: One model's claim about one message — a category, whether it needs a
  response, whether it needs moderation, a severity and a self-reported confidence — with its provenance: the
  classification model, the instruction version, the vocabulary version, the model call, and when it was made.
  Immutable; at most one current per message; holds no message text.
- **Classification model role**: The slot in the existing model roster for the model that classifies moderation
  messages, with exactly one active model, chosen independently of the assessment generation model and sharing
  the machine's one-generation-at-a-time protection with it.
- **Instruction version and vocabulary version**: The named, versioned instruction the model was given, and the
  numbered version of the seven-category vocabulary it answered in. Every figure is grouped by both, because a
  number pooled across versions describes no model that ever ran.
- **Routing decision**: What the system did with a prediction — opened an incident, found the message already
  flagged, listed it as a possible violation (uncertain or inconsistent), recorded it as awaiting review, found
  no moderation needed, or recorded it for measurement only — and the thresholds in force when it decided. Made
  once, never revisited.
- **Possible violation**: A live prediction that a message needs moderation, not confident or not coherent enough
  to open an incident and not so weak as to fall below the floor. Listed read-only while its message anchors no
  incident; in nobody's figures; turned into an incident only by an operator's own flag.
- **Flag origin**: On an operator-opened incident, whether the operator flagged the message independently or from
  the possible-violations list — the fact that keeps the comparison from counting a suggestion taken as an
  independent agreement.
- **Eligibility outcome**: For a message that never reached the model, which condition excluded it; for one that
  did and produced no prediction, which kind of failure. Together with predictions, these account for every
  message in a measured group.
- **Model-opened incident**: A TG-M4 incident whose opener is the model: linked to the prediction that opened it,
  labelled with that prediction's category and severity marked as the model's, and in every other respect —
  lifecycle, attribution, timings, outcome, false-positive closure — an incident like any other.
- **Human labels**: The corrections TG-M3 and TG-M4 already record — dismissed questions, questions added by hand,
  operator-flagged incidents with their categories, false-positive closures — which this milestone uses as the
  reference the model is compared against, without changing any of them.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The runbook's smoke test passes as written: the operator's 5–10 labelled real Arabic messages are
  classified by the active classification model with every category and needs-moderation judgement matching the
  operator's label, and each result is reported.
- **SC-002**: In the development group, a clear advert posted by the disposable account opens a model-opened
  incident within one minute while the model is otherwise idle, with its posting moment equal to the platform
  timestamp, its detection moment when the model flagged it, the owner at that moment as responsible, and nothing
  sent anywhere.
- **SC-003**: With the model runtime stopped, a question asked and answered in the development group produces
  the same question item and the same response time as TG-M3 would; when the runtime returns, each waiting
  message is classified exactly once.
- **SC-004**: Across scripted valid, cut-off, malformed and out-of-range outputs, zero partial, repaired or
  defaulted predictions are recorded, and every failure is counted with its kind.
- **SC-005**: Across a fixture set containing phone numbers in three digit systems, email addresses, links and
  handles, none of them reaches the shared model layer or any record it keeps, with its debugging capture on.
- **SC-006**: 100% of predictions carry their classification model, instruction version, vocabulary version,
  confidence, model call reference and routing decision.
- **SC-007**: Interpreting the same message three times produces one prediction, one successful model call and at
  most one incident; two workers classifying the same message at once produce the same.
- **SC-008**: Every routing case — below the floor, exactly at the floor, inside the band, just below and exactly
  at the incident threshold, and each inconsistent combination — produces exactly the outcome specified, and none
  but the confident, consistent, live case opens an incident.
- **SC-009**: Changing either threshold afterwards changes no past routing decision, incident, list entry or
  figure.
- **SC-010**: Activating a different classification model leaves the active assessment model unchanged, and the
  reverse.
- **SC-011**: Running the catch-up command twice over the same group and window classifies nothing the second
  time, and neither run opens an incident or adds a possible violation.
- **SC-012**: For a fixed fixture of human labels and scripted predictions from two models, every classification
  figure matches hand computation, no figure combines the two models, and list-prompted flags are counted apart
  from independent ones.
- **SC-013**: No average — of confidence or of anything else — and no combined score appears anywhere in the
  control panel.
- **SC-014**: Across every combination of prediction values, no prediction changes the state of any question item
  or any incident it did not open, and no question item is ever opened by the model.

  > **Amended by TG-M5.1 (2026-10-03).** Holds with `MODERATION_AI_ATTENTION_FROM` blank. With it set, the model may open a question item the rules declined, and still changes the state of none it did not open — `specs/009-tg-m5-1-ai-attention/`.
- **SC-015**: Every TG-M3 figure computed over the same traffic is identical with and without a classification
  model active; every TG-M4 figure differs only by the incidents the model opened.

  > **Amended by TG-M5.1 (2026-10-03).** Holds with `MODERATION_AI_ATTENTION_FROM` blank. With it set, the TG-M3 response figures also count model-opened questions, as items like any other (TG-M5.1 FR-108).
- **SC-016**: In a representative fixture of group traffic, moderators' messages, service announcements,
  acknowledgement-only messages and messages without text never reach the model, and the count excluded by each
  reason is reported.
- **SC-017**: A model-opened incident closed as a false positive appears in the model's false-positive count and
  in no handled, missed or timing figure.
- **SC-018**: A prediction inside the band opens no incident and appears on the possible-violations list;
  flagging it from there produces an operator-opened incident with the operator's labels, recorded as
  list-prompted, and the entry leaves the list.
- **SC-019**: The complete automated test suite and the quality gate pass with no model runtime, no platform
  credential and no network access.
- **SC-020**: No log line produced anywhere in this milestone contains message text in any form or the model's raw
  output, enforced by the existing automated check.
- **SC-021**: Over one full smoke run, the bot posts nothing anywhere and performs no moderation act.

## Assumptions

These are reasonable defaults taken where the milestone description did not specify details. Each is drawn from
the source plan, the operator runbook, the constitution, or a previous milestone.

- **Definition of done.** Implementation exists, tests exist and pass, documentation and configuration are
  updated, a manual smoke test succeeds, no unrelated scope was added, and known limitations are written down.
  From the source plan's §25 preamble.
- **The vocabulary is the plan's first version.** Seven categories, two yes/no judgements, a four-step severity
  and a confidence, exactly as D-TG-08 and §15.1–15.2 define them; the vocabulary is version 1. Spam and
  competitor adverts stay one category until reviews have produced labelled examples to split them on.
- **Confidence is a routing hint, never a probability.** From §15.6: the model's self-report is weakly
  calibrated. It decides routing and is displayed labelled as a self-report; it is never averaged.
- **The thresholds are the plan's.** A floor of 0.60 and an incident threshold of 0.85, from §14.1 and §15.6,
  configurable, and blank-safe because TG-M4's second finding showed a blank configuration value silently
  becoming zero.
- **Uncertain violations are listed, not opened.** Confirmed in this session, resolving the disagreement
  between §14.1 and §15.6 in §14.1's favour while making the band visible now rather than at TG-M8. The list is
  read-only because recording that a listed message was *not* a violation is a review verdict, and review is
  TG-M8's; its only action is TG-M4's existing flag, so the list adds a way to see, not a new way to act.
- **List-prompted flags are kept apart.** An operator who flags a message because the model listed it is not
  independently agreeing with the model; counting it as agreement would inflate the model's figures by exactly
  the flags it caused. Recording the flag's origin is the smallest fact that keeps the comparison honest.
- **The model measures questions; it does not open them.** Confirmed in this session. TG-M3 built the rule set's
  precision and recall as the baseline the model must beat; the model is compared against it on the same human
  labels, and every TG-M3 figure is left exactly as it was so the baseline is undisturbed. Whether the model later
  supplements or replaces the rule set is a decision taken on this evidence, not assumed here.
- **Only a consistent prediction may open an incident.** A prediction that says a message needs moderation but
  calls it chit-chat, a question or a complaint, or gives it severity none, is a model contradicting itself — a
  real failure mode of small models. The incident vocabulary TG-M4 fixed is spam or advert, abuse, or other, at
  low, medium or high; a prediction outside it is never coerced into it. It is listed, marked inconsistent,
  instead.
- **The catch-up command measures; it never accuses.** It exists so that the human labels TG-M3 and TG-M4 have
  already recorded can be compared with the model, which requires the labelled messages to be classified. An
  incident opened or a possible violation listed from it would concern a message weeks old and would be charged
  to today's owner, so its predictions are recorded for measurement only. It classifies only messages that have
  no prediction; replacing an existing prediction is TG-M8's reprocessing.
- **Nothing is backfilled automatically.** As in TG-M3 and TG-M4: ordinary operation classifies messages recorded
  from this milestone onwards, and history is reached only through the operator's command, on request.
- **Messages are classified one at a time, with no context.** §15.5 sends the redacted text of one message; the
  plan defers conversation modelling (D-TG-03). The question side of the comparison therefore judges a question
  item by any of its messages, mirroring the rule set's "at least one message carries a question signal".
- **The eligibility filter narrows the plan's pre-filter in two places.** §25 lists bot messages and
  already-answered messages among what never reaches the model. This spec classifies both: TG-M4 established bot
  accounts and channels as spam sources and fixed capture specifically so channel spam is stored, and an answered
  message is still one the comparison needs — both as a labelled question and because a message can be answered
  and be spam. The cost is more calls per day, which the model call accounting makes visible. Recorded here as a
  narrowing rather than taken quietly.
- **Classification starts when a classification model is activated.** Seeding and activating the classification
  model in the roster is the operator's deliberate act that turns the milestone on; no separate switch is added.
  The seed is the same local model already installed for generation, configured for short, deterministic
  answers, per D-TG-14; a larger model can be activated for the classification role alone.
- **The shared model layer changes in one additive way.** From D-TG-14 and §23: the roster's role vocabulary
  widens by one role, and callers may name the role they want, with every existing caller unchanged. It is the
  only extension to the model gateway's contract, and the one-generation-at-a-time protection stays shared
  because a classification is still a generation on a machine that cannot run three at once.
- **Retries follow the gateway's failure vocabulary.** Transient failures are retried with backoff a bounded
  number of times; an output that was cut off or malformed is not, because the classification model answers
  deterministically and would fail identically. Setting a retry policy per task, not globally, is from §2.4.
- **Model-opened incidents go through TG-M4 unchanged.** One opening step, one guard, one evidence matcher; the
  lifecycle, the "acted before flagging" rule, handled-in-time and every figure apply to them as written. The
  responsible moderator is the owner when the model flagged the message, the counterpart of measuring moderator
  timings from the flag.
- **An operator's flag outranks a prediction.** When both exist for one message, the incident keeps the
  operator's labels and opener, and the prediction is shown beside them. Correcting either belongs to TG-M8.
- **A late classification still opens an incident when it is confident.** After a model outage the detection
  moment is when the model flagged the message; the delay is the system's detection latency, reported apart and
  charged to nobody. No staleness cut-off is added: the delay is visible, and a cut-off would silently discard
  real violations.
- **Edits and media are not classified.** §4 defers edited-message handling and media captions to after the first
  version; a message edited into an advert after it was classified is a known limitation, written down.
- **The model never touches the lifecycle.** A prediction is not evidence. The model can open an incident; it can
  never acknowledge, resolve or close one, and it never opens, dismisses or closes a question.
- **Labels on screens are a known source of influence.** Showing the model's labels to operators makes their later
  corrections less independent of it. The strongest case is recorded (list-prompted flags); the rest is written
  down as a known limitation rather than hidden by withholding labels the source plan asks to show.
- **The smoke test runs against the real local model, and the fixtures stay private.** Runbook §C's TG-M5 row asks
  the operator for 5–10 real Arabic messages with known labels; real student messages are personal data, so the
  command reads the operator's fixtures from outside version control, and a small synthetic set ships for anyone
  else. The live dev-group check in SC-002 extends the runbook row and uses the dev group and the disposable
  account TG-M4 already required.
- **Figures follow the established rules.** Selection by platform time, half-open periods, no averages, no
  composite, one shared definition per figure, reproducible by hand — as TG-M3 and TG-M4 established.
- **The panel reads the same store directly with its restricted role, owns no schema change, makes no model call,
  and its tests wrap each case in a transaction.** The established pattern, not revisited.
- **Tests are written where the risk is.** Following Principle I: the structured-output contract at this boundary
  (valid, cut off, malformed, out of range); redaction; the eligibility filter; confidence and consistency
  routing; idempotency of classification and of automatic opening; that no prediction moves any state it did not
  open and never opens a question; the list's membership rule and flag origin; the comparison arithmetic; the
  role separation in the roster; model-down continuity; and the silence guarantee. No test is written for screen
  listing behaviour, framework wiring or column types.
- **Migration numbering is linear and first-come.** This domain reserved a block of revision identifiers and
  consumes the fifth of them here.

## Dependencies

- **TG-M4 must be complete and merged**, as it is: incidents with their single opening step, the guard, the
  evidence matcher that runs at opening, the automatic opener value reserved and never written, the empty link to
  a classification shaped for this milestone, operator-assigned labels in the plan's vocabulary, false-positive
  closures, and the incident figures, the "acted before flagging" rule and the handled-in-time outcome.
- **TG-M3 must remain in place**: question items with their source and rule version, the rule set's
  acknowledgement stoplist, operator dismissals and hand-added items, the rule-set precision and recall
  definitions, the Live Attention Queue, and the question figures.
- **TG-M3's rule-set accuracy has been measured.** The source plan's gate for this milestone: the rule set's
  precision should have been read over real pilot traffic — the TG-M3 quickstart says after a week, not an
  afternoon — so the model has a baseline to beat. The milestone is fully buildable and testable without it; the
  comparison it reports is only meaningful with it.
- **TG-M2 must remain in place**: typed messages with normalised text, platform send time, sender, the write-once
  record of whether the sender was a moderator, content flags, the ownership history and its point-in-time
  lookup, the measurement flag, and the operator's re-derivation command.
- **TG-M1 and TG-M0 must remain in place**: the append-only captured-event record, group promotion linking, the
  domain's module boundary and its enforcement, the configuration block, the correlation-identifier whitelist,
  the no-message-text rule, the domain's Arabic normaliser and the redactor.
- **M1 must remain in place**: the model gateway with its roster, active-model resolution, one-generation-at-a-time
  protection, failure protection, retries, structured-output checking that rejects a cut-off answer before
  parsing, the closed failure vocabulary, call accounting, and the scripted fake model that makes classification
  testable with no runtime. This milestone extends it by one role and one additive selection, and changes nothing
  else about it.
- **M0 must remain in place**: the running environment, migrations as the sole owner of schema change, the queue
  and background worker, the control panel shell with its restricted role and transaction-per-test pattern, and
  the quality gate with its enforced test-store isolation.
- **The source plan** `docs/plan/telegram/telegram-moderation-intelligence.md` — §7 for where classification sits
  in the flow, §9 for fact versus derived, §10.10 for the prediction record, §14.1 and §15.6 for confidence
  routing, §15 for the taxonomy, structured output, the model role, Arabic handling, redaction and reprocessing,
  §18.7 for the accuracy figures, §19 for the two identity planes and retention, §20.2 for the model-down and
  slower-than-moderator scenarios, §22 for which tests are earned, §25 for this milestone's own definition, and
  §27 for the dialect-weakness risk and its mitigation.
- **The operator runbook** `docs/runbooks/tg-operator-prerequisites.md` — §A.1 for the model runtime's launch
  settings and the already-installed model, §C's TG-M5 row for the prerequisite and the smoke test.
- **Operator-supplied**: the model runtime running with its launch settings; 5–10 real Arabic messages whose
  correct label the operator already knows, kept outside version control; and, for SC-002, the development group,
  the development bot as an administrator there and the disposable account from TG-M4. Without them the milestone
  is fully developable and fully testable, but not smoke-testable.
- **No model runtime, no network access and no credential** are required by anything in this milestone's
  automated verification, including its tests.
