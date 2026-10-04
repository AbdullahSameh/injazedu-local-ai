# Feature Specification: TG-M5.2 — classify_v3 and Model Qualification

**Feature Branch**: none created. Git is operator-owned (constitution IV), so the work sits on
`m5/ai-classification`.
**Created**: 2026-10-04
**Status**: Draft
**Input**: "Based on this session and the `docs/plan/telegram/tg-m5-classify-v3-plan.md` plan, start specifying
TG-M5.2." That is the operator's request of 2026-10-04. The plan of record is
`docs/plan/telegram/tg-m5-classify-v3-plan.md`: root cause §1–§4, decisions §5, tuning outcome §14, options §15,
and the larger-model measurement §16.

## Provenance — why this milestone exists

- **TG-M5** recorded one immutable prediction per message from one instruction. Its needs-response judgement was
  measurement only.
- **TG-M5.1** let a live prediction open an Attention item when the rule set declined the burst. Its benchmark
  (009 research, Finding 9) showed that the active instruction reads an *announcement* as a *question*.
- **Root cause, measured** (plan §1–§2): `classify_v1` and `classify_v2` decide needs-response by **topic**,
  never by **function**:
  - each question category is described by a list of topics;
  - needs-response follows from the category;
  - the only explicit "no response" path is the purely social category.

  On the operator's paired benchmark, 12 of 20 clear informing or resolved-status statements would have opened
  an item under v2. Each one is moderator work, and if nobody dismisses it, it becomes a permanent "unanswered"
  (TG-M3 G3).
- **The wording can be fixed** (plan §4). A wording that separates *asking* from *informing* removes every
  clear false positive. On the current small model (2B effective), the same wording moves the advert boundary,
  because one prompt carries both policies. After three tuning rounds, no wording met both sides (plan §14).
- **A larger model holds both** (plan §16). On a 7.5B model, the same wording opens 0 of 27 clear negatives,
  misses 0 of 13 clear questions, and gets 64/64 on the synthetic policy set with no legitimate message opened as
  an incident. Two boundary cases remain on the real and shipped advert sets (FR-212).
- **The operator's direction** (2026-10-04): production will run on a powerful host, and the system must not
  rely solely on small models. TG-M5.2 therefore freezes **one** new instruction and makes the production
  **model** something that is **qualified on evidence**, not assumed.

**What it changes:**
- a new opt-in instruction, `classify_v3`;
- a repeatable qualification procedure;
- a held-out benchmark;
- the rule that AI-assisted Attention goes live only on a qualified model-and-instruction pair.

**What it keeps:** everything else. That includes TG-M5.1, the rule set, the schema, the taxonomy, routing,
thresholds, the gateway, redaction and immutability.

## Clarifications

### Session 2026-10-04

- **Q: How is a short, bare statement treated, such as «الاختبار اليوم» or «في محاضرة اليوم»?** A: **Policy S.**
  - A member's short statement of a course arrangement, with nothing added, is a potential implicit question.
    It needs a response and may open Attention.
  - If it is not really a question, the moderator dismisses it ("Not a real question").
  - Avoiding missed real questions is preferred over avoiding every ambiguous false positive.
- **Q: Which messages must stay "no response"?** A: **Clear informing and resolved-status statements**, such as
  «الاختبار اليوم الساعة 7», «الموعد تغير وصار الخميس», «المنصة رجعت تشتغل عندي طبيعي» and «الكتاب وصلني
  اليوم».
- **Q: How do ambiguous benchmark cases count?** A: They are **reported separately** and are never a hard
  production pass or fail.
- **Q: May benchmark labels be corrected?** A: **Never silently.** Disputed labels are flagged for operator
  review.
- **Q: One call per message, or a separate needs-response call?** A: **One call.**
  - The separate-call design (plan §15 Option B) works around a small model's limit by adding a second call
    and a schema change to every deployment.
  - Production will run on a powerful host, and the larger-model measurement already passes the Attention side
    with one call.
  - Option B is reconsidered only if no production-class model qualifies (FR-216).
