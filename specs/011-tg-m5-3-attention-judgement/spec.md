# Feature Specification: TG-M5.3 — A Separate Attention Judgement

**Feature Branch**: none created. Git is operator-owned (constitution IV), so the work sits on
`m5/ai-classification`.
**Created**: 2026-10-07
**Status**: Draft. *(2026-10-09)* Amended by the Policy D′ addendum
(`docs/plan/telegram/tg-m5-3-attention-v2-addendum.md`, approved 2026-10-09 with every recommended option):
`attention_v1` stays frozen as history, and `attention_v2` goes through a second qualification cycle.
*(2026-10-09)* **The second cycle stopped under W-7′.** No v2 candidate passed, including after the one revision, so
`attention_v2` was not created. `attention_v1` is not qualified under D′, and AI-assisted opening stays off
(rules-only).
**Input**: "TG-M5.3 — A Separate Attention Judgement, per `docs/plan/telegram/tg-m5-3-attention-judgement-plan.md`,
with the approved decisions (§16 items 1–12, approved 2026-10-06) and the 2026-10-07 amendments (§16 items 13–19,
approved 2026-10-07 as written; D6 kept as 'course-content question with no addressee → asking, marked
ambiguous'; the dismissal-reason story is first and independently deployable and also carries the corrected
'dismissed (any reason)' wording and per-reason breakdowns)." That is the operator's request of 2026-10-07. The
plan of record is `docs/plan/telegram/tg-m5-3-attention-judgement-plan.md`.

## Provenance: why this milestone exists

- **TG-M5.1** let a live prediction open an Attention item that the rule set declined. Its signal is the
  needs-response value of the same classification that judges adverts and abuse.
- **TG-M5.2 stopped under its FR-216** (2026-10-06). Two milestones of evidence show that one instruction cannot
  carry both judgements:
  - Needs-response followed the *topic*, not the *function* (010 Finding 10).
  - On the small model, every wording that separated asking from informing moved the advert boundary (010
    Finding 11).
  - On the larger model, the compliant wording re-opened a clear negative. A one-sentence change to the
    needs-response wording turned a legitimate message into an advert incident (010 research §2).
  - The attention wording alone did work on the small model: 0 of 27 clear negatives opened, 0 of 13
    positives missed. It failed only because it shared the prompt with the advert policy.
- **FR-216 named the next step:** a separate needs-response judgement, as its own specification. This is it.
- **The operator's review of 2026-10-07** added three things:
  - a way to mark **member-to-member discussion** apart from "not a real question";
  - a `discussion` intent and labelling Policy D;
  - a verified account of **multi-message bursts**, with no change to TG-M3.

**What it changes:**
- a new attention judgement, with its own instruction, output, record, model role and qualification;
- TG-M5.1's opener reads that judgement instead of the classification's needs-response;
- a third dismissal reason, "Member discussion", with per-reason breakdowns and corrected wording.

**What it keeps:**
- `classify_v2` stays byte-identical, along with routing, thresholds, incidents and TG-M4.
- TG-M3's rule set, bursts, settle window, attribution, matching and ageing stay as they are.
- The gateway, redaction, first-posted-text behaviour and immutability stay as they are.

## Clarifications

### Session 2026-10-06 (plan approval, plan §16 items 1–12)

- **Q: How are attention judgements stored?** A: In their **own immutable record**, beside the classification's.
  Both are insert-only, with one current judgement per message. A generic judgement store and extra columns on
  the classification record were rejected.
- **Q: What does the model return?** A: **One intent from a closed list.** Needs-response is derived from it by
  the domain. There is no self-reported confidence.
- **Q: May the attention side read the moderation side?** A: **Once, and one way only.** The opener does not
  open a model item on a message the classification called an advert or abuse. Nothing else is shared.
- **Q: Which model runs the attention judgement?** A: A model with its **own role**, chosen separately from the
  moderation model.
- **Q: When is a message judged?** A: **At ingest.** The call is skipped when the message's own first-posted
  words already open the rules. The two judgements are independent and may run concurrently.
  - **Current scheduling policy:** Attention goes before Moderation only when both need the same constrained
    inference lane.
  - **Not a contract rule:** the ordering is deployment policy and may change.
- **Q: Are judgements recorded before the opening switch is set?** A: **Yes, in shadow.** Judgements are
  recorded whenever the attention instruction is configured, whether or not the opening switch is set.
- **Q: How is the pair qualified?** A: With **one task-agnostic qualification core and per-task suites**. The
  violations threshold starts at ≤ 1. Latency is a deadline property: the judgement lands before the settle.
- **Q: How is the wording chosen?** A: **Three candidates fixed before any run**, measured on two models with a
  validation set.
  - One selection round and at most one revision, then a freeze.
  - A held-out set is written after the freeze, and the operator supplies a fresh sample.
  - If nothing passes, the milestone stops.
- **Q: Is the classification-sourced opener kept as a fallback?** A: **No, it is removed.** Development AI
  opening pauses until the attention pair qualifies.
- **Q: Is catch-up judged?** A: **No, it is deferred.** Only live messages get attention judgements.

### Session 2026-10-07 (plan amendments, plan §16 items 13–19)

- **Q: How does an operator mark a real question that only members needed to answer?** A: With a **third
  dismissal reason, "Member discussion"**.
  - It is distinct from "Not a real question", and the item's status stays dismissed.
  - It applies to items opened by the rules, the model or an operator.