- **Q: Which model runs in production?** A: **Whichever candidate passes qualification on the production host**
  (FR-206–FR-210). The development machine keeps its current model and instruction.
- **Q: How do the two known advert-side boundary cases count?** They are the real outside-programme
  announcement and the shipped synthetic insulting accusation. A: **Option A: tracked exceptions, with
  guardrails** (FR-212).
  - They are reported on every run but do not fail qualification.
  - The list is closed: any other advert-side regression fails.
  - Each exception expires: the accusation's on the operator's label review (ABUSE confirmed makes it a hard
    gate), the announcement's when the deterministic no-link rule ships.
  - Measured basis: on the 7.5B model with the candidate wording, the accusation comes back as a complaint
    needing a response, so the model still opens an Attention item and moderators see it. The announcement
    fails under every informing-aware wording on both models, and the no-link rule is its intended control.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — A statement that informs no longer opens an Attention item (Priority: P1)

A member posts that the live session is tonight at 8, that the platform works again for them, or that the
book reached them today. With `classify_v3` on a qualified model, the prediction records needs-response false,
and no item opens. Before this milestone, most such messages opened an item that a moderator had to dismiss.

**Why this priority**: Every false positive is unnecessary moderator work and damages the moderator's
response figures. It is the reason AI-assisted Attention cannot go to production yet.

**Independent Test**: Run the qualification on the clear-negative fixtures. Count model-opened items on
expected-false lines.

**Acceptance Scenarios**:

1. **Given** a message that supplies the answer itself (a time, day, place, deadline or where to find it),
   **When** it is classified, **Then** needs-response is false and no item opens.
2. **Given** a message that reports a solved problem or confirms receipt, **When** it is classified, **Then**
   needs-response is false.
3. **Given** a message that passes on what was announced, or comments on how something went, **When** it is
   classified, **Then** needs-response is false.

---

### User Story 2 — Implicit questions are still caught (Priority: P1)

A member writes a bare statement with no question mark, for example "the exam today". Under Policy S this is a
check. The prediction records needs-response true, and when the rules decline, the model opens an item.
Unresolved problems ("the content shows incomplete for me") and requests are caught too.

**Why this priority**: TG-M5.1 exists to catch questions the rule set cannot see. Fixing false positives must
not cost real questions.

**Independent Test**: Run the qualification on the clear-positive fixtures, separately on those the rule set
declines. Report the ambiguous set's "answered true" count on its own.

**Acceptance Scenarios**:

1. **Given** a request or an unresolved problem with no rule-set signal, **When** it is classified, **Then**
   needs-response is true and the model opens the item.
2. **Given** a bare statement of a course arrangement with nothing added, **When** it is classified, **Then**
   needs-response should be true under Policy S. The result is reported, never gated.
3. **Given** a message that informs and also asks or reports a remaining problem, **When** it is classified,
   **Then** needs-response is true.

---

### User Story 3 — Advert and abuse detection is preserved (Priority: P1)

The same prediction decides whether a message breaks the group's rule. Changing the instruction or the model
must not let adverts through, and must not open incidents on legitimate questions.

**Why this priority**: TG-M5 and the `classify_v2` work established the violation side on real
moderator-removed messages. A regression there costs more than the Attention gain.

**Independent Test**: Run the qualification on the real and synthetic moderation sets with the same model and
instruction. Compare against `classify_v2` on the current model.

**Acceptance Scenarios**:

1. **Given** the operator's real moderator-removed messages, **When** they are classified, **Then**
   needs-moderation matches, except for the tracked boundary cases (FR-212).
2. **Given** the synthetic policy set, **When** it is classified, **Then** at most one violation is missed,
   no legitimate message is flagged, and none is routed to an incident.

---

### User Story 4 — The operator qualifies a model on any host before switching on (Priority: P1)

On the powerful production host, the operator pulls a candidate model, registers it as an inactive moderation
profile, and runs one qualification command naming the profile and the instruction. The command prints, per
benchmark set:
- counts and line numbers, never text;
- clear-labelled results;
- ambiguous results, separately;
- the advert-side results;
- latency.

It writes nothing. The operator switches on only a pair that passed.

**Why this priority**: Production will not run on the development machine's model. Without a repeatable
qualification, the production model would be chosen by assumption.

**Independent Test**: Run the qualification for an inactive profile and confirm it writes no row, prints no
text, and reports every gate line.

**Acceptance Scenarios**:

1. **Given** an inactive moderation profile and a named instruction, **When** the operator runs the
   qualification, **Then** every benchmark set is evaluated with that pair, and the gate lines show pass or
   fail.
2. **Given** a run on the same pair twice, **When** the results are compared, **Then** they are identical.
3. **Given** a pair that fails any hard gate, **When** the operator reads the report, **Then** it says which
   gate failed, with line numbers.

---

### User Story 5 — The result is checked on cases nobody tuned against (Priority: P2)

After the `classify_v3` wording is frozen, a held-out synthetic set is written from a grid fixed in advance. It
covers new topics, both dialects, messages without question marks, and near-pairs. It is run once. The operator
also labels a fresh sample of real messages, kept outside the repository, that nobody looked at while writing
the instruction.

**Why this priority**: The tuning sets shaped the wording. Only unseen cases show whether it generalises.

**Independent Test**: Confirm the held-out set was created after the frozen instruction's hash, contains no
real text, and is reported as run, with no further edits to the instruction.

**Acceptance Scenarios**:

1. **Given** the frozen instruction, **When** the held-out set fails a gate, **Then** the failure is
   reported. The instruction is not edited to pass, and any new wording is a new version with a new held-out
   set.

---

### User Story 6 — Known boundary cases are tracked, not hidden (Priority: P3)

Two advert-side cases failed under every informing-aware wording or on the larger model:
- an outside programme announcement on the real set;
- an insulting accusation on the shipped synthetic set, labelled abuse, which the larger model reads as a
  complaint.

Each is listed with a disposition, and the qualification report shows them on their own line.

**Why this priority**: They decide whether the advert gate can pass at all. Treating them silently either way
would be a decision made in secret.

**Independent Test**: The qualification report lists each tracked case and whether it passed.

**Acceptance Scenarios**:

1. **Given** a tracked boundary case, **When** qualification runs, **Then** its result appears on the
   tracked-cases line, and it counts toward the gate only as FR-212 states.

### Edge Cases

- **A message that informs and also asks** (it arrived, but a part is missing) is a question.
- **Something worked, then stopped again**: a remaining problem, so a question.
- **A question wrapped in a greeting or thanks** is still a question. A purely social message is never one.
- **A detailed statement that ends with a tag** asking for confirmation ("…, right") is a question.
- **An informing message about something from outside the course** is still judged by the group's rule.
  Informing never makes a promotion acceptable.
- **A candidate model that passes the Attention side but fails the advert side** (or the reverse) is not
  qualified.
- **A candidate model too slow** for predictions to land within the 90-second settle under normal load is not
  qualified for live use.
- **Switching the instruction or the model** revisits nothing. Each prediction keeps the model and instruction
  it was made with, and every figure stays split by both.
- **Catch-up classification** stays measurement only under any instruction or model.
- **`classify_v3` on the development model** is not qualified. The development configuration stays as it is
  (Assumptions).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-201**: The system MUST offer a third instruction, `classify_v3`, as an opt-in value of the existing
  instruction setting.
  - The default instruction MUST stay `classify_v1`.
  - `classify_v1` and `classify_v2` MUST stay byte-identical.
  - The new instruction MUST be pinned by its content hash like the others.
- **FR-202**: `classify_v3` MUST decide needs-response by what the writer wants, not by the topic:
  - **Asking:** a question; a request; a problem the writer still has; or, under Policy S, a bare statement of
    a course arrangement with nothing added.
  - **Informing:** the message supplies what an asker would need; passes on what was announced; says how
    something went; confirms that something arrived, appeared or works for the writer; or says a problem is
    solved.
  - **Mixed:** a message that informs and also asks or reports a remaining problem is asking.
  - The absence of a question mark MUST NOT decide either way.