- **Q: Do the existing dismissal-based figures change?** A: **No.** Every figure that counts dismissals keeps
  counting every reason, and that includes the pilot gate.
  - **Additive:** a per-reason breakdown is added beside the rule-dismissed and model-dismissed counts.
  - **Diagnostic only:** the breakdown never moves a gate.
- **Q: The panel and two documents call every dismissal "not a real question". Is that fixed?** A: **Yes, in this
  milestone's first story.** The wording becomes "dismissed (any reason)", followed by the breakdown. It is not
  applied separately beforehand.
- **Q: What does "asking" mean?** A: A message that reasonably needs an **answer, action, clarification or
  decision from the team**. Being grammatically a question does not decide it.
  - **The new intent:** a `discussion` intent covers genuine peer-to-peer questions that need no moderator.
  - **The derivation is unchanged:** needs-response is true exactly when the intent is `asking`, and that stays
    the single derivation.
- **Q: Where is the line between asking and discussion?** A: **Policy D** (FR-310), with these edge cases:
  - a peer-addressed service question → `asking`;
  - a named-peer academic or experience question → `discussion`;
  - an unclear case → `asking`.
- **Q: A course-content question with no addressee (D6)?** A: **`asking`, marked ambiguous**, so it is reported
  but never gated. It is revisited only if pilot data shows most such questions are peer discussion.
- **Q: Does TG-M3 change for multi-message bursts?** A: **No.**
  - **Already handled:** a greeting followed by a question already opens by rule.
  - **No burst input:** the model receives no burst-level input in this milestone.
  - **The remaining gap (L-B1):** a request spread across messages, where no single message asks on its own. It
    is documented and measured.

### Session 2026-10-07 (Policy D confirmed by the operator, T070)

- **Q: Is Policy D confirmed as the operator's policy for TG-M5.3?** A: **Yes, D1–D8**, with D1 reworded:
  - **D1 — The expected answerer decides, not the addressee.** Classify by who should reasonably provide the
    useful or authoritative answer, not simply by who the message is addressed to. Illustrations:
    - «يا شباب التسجيل فتح؟» → `asking`: the team is the authority on registration;
    - «يا شباب مين اختبر اليوم؟» → `discussion`: the answer comes from members' own experience;
    - «يا أحمد رابط المحاضرة فين؟» → `asking`: the subject is an official service or resource;
    - «يا أحمد كيف حليت السؤال 15؟» → `discussion`: the requested answer is Ahmed's own work or experience.
  - **D2–D8 stay as written,** including D6: a course-content question with no addressee is `asking`,
    `label_class: ambiguous`.
  - The illustrations show the policy; they are not fixture lines. Each carries a v1 signal (`؟`), so the rules
    would open them before any model is asked.

### Session 2026-10-08/09 (Policy D′, the operator's option (a); addendum approved 2026-10-09)

- **Q: Is general guidance about outside institutions the team's responsibility?** A: **No, option (a)
  (2026-10-08).** The operator reviewed T077's real fresh sample:
  - Outside institutions include universities, Qiyas and other national testing bodies, licensing bodies,
    ministries and government portals.
  - Questions and problems about them create no moderator-response obligation unless they are specifically about
    the course's own service.
  - Policy D's D2, D5 and D7 had made peer questions about them `asking`.
- **Q: What replaces Policy D?** A: **Policy D′ (FR-310).** Its direction was approved 2026-10-08, and its exact
  text 2026-10-09 (addendum §3):
  - D0 is new: the team's responsibility.
  - D1, D2, D3, D5 and D7 are amended. D4, D6 and D8 are unchanged.
  - The `asking` and `discussion` definitions (FR-309) and Policy S's scope change with it.
  - D7 still leans to `asking` when it is unclear whether the subject is the course's own service.
  - Two illustrations are added, synthetic and rule-opened by their `؟`:
    - «يا شباب نتائج الجامعة طلعت؟» → `discussion`: an outside institution;
    - «يا شباب نتائج الاختبار التجريبي طلعت؟» → `asking`: the course's own test.
- **Q: What happens to `attention_v1`?** A: **It stays frozen, pinned and allowlisted, as history.**
  - Its evidence (T071–T077) is kept as recorded. It is valid under Policy D (2026-10-07).
  - Under D′ it is not qualified, so FR-329 bars it from opening. `MODERATION_AI_ATTENTION_FROM` stays blank.
  - Any judgements it records keep `prompt_version = 'attention_v1'` and are never rewritten.
  - The new wording is `attention_v2`, qualified in a second cycle (FR-330, FR-331).
- **Q: Which fresh sample did T077 qualify on?** A: **The 37-line version (operator, 2026-10-08).**
  - The operator then cut the active file back to 30 lines to meet the 20–30 requirement.
  - The 37-line evidence is historical only.
  - The sample is relabelled under D′ and becomes tuning (`real-attention-fresh-v1.jsonl`). It is never a fresh
    sample again.
- **Q: What does D′ change for rule-opened messages?** A: **Nothing.**
  - Most outside-institution questions carry a v1 signal. Rule set v1 opens them before any model is asked (7 of
    the operator's 8 examples).
  - They are dismissed as "Member discussion", whose definition already covers them, and counted by C7 and C9.
  - A rule-set change would be a separate milestone.
- **Q: How is the second cycle judged?** A: **As the addendum's §6, with every recommended option:**
  - the 37-line sample becomes tuning;
  - the v1 held-out set is kept byte-identical as a validation set;
  - A3 is judged per validation set;
  - the candidates are V2-A, V2-B and V2-C, in that order of preference;
  - the topics are fixed in addendum §6.2 and §6.6.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — The operator marks member discussion, and the figures say why items were dismissed (Priority: P1)

In large trainee groups, members ask each other questions, such as «يا شباب مين اختبر اليوم؟». Rule set v1 opens
many of these, because they carry a question mark or a question word. Today the operator can only dismiss such
an item as "Not a real question", which is untrue, or leave it open until it expires and counts as unanswered
forever. With this story:
- the operator dismisses it as **Member discussion**;
- the item leaves the unanswered and response-time figures;
- the accuracy page shows how many dismissals were member discussion, not a real question, or a removed
  message.

Nothing the existing figures count changes.

**Why this priority**: It works without any model. It corrects the existing figures today, and it starts
counting rule-opened peer questions at once. That count is the evidence for any later rule change. It also
corrects wording that is already misleading.

**Independent Test**: Deploy this story alone. On a fixed scenario with items dismissed for each reason:
- every existing dismissal count is unchanged;
- the per-reason parts sum to it;
- no screen calls every dismissal "not a real question".

**Acceptance Scenarios**:

1. **Given** an open item of any source, **When** the operator chooses "Member discussion" and confirms,
   **Then**:
   - the item is dismissed with the reason member discussion, who dismissed it and when;
   - it stops ageing;
   - it leaves the unanswered count.
2. **Given** the dismissal confirmation, **When** it is shown, **Then** it states what each of the three reasons
   means.
3. **Given** an already-dismissed item, **When** a second dismissal is submitted, **Then** nothing changes.
4. **Given** a period with dismissals for each reason, **When** the accuracy page shows the rule baseline and
   the questions the model opened, **Then**:
   - each dismissal count is the same as before this story;
   - a breakdown by reason appears beside it, and its parts sum to the count.
5. **Given** the page's model-opened questions section, **When** it is read, **Then** it says "dismissed (any
   reason)", not "dismissed as not a real question".

---

### User Story 2 — Every eligible message gets its own attention judgement, independent of moderation (Priority: P1)

When a member posts, the system asks a separate attention instruction what the message *does*: asking,
discussion, informing, social, offering or other. It records that judgement once, with the model and
instruction that made it. The moderation judgement runs as before, unaware of it.

In shadow (the opening switch blank), judgements accumulate. The operator sees two things:
- coverage: judged, excluded by reason, failed, or not yet;
- timeliness: the share of judgements landing before the burst settles.

**Why this priority**: It is the new capability, and it must be measurable before it opens anything.

**Independent Test**: Configure the attention instruction and an attention profile, leave the opening switch
blank, and ingest messages. Then confirm:
- each eligible message gets exactly one judgement or one exclusion;
- a replay records nothing new;
- the classification record is unchanged in content;
- no item opens.

**Acceptance Scenarios**:

1. **Given** an eligible member message whose own words do not open the rules, **When** it is ingested,
   **Then** one attention judgement is recorded, with its intent, the derived needs-response, the model and the
   instruction version.
2. **Given** a message whose own first-posted words open the rules, **When** it is ingested, **Then** no call
   is made, and an exclusion "rule opens" is recorded once.
3. **Given** a message the classification also excludes (a moderator's, a bot's, an acknowledgement, and so
   on), **When** it is ingested, **Then** the attention exclusion records the same reason.
4. **Given** the attention model is unreachable, **When** the message is judged, **Then** it retries, then
   records a failure naming the model. The classification is unaffected, and the rules still open explicit
   questions.
5. **Given** the moderation model is unreachable, **When** a message is ingested, **Then** the attention
   judgement is recorded and works as normal.
6. **Given** the attention instruction is blank or no attention profile is active, **When** messages arrive,
   **Then** no call is made and nothing is recorded.

---

### User Story 3 — A question the rules miss is opened from the attention judgement (Priority: P1)

A member writes «حاولت ادخل المنصة وما زبط معي» with no question signal. The rules decline. The attention
judgement says `asking`. With the opening switch set, the opener opens a model item, using the same anchor,
clock and owner as TG-M5.1. A late judgement reconciles through the existing re-judgement path.

An advert that the moderation side called an advert never opens a question item, whatever the attention side
said.

**Why this priority**: This is the outcome TG-M5.1 promised and TG-M5.2 could not deliver.

**Independent Test**: With scripted judgements, check the following:
- rules first;
- an item linked to the opening attention judgement;
- the advert and abuse veto;
- window checks;
- reconciliation for judgements before and after the settle;
- no model item when the attention instruction is blank, even with the switch set.

**Acceptance Scenarios**:

1. **Given** a burst the rules open, **When** it settles, **Then** a rule item opens, and no attention judgement
   is consulted.
2. **Given** a burst the rules decline whose earliest `asking` member has a live judgement within the window,
   **When** it settles, **Then**:
   - a model item opens on the burst's earliest member, dated from it;
   - the item is linked to that judgement.
3. **Given** the same burst where that member's classification is advert or abuse, **When** it settles,
   **Then** no model item opens from that member.
4. **Given** a member whose classification is social chat and whose attention judgement is `asking`, **When**
   the burst settles, **Then** the model item opens. Social chat is not vetoed.
5. **Given** a judgement that lands after the burst was judged, **When** it is recorded, **Then** the burst is
   re-judged and converges on one item within one sweep interval.
6. **Given** a judgement recorded before the switch was set, or older than the maximum item age, **When** the
   burst is judged, **Then** it opens nothing.
7. **Given** a model item, **When** a moderator replies, **Then** it is answered exactly like a rule item. The
   model closes, dismisses, expires, re-dates and re-attributes nothing.

---

### User Story 4 — Member discussion is told apart from questions for the team (Priority: P2)