- **FR-203**: `classify_v3` MUST keep the seven categories, the five reported values and taxonomy version 1. An
  on-topic message that only informs MUST have a place in the existing categories: the residual category, or
  the social one when it is only social.
- **FR-204**: `classify_v3` MUST keep `classify_v2`'s group rule, advert, abuse and needs-moderation wording.
  It MUST keep verbatim the sentence that needs-response is always false for adverts, abuse and social messages,
  because TG-M5.1's gate rests on it.
- **FR-205**: `classify_v3` MUST NOT quote benchmark text or mirror fixture-specific nouns. It MUST stay
  within about 1,000 characters of `classify_v2` (plan §6, principles 6–7).
- **FR-206**: A qualification command MUST evaluate a **named model profile** (active or not) with a **named
  instruction** over every benchmark set:
  - the real attention sets;
  - the shipped synthetic attention set;
  - the held-out set;
  - the real and synthetic moderation sets.

  It MUST print counts and line numbers only, never message text, and MUST write nothing.
- **FR-207**: The qualification MUST report, separately:
  - clear-positive and clear-negative results;
  - ambiguous results;
  - rule, model and nobody opener counts by label;
  - category agreement (secondary);
  - the advert-side figures;
  - the tracked boundary cases;
  - median and 90th-percentile classification time.

  Ambiguous results MUST NOT count toward pass or fail.
- **FR-208**: A pair MUST be **qualified** only when it meets every hard gate:
  - clear negatives model-opened: 0 on the tuning sets, at most 1 on the held-out set;
  - clear positives missed: 0 on the tuning sets, at most 1 of the rule-declined ones on the held-out set;
  - advert side no worse than `classify_v2` on the current model, as FR-212 states;
  - identical results on two runs;
  - the operator's fresh real sample: at most 1 model-opened clear negative and at most 1 missed rule-declined
    clear positive;
  - predictions landing within the settle window under normal load.
- **FR-209**: The held-out set MUST be written only after the `classify_v3` wording is frozen. It MUST contain
  only synthetic or sanitised text and follow the grid fixed in plan §9:
  - new topics;
  - Saudi and Egyptian phrasing;
  - messages without question marks;
  - near-pairs;
  - rule-declined clear positives;
  - mixed, relapse and social-wrapped cases.

  It MUST be run once per frozen version. A held-out failure MUST NOT lead to editing that version.
- **FR-210**: AI-assisted Attention MUST NOT be switched on for a production group unless that group's model and
  instruction pair is qualified. After switch-on, the pilot is controlled by the model-opened dismissal rate (SC-206).
- **FR-211**: Benchmark labels MUST NOT be changed by the system or the implementer. Disputed labels MUST be
  listed for operator review, with the case's line number and the reason.
- **FR-212**: The two known advert-side boundary cases MUST be tracked by name in the qualification:
  - the real outside-programme announcement;
  - the shipped synthetic insulting accusation.

  They are **tracked exceptions**: reported on their own line in every qualification report, but never failing
  qualification. Three guardrails apply:
  - **A closed list.** Exactly these two cases, named by set and line. Any other missed violation, and any
    legitimate message flagged or routed to an incident, fails qualification.
  - **Reported every run,** with pass or fail shown.
  - **Each exception expires.**
    - The accusation's exception ends when the operator reviews its label. If ABUSE is confirmed, it becomes a
      hard gate.
    - The announcement's exception ends when the deterministic no-link rule ships.
- **FR-213**: Changing the instruction or the model MUST revisit nothing:
  - each prediction keeps its model and instruction version;
  - every figure stays split by both;
  - catch-up stays measurement only.
- **FR-214**: Nothing in TG-M5.1's opening, reconciliation, timing, attribution or switch may change. The same
  applies to TG-M3's rule set, the schema and migrations, the routing, the thresholds, the gateway, the
  redaction boundary and the first-posted-text behaviour.