A member writes «حد خلص الواجب» ("anyone finished the homework?"). No rule fires. The attention judgement says
`discussion`, and no item opens. Another member writes «يا جماعة حد عنده رابط المحاضرة» ("does anyone have the
lecture link?"), addressed to peers but about the service. It is `asking`, and an item opens. When the case is
unclear, the judgement leans to `asking`.

**Why this priority**: Without a `discussion` intent, a peer question has nowhere to go but `asking`. That is the
form-over-function error in a new place. It reaches only peer questions without a rule signal; the rest are
handled by Story 1.

**Independent Test**: Run the attention suite on the validation and held-out peer lines, all written so that
rule set v1 declines them. Read the asking-vs-discussion line.

**Acceptance Scenarios**:

1. **Given** a rule-declined, named-peer or peer-group question about the members' own experience or work,
   **When** it is judged, **Then** the intent is `discussion` and no item opens.
2. **Given** a rule-declined, peer-addressed question about schedule, access, links, materials, exams,
   registration, payment or certificates, **When** it is judged, **Then** the intent is `asking`.
3. **Given** a rule-declined, peer-addressed problem check ("is the platform opening for anyone?"), **When** it
   is judged, **Then** the intent is `asking`.
4. **Given** a member answering another member, **When** it is judged, **Then** the intent is `informing`.

---

### User Story 5 — The operator qualifies an attention pair on any host before switching on (Priority: P1)

The operator registers a candidate as an inactive attention profile, then runs the qualification for the
attention task, naming the profile and the instruction. The report, printed per set, contains:
- gate lines, with counts and line numbers, never text;
- the ambiguous lines;
- the asking-vs-discussion line;
- the rule-opened negatives;
- the burst-fixture results;
- latency.

Nothing is written. The opening switch may be set only on a QUALIFIED pair. The moderation task is qualified
by its own suite, with its existing advert gates.

**Why this priority**: Production will not run on the development model. Switch-on must rest on evidence.

**Independent Test**: Run the attention qualification for an inactive profile. Confirm that:
- it writes no row and prints no message text;
- it reports every gate and reported line;
- a run that names a candidate wording file can never print QUALIFIED.

**Acceptance Scenarios**:

1. **Given** a named attention profile and a pinned attention instruction, **When** the qualification runs,
   **Then**:
   - every attention set is judged on the real path: rules first, then eligibility and the rule skip, then the
     model;
   - each gate shows pass or fail.
2. **Given** a fixture whose intent disagrees with its needs-response label, or names an unknown intent, **When**
   the run starts, **Then** the verdict is INCOMPLETE and the line is named.
3. **Given** two runs on the same pair, **When** they are compared, **Then** the per-line results are
   identical.
4. **Given** the moderation qualification on `classify_v2`, **When** it runs, **Then** its advert gates are
   those of 010, and its results are unaffected by this milestone.

---

### User Story 6 — The wording is chosen without fitting the benchmark (Priority: P2)

Three candidate wordings are fixed before any run:
- generic;
- derived from the measured probe;
- generic plus a one-sentence glossary of the service.

All three share the same intent definitions and Policy D, word for word. Each runs on the small and the larger
model, against the tuning sets and an off-vocabulary validation set. A decision rule written beforehand picks
the smallest passing model and the fewest-assumption wording. At most one revision follows, then a freeze.

The held-out set is written only after the freeze and run once. The operator's fresh sample is labelled before
any run. If nothing passes, the milestone stops and reports, as TG-M5.2 did.

**Why this priority**: TG-M5.2 showed how easily a wording memorises fixture nouns. Only unseen cases show
whether the distinction is learned.

**Independent Test**: Check the order of events:
- the candidates' hashes are recorded before the first run;
- the held-out set is created after the frozen instruction's hash;
- the held-out run happens once, with no later edit to the frozen instruction.

**Acceptance Scenarios**:

1. **Given** the selection results, **When** a candidate wins only on in-vocabulary tuning lines and not on the
   validation set, **Then** the noun effect is recorded as memorisation, and the generic wording is preferred.
2. **Given** the frozen instruction, **When** the held-out set fails a gate, **Then** the failure is reported
   as it stands, and the frozen version is not edited.

---

### User Story 7 — Multi-message bursts stay as they are, and the remaining gap is measured (Priority: P3)

A member posts «السلام عليكم», then «متى موعد الاختبار؟». The rules already open this burst on the second
message, dated from the greeting. No change is needed.

A member posts a greeting, then «كنت بحاول أدخل الاختبار», then «بس الرابط بايظ». No rule fires. The last
message is `asking` on its own, so the model item opens on the burst, dated from the greeting.

What remains is L-B1: a request spread across messages, none of them asking alone. It is documented. It is
measured before the pilot by reported burst fixtures, and during the pilot by splitting the operator's
hand-opened items by burst size.

**Why this priority**: The operator's preference is to measure before building. The only deliverables here are
measurement and documentation.

**Independent Test**: Run the burst fixtures, and read each line's opener and opening member. Confirm the
following:
- no burst-level input reaches any model;
- the operator-added split shows single- and multi-message bursts.

**Acceptance Scenarios**:

1. **Given** a burst fixture whose members are a greeting and a question with a rule signal, **When** it is
   scored, **Then** the opener is the rules.
2. **Given** a burst fixture where no member carries a rule signal and one member is `asking` alone, **When** it
   is scored, **Then** the opener is the model, and the opening member is named.
3. **Given** an L-B1 burst fixture, **When** it is scored, **Then** its result is reported (expected: none) and
   never gated.
4. **Given** hand-opened items in a period, **When** the coverage figures are read, **Then** each is counted by:
   - its anchor's attention status;
   - whether its sender posted another message in the same chat and thread within the burst gap.

### Edge Cases

- **A greeting before a question:** the greeting gets its own attention call, because it is neither an
  acknowledgement nor rule-skipped. It costs a call and decides nothing, since the later member opens by rule.
- **An edit inside the settle window** removes the only rule signal of a rule-skipped message. The burst
  declines, and that member has no judgement. This is a stated limitation; hand-opening covers it.
- **A peer question sent as a bare reply** («كيف حليته؟»): the model sees no reply context, so the D7 tie-break
  applies. Such a message usually carries a rule signal and opens by rule anyway.
- **A message that is both an advert and asking:** the incident path is unaffected, and no question item opens
  from it.
- **Text shaped like an instruction** ("ignore the instructions…"): the worst outcome is an item a moderator
  dismisses. The model's output is a closed list; anything else is a recorded failure that opens nothing.
- **The opening switch is set but the attention instruction is blank:** no model item opens. This is the
  deployment consequence of removing the classification-sourced opener.
- **Historical TG-M5.1 items** keep their classification link. Every figure reports each era in its own rows,
  never pooled.
- **A dismissal with operator free text, or a legacy reason,** is counted under "other" in the breakdown.
- **A rule-opened peer question** dismissed as Member discussion still counts against rule precision, as every
  dismissal always has. The breakdown shows why.
- **Catch-up processing** produces no attention judgement and opens nothing.

## Requirements *(mandatory)*

### Functional Requirements

**Dismissal reasons and their figures (User Story 1; first, and deployable on its own)**

- **FR-301**: The system MUST let an operator dismiss an open item of any source as **"Member discussion"**.
  - It records the reason, who dismissed the item and when.
  - The status is dismissed.
  - It uses the same guarded write as every other dismissal, requires confirmation, and offers no bulk action.
- **FR-302**: The dismissal confirmation MUST state each reason's meaning:
  - **Not a real question:** not a question or request at all.
  - **Member discussion:** a real question or discussion between members; no moderator was needed.
  - **Message removed:** the operator's own judgement that the message is gone.
- **FR-303**: Every existing figure that counts dismissed items MUST keep counting every dismissal reason, with
  its definition unchanged:
  - unanswered and opened;
  - rule precision;
  - the classification question labels;
  - the model-opened questions, including the pilot gate (dismissed ÷ opened).
- **FR-304**: The rule baseline (per rule version) and the model-opened questions (per opening judgement's
  model and instruction, per era) MUST each show a per-reason breakdown beside the dismissal count:
  - the reasons are not a real question, member discussion, message removed, and other;
  - the parts MUST sum to the count;
  - the breakdown MUST NOT move any gate.
- **FR-305**: No screen or operator document may describe all dismissed items as "not a real question". Such
  wording MUST read "dismissed (any reason)", followed by the breakdown.
- **FR-306**: FR-301 to FR-305 MUST be deployable before, and independently of, every other requirement here.
  They need no schema change, no model and no switch.

**The attention judgement (User Stories 2 and 4)**

- **FR-307**: The system MUST offer a separate attention instruction, `attention_v1`, selected by its own setting.
  - The setting is blank by default; while it is blank, no attention call is made and nothing is recorded.
  - The instruction is pinned by its content hash.
  - A new wording is a new version.
  - *(2026-10-09)* Under Policy D′ the new version is `attention_v2`. `attention_v1` stays pinned and allowlisted
    as history.
- **FR-308**: The attention request MUST carry exactly what the classification request carries: the instruction
  and the message's first-posted, redacted words. No message text may be logged.
- **FR-309**: The attention judgement's output MUST be exactly one of six intents:
  - **`asking`:** the message reasonably needs an answer, action, clarification or decision from the team. That
    includes a question or request about the course's own service, a problem the writer still has with it, and a
    Policy S bare statement of the course's own arrangement. Being grammatically a question does not decide it,
    and neither does lacking a question mark.
  - **`discussion`:** a genuine question or prompt between members, about their own experience, work, answers or
    opinions, or about an outside institution.
  - **`informing`:** states information, including a member answering another member or a resolved status. A
    bare statement or complaint about an outside institution is `informing` (2026-10-09).
  - **`social`:** greetings, thanks, congratulations, wishes, or small talk with no question.
  - **`offering`:** offers or promotes a service, product, group or contact.
  - **`other`:** none of the above.

  *(Amended 2026-10-09, Policy D′.)* The earlier wording, which `attention_v1` states:
  - `asking`: "a question or request about the service, a problem the writer still has, and a Policy S bare
    course statement";
  - `discussion`: "about their own experience, work, answers or opinions".

  Needs-response MUST be true exactly when the intent is `asking`. That MUST be its single derivation, stored
  with the judgement and never recomputed elsewhere. There is no self-reported confidence.
- **FR-310**: Every label, every candidate wording and the dismissal reasons MUST follow **Policy D′**
  *(amended 2026-10-09, the operator's option (a))*:
  - **D0, the team's responsibility (new):**
    - The team answers for the course's own service and for course content.
    - The course's own service is its schedule and sessions, its tests and their arrangements, access, links,
      the platform, materials, recordings, registration and payment with the course, its certificates, and the
      group's rules.
    - An outside institution's service or process is not the team's: a university, a national testing or
      licensing body, a ministry or another government portal.
    - This holds even for the exams the course prepares students for. Their registration, appointments, results
      and licences belong to the outside body; what they test is course content.
  - **D1:** the expected answerer decides, not the addressee or the form.
    - A message is `asking` only when the team is reasonably expected to give the useful answer, action,
      clarification or authoritative guidance.
    - A question, a described problem, an education topic, or an address to the group ("does anyone know?") does
      not by itself make a message `asking`.
  - **D2:** a peer-addressed question about the course's own service is `asking`.
  - **D3:** a question between members whose useful answer comes from the members' own experience, work, answers
    or opinions, or from what members know of an outside institution (including help with an outside
    institution's site or system), is `discussion`.
  - **D4:** a member answering another member is `informing`.
  - **D5:** a peer-addressed problem check about the course's own service is `asking`.
  - **D6:** a course-content question with no addressee is `asking`, marked ambiguous.
  - **D7:** when it is unclear whether the team is needed, including whether the subject is the course's own
    service or an outside institution's, the label is `asking`.
  - **D8:** the model does not see reply context; this is a stated limitation.

  *(History.)* **Policy D (confirmed 2026-10-07)** governs `attention_v1` and its evidence. Its D1 had no "or the
  form" sentence. D2 and D5 had no "course's own" scope ("a peer-addressed service question", "a peer-addressed
  problem check"). D3 had no outside-institution clause. D7 read "when it is unclear whether the team is needed".
  There was no D0.
- **FR-311**: A message MUST be judged only if the classification would accept it (the same eligibility, with the
  same exclusion reasons). It MUST also be skipped, with the exclusion "rule opens", when its own first-posted
  words alone open rule set v1.
- **FR-312**: Each judgement MUST be recorded once and never updated or deleted, with no message text. It records:
  - the model profile, the instruction version and the model run;
  - the intent and the derived needs-response;
  - the path and the time.

  There MUST be at most one current judgement per message, and a replay MUST record nothing new.
- **FR-313**: Exclusions MUST be recorded once. Failures MUST be appended, each naming the model.
  - **Transient errors** MUST be retried at task level.
  - **Final errors** (truncated or invalid output) MUST be recorded and open nothing.
- **FR-314**: The attention and moderation judgements MUST be independent:
  - neither reads, waits for, or is ordered after the other;
  - each records and opens correctly when the other is absent, failed or late;
  - the opener's veto (FR-318) is the only exception.

  Concurrency and ordering are deployment policy. The current policy, Attention first when both need the same
  constrained inference lane, MUST be configuration, not part of the domain contract.
- **FR-315**: The attention judgement MUST use its own model role, with exactly one active profile.
  - Candidate profiles are registered inactive.
  - Existing profiles, including the larger model's, stay registered, and its model stays installed.
- **FR-316**: Judgements MUST be recorded whenever the attention instruction is configured and an attention
  profile is active, regardless of the opening switch (shadow).
- **FR-317**: Only live messages get attention judgements. Catch-up processing MUST record none and open nothing.

**Opening (User Story 3)**

- **FR-318**: The rule set MUST keep the first word. When it declines a burst and the opening switch is set, the
  opener MAY open a model item from the earliest burst member whose current judgement passes all of these:
  - it is live;
  - its needs-response is true;
  - it is within TG-M5.1's window: recorded after the switch, and no older than the maximum item age;
  - its message's current classification is neither advert nor abuse.

  Social chat MUST NOT be vetoed.
- **FR-319**: A model item MUST link to the judgement that opened it. Every model item MUST carry exactly one
  link, either this or, for TG-M5.1's historical items, the classification link. No other item may carry one.
- **FR-320**: A model item's anchor, start time, owner, closure, ageing and expiry MUST be TG-M3's and TG-M5.1's,
  unchanged.
- **FR-321**: A judgement that lands after its burst was judged MUST trigger re-judgement through TG-M5.1's
  existing mechanism, as part of recording the judgement. The burst MUST converge on one item within one sweep
  interval.
- **FR-322**: The classification-sourced opener MUST be removed, with no fallback. The classification's
  needs-response returns to measurement only. When the attention instruction is blank, no model item opens,
  even with the opening switch set.
- **FR-323**: The model MUST NOT close, dismiss, expire, re-date or re-attribute any item.

**Qualification (User Stories 5 and 6)**

- **FR-324**: The qualification MUST run per task (moderation or attention) over a named profile and a named
  instruction.
  - It writes nothing, and prints counts and line numbers, never text.
  - Its verdict is QUALIFIED, NOT QUALIFIED or INCOMPLETE.
  - A run naming a candidate wording file prints CANDIDATE and can never be QUALIFIED.
  - The existing moderation command keeps working.
- **FR-325**: The attention suite MUST gate:

  | Gate | Measures | Passes when |
  |---|---|---|
  | A1 | clear negatives model-opened, tuning sets | = 0 |
  | A2 | clear positives missed, tuning sets | = 0 |
  | A3 | validation set: clear negatives model-opened / rule-declined clear positives missed | ≤ 1 / ≤ 1 (*2026-10-09:* per validation set) |
  | A4 | held-out set, the same | ≤ 1 / ≤ 1, of at least 10 |
  | A5 | fresh sample, the same; required for QUALIFIED | ≤ 1 / ≤ 1 |
  | A6 | violations answered `asking` (with no credit for the veto) | ≤ 1, lines listed |
  | A7 | lines differing over 2 runs | 0 |
  | A8 | single-call 95th-percentile latency | ≤ 10 s |
  | A9 | errors | 0 |

  The per-message estimate for the host's serving mode MUST be reported: the sum of the two calls on a
  single-occupancy lane, the larger one on a concurrent lane.
- **FR-326**: The attention suite MUST report, never gate:
  - ambiguous lines;
  - intent agreement;
  - **asking vs discussion**: label asking answered discussion, label discussion answered asking, and peer lines
    correct of judged, each with line numbers;
  - **clear negatives rule-opened**, with peer lines counted apart;
  - **burst fixtures**: per line, the opener, the opening member and the expected result.
- **FR-327**: The fixtures MAY carry an intent, a peer flag, or a burst list.
  - **Intent:** it MUST be one of the six, and it MUST agree with the needs-response label; otherwise the run is
    INCOMPLETE.
  - **Peer flag:** every peer line in the repository's validation and held-out sets MUST be one that rule set v1
    declines, enforced by an automated check.
- **FR-328**: The moderation suite MUST keep 010's advert gates and add repeat and errors gates. It runs over
  `classify_v2` and the moderation profile.
- **FR-329**: The opening switch MAY be set on a host only when that host's active attention pair is QUALIFIED.
  Any change to the moderation pair MUST have a QUALIFIED moderation suite.
- **FR-330**: Wording selection MUST follow the plan's protocol (plan §8.3):
  - **The candidates:** three fixed before any run, sharing the intent definitions and Policy D verbatim.
  - **The matrix:** each runs on both development models with 2 repeats, against the tuning and validation sets.
  - **The decision rule, fixed beforehand:** the smallest model with any candidate passing A1–A3, A6, A7 and A9;
    among those, the generic wording first, then glossary, then probe-derived.
  - **Revision:** at most one, limited to the failing sentence, then a freeze.
  - **The stop condition:** if nothing passes, the milestone stops and reports.
  - *(2026-10-09)* **The second cycle, for `attention_v2`** (addendum §6.3–§6.4):
    - **The candidates:** each is `attention_v1.md` with its policy-bound sentences replaced by Policy D′'s,
      verbatim. They differ only in where D0 sits: V2-A in place, V2-B scope first, V2-C scope first with one
      generic contrast sentence.
    - **The decision rule:** the smallest model with any candidate passing A1, A2, A3 (every validation set), A6,
      A7 and A9; among those, V2-A, then V2-B, then V2-C.
    - **Revision:** at most one; a policy sentence is never revised.
    - **If nothing passes:** the cycle stops. `attention_v1` stays unqualified under D′, and opening stays
      rules-only.
- **FR-331**: The benchmark sets MUST include the following.
  - **A validation set,** written before the selection round:
    - about 40 synthetic lines on topics outside both the tuning and held-out vocabularies;
    - of which about 12 are rule-declined peer lines: at least 6 discussion negatives, 3 peer-addressed service
      positives, 1 peer problem check and 2 unaddressed course-content lines.
  - **A held-out set,** written only after the freeze and run once:
    - topics fixed in plan §9;
    - at least 10 rule-declined clear positives, at least 80% of lines without a question mark;
    - at least 3 rule-declined peer-discussion negatives and 2 peer-addressed positives.
  - **The operator's fresh sample:**
    - 20–30 real messages, labelled with intents before any run, kept outside the repository;
    - including peer discussion and peer-addressed service questions as they occur, aiming for at least 3 of each.
  - **About 8 burst fixtures,** reported only.
  - *(2026-10-09)* **For the second cycle** (addendum §6.1–§6.7):
    - **Tuning** gains `real-attention-fresh-v1.jsonl`: T077's 37-line sample, relabelled under D′.
    - **Validation** gains two sets:
      - the v1 held-out set, renamed `attention_heldout_v1_fixtures.jsonl`, byte-identical, with its hash pinned;
      - `attention_validation_scope_fixtures.jsonl`: about 18 rule-declined synthetic lines, written before any
        v2 candidate. It holds at least 6 outside-institution clear negatives, at least 4 own-service clear
        positives with the same surface words (at least 2 of them peer-addressed), at least 2 D7 lines and at
        least 1 exam-content line, the last two ambiguous.
    - **A new held-out set,** written only after `attention_v2` is frozen and run once:
      - at least 10 rule-declined clear positives on own-service topics, at least 2 of them peer-addressed;
      - at least 8 rule-declined outside-institution clear negatives, at least 4 `discussion` and at least 2
        `informing`;
      - at least 3 peer-discussion negatives;
      - at most 20% of lines with a question mark.
    - **A new fresh sample:** 20–30 real messages, none of them in T077's sample, labelled under D′ before any
      run.
- **FR-332**: Benchmark labels MUST NOT be changed by the system or the implementer. Disputed labels MUST be listed
  for operator review.
- **FR-333**: Validation results MUST NOT be seen before the held-out topics are fixed, and held-out results MUST
  NOT be seen before the freeze.
  - *(2026-10-09)* The second cycle's held-out topics are fixed in addendum §6.6, before any v2 candidate:
    - outside institutions: embassy or visa, degree equivalency, the labour office, civil service;
    - the course's own service: subscription, discount code, question bank, simulated test.

    No validation or tuning file in the repository may carry them.

**Measurement (User Stories 2, 3 and 7)**

- **FR-334**: The panel MUST show, per attention model and instruction:
  - each eligible message's status: judged, excluded by reason, failed, or not yet;
  - judgements by intent;
  - the share of judgements landing before their burst's settle.
- **FR-335**: The panel MUST show operator-added items split two ways:
  - by their anchor's attention status: judged asking, judged non-asking by intent, excluded by reason, failed,
    or none;
  - by whether the anchor's sender posted another message in the same chat and thread within the burst gap.
- **FR-336**: The model-opened questions MUST be grouped by the opening judgement's model and instruction, with
  TG-M5.1's classification-opened items in their own rows, never pooled.
- **FR-337**: The panel MUST read stored values only. It MUST compute no state, gate, eligibility or derivation,
  and show no average, composite score or percentage.

**Invariants**

- **FR-338**: Nothing in TG-M3's rule set (literals, conditions, rule version), bursts, settle window, edits,
  attribution, matching or ageing may change. The same holds for `classify_v2`, routing, thresholds, incidents,
  TG-M4, the gateway, redaction and the first-posted-text behaviour.
- **FR-339**: No burst-level input may reach any model. L-B1 MUST be documented as a limitation of the opening
  contract.
- **FR-340**: The schema change MUST be one additive revision that every existing row satisfies. It is
  forward-only once judgements exist.
- **FR-341**: Every automated check MUST pass with no model runtime.

### Key Entities

- **Attention judgement**: one message's immutable intent.
  - It carries the derived needs-response, the model profile, the instruction version, the model run, the path
    and the time.
  - At most one is current per message, and it holds no text.
- **Attention attempt**: an exclusion (with its reason, including "rule opens") recorded once, or a failure
  (with its kind and model) appended.
- **Attention instruction version**: a named, hash-pinned instruction text, selected by its own setting and kept
  apart from the classification instructions.
- **Model profile (attention role)**: a model configuration for this task only. Candidates are inactive, and one
  is active per deployment.
- **Attention item**: TG-M3's item. A model item now links either to an attention judgement (TG-M5.3) or to a
  classification (TG-M5.1 history), never both. The dismissal reason gains member discussion.
- **Benchmark set**: labelled lines.
  - **Keys:** a label class and a tracked disposition, plus, from this milestone, an intent, a peer flag or a
    burst list.
  - **Kinds:** tuning, validation, held-out, fresh sample, burst.
- **Qualification result**: one task and pair's per-set counts, line lists, gate verdicts, reported lines and
  latency.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-301**: On a fixed scenario with dismissals of every reason:
  - every existing dismissal-based figure has the same value before and after User Story 1;
  - each per-reason breakdown sums to its count;
  - no screen describes all dismissals as "not a real question".
- **SC-302**: On the qualified attention pair:
  - **tuning sets:** 0 clear negatives model-opened and 0 clear positives missed;
  - **validation set:** at most 1 of each (*2026-10-09:* in each validation set);
  - **held-out set:** at most 1 of each, of at least 10 rule-declined clear positives;
  - **fresh sample:** at most 1 of each.

  The peer-discussion negatives and peer-addressed positives count in these totals.
- **SC-303**: On the qualified attention pair, at most 1 violation line is answered `asking`.
- **SC-304**: Two runs on the qualified pair give identical per-line results. There are 0 errors, and the
  95th-percentile single call is at most 10 seconds.
- **SC-305**: The moderation suite on `classify_v2` and the development moderation profile gives the same
  per-line results before and after this milestone.
- **SC-306**: In shadow, under normal load, at least 95% of live attention judgements land before their burst's
  90-second settle.
- **SC-307**: In the pilot, model-opened items dismissed for any reason are at most 10% of the first 30 or more
  model-opened items, with the per-reason breakdown reported. Above that, the switch is blanked, and nothing
  recorded changes.
- **SC-308**: With either model unavailable, 100% of rule-signalled questions still open, and the other
  judgement still records.
- **SC-309**: Every qualification run reports the asking-vs-discussion line, the rule-opened negatives and every
  burst fixture's opener.
- **SC-310**: Every automated check passes with no model runtime. The hashes of `classify_v1` and `classify_v2`
  are unchanged. Every earlier milestone's suite keeps its outcome, apart from the asserted dismissal wording and
  breakdown shape.

## Assumptions

- **Operator prerequisites, before qualification (not before planning):**
  - T031's annotations of the external attention sets: ambiguous lines, real moderation #1 tracked as
    no-link-rule, and intent plus peer flags on peer lines;
  - the fresh sample.
- **The development host:**
  - the moderation side stays on the small model with `classify_v2`;
  - attention candidates are measured on the small model first, with the larger model as the fallback;
  - the same model for both tasks is preferred in development only because of the host's memory. The design
    allows a different model per task.
- **The thresholds:**
  - A6 is ≤ 1 and A8 is ≤ 10 seconds (plan decision 7, proposed values fixed here);
  - the pilot threshold of 10% over at least 30 model-opened items is TG-M5.2's SC-206, unchanged.
- **The revision number** is the next free one after `0007`. The roadmap's reservation table is updated.
- **Retries** reuse the classification's attempt limit and backoff.
- **The rule skip:** most rule-opened members are skipped, so the attention model's agreement on rule-opened
  questions comes from the benchmark, not production. The page says so.
- **The illustrations** in this spec are the operator's synthetic examples, not real messages.

## Out of Scope

- Burst-level model input, and reply context as model input.
- Rule-side handling of peer questions: a rule version 2 condition is a TG-M3 change and its own milestone, decided
  from the member-discussion count.
- Any change to `classify_v2`, routing, thresholds, incidents, TG-M4 or TG-M3's rule set.
- The deterministic no-link rule.
- A prompt registry or prompt-versions store. It is reserved for the assessment milestones.
- Fine-tuning, model chaining, and provisioning the production host.
- Catch-up attention judgements, and reprocessing (TG-M8).
- Activating any model, instruction or switch in production. That is an operator action after qualification.