- **FR-215**: The control panel MUST need no change. Figures already split by model and instruction version.
- **FR-216**: If no production-class model qualifies with `classify_v3`, the milestone MUST stop and propose
  a separate needs-response judgement (plan §15 Option B) as its own specification, not change the schema here.

### Key Entities

- **Instruction version**: a named, hash-pinned instruction text (`classify_v1`, `classify_v2`,
  `classify_v3`). It is selected by setting and stored on every prediction.
- **Model profile (moderation role)**: a named model configuration. Candidates are registered inactive, and
  exactly one is active per deployment. Every prediction records its profile.
- **Benchmark set**: labelled messages, each case with an expected needs-response and optionally a category or
  needs-moderation.
  - Each case has a **label class**: clear positive, clear negative or ambiguous.
  - Real sets live outside the repository; synthetic and held-out sets live inside it.
- **Qualification result**: for one model and instruction pair, the per-set counts, line lists, tracked
  boundary cases, latency figures, and a pass or fail on each hard gate.
- **Tracked boundary case**: a named benchmark line with its disposition, either a deferred milestone or
  operator label review.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-201**: On the qualified pair, **0 of the 20** clear informing or resolved-status messages in the
  operator's two real attention sets would open an item, and **at most 1** on the held-out clear negatives.
  `classify_v2` on the development model opens 12 of those 20.
- **SC-202**: On the qualified pair, **no** clear question in the tuning sets is missed. On the held-out set,
  **at most 1 of 10 or more** rule-declined clear questions is missed.
- **SC-203**: On the qualified pair, the advert side is no worse than `classify_v2` on the development model:
  - the real moderator-removed set fully matched, apart from FR-212's tracked cases;
  - the synthetic policy set with at most 1 missed violation, no legitimate message flagged, and none routed to
    an incident.
- **SC-204**: Two consecutive qualification runs on the same pair produce identical per-line results.
- **SC-205**: On the operator's fresh real sample of 20–30 messages, at most 1 clear negative is model-opened
  and at most 1 rule-declined clear question is missed.
- **SC-206**: In the production pilot, at most **10%** of model-opened Attention items are dismissed as not a
  real question, over the first 30 or more model-opened items. Above that, the switch is blanked, and nothing
  already recorded changes.
- **SC-207**: Under normal load, **95%** of live predictions on the qualified pair land before their burst's
  90-second settle.
- **SC-208**: Every automated check passes with no model runtime. The hashes of `classify_v1` and
  `classify_v2` are unchanged.

## Assumptions

- **The production host** can run at least a 7.5B-class model alongside the stack, and probably larger.
  Candidates are chosen and qualified on that host. The 16 GB development machine runs the 2B-effective model
  and cannot test 12B-class models.
- **The development configuration stays** `classify_v2` on the current model. The measured 7.5B profile stays
  registered and inactive as the mid-tier reference.
- **Starting draft:** the frozen wording starts from the measured probe P2 (plan §4), with fixture-specific
  nouns replaced by generic terms (FR-205). It is re-measured before freezing.
- **The tuning sets** are the operator's two real attention sets and real moderation set, kept outside the
  repository, plus the shipped synthetic attention, moderation and policy sets.
- **The fresh real sample** is the operator's: labelled before any run, kept outside the repository, and never
  used for tuning.
- **Disputed labels** already identified (plan §13 and §16) go to operator review:
  - the paired set's ambiguous lines and #19;
  - the original set's #11 and #13;
  - the shipped moderation set's #11.
- **The pilot dismissal threshold** (10%) and the settle-window latency target come from the plan's recommended
  gate (plan §10).

## Out of Scope

- A separate needs-response call, a second judgement record, or any schema change (plan §15 Option B; see
  FR-216).
- The deterministic no-link rule. It stays its own milestone.
- Changes to TG-M5.1, TG-M3's rule set, the taxonomy, routing, thresholds, the gateway, redaction or the
  first-posted-text behaviour.
- Fine-tuning a model, or chaining a small and a large model.
- Control-panel changes.
- Activating any model or instruction in production. That is an operator action after qualification.
