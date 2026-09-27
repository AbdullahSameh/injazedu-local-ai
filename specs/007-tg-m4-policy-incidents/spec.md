# Feature Specification: TG-M4 — Policy Incidents

**Feature Branch**: `m4/policy-incidents` *(operator-created; see Principle IV)*
**Spec Directory**: `specs/007-tg-m4-policy-incidents`
**Created**: 2026-09-24
**Status**: Draft
**Milestone**: TG-M4 (fifth milestone of `docs/plan/telegram/telegram-moderation-intelligence.md` §25)
**Input**: User description: "read docs/plan/telegram/telegram-moderation-intelligence.md and check the docs/runbooks/tg-operator-prere quisites.md, the start specify Milestone number 4 "Policy incidents""

## Overview

TG-M3 answered the first half of the business problem: *a student asked, and this long passed before a
moderator answered.* TG-M4 answers the second half: **a message broke the group's rules, and this is
what the moderators observably did about it, who did it, and when.**

The second half is much harder to be honest about than the first, for one reason the platform imposes:
the commonest way a moderator deals with spam — deleting it — is invisible. The platform reports no
deletion in a group and never says who deleted anything. A design that wanted a "time to removal"
figure would have to invent it. This milestone refuses to. It measures only what the platform actually
attributes, with a named actor and the platform's own timestamp: a moderator's reply to the offending
message, a moderator's reaction on it, and the removal or restriction of the sender — which the
platform reports together with who performed it. Everything else is an operator's statement, recorded
as a human act and never dressed up as an observation.

From that evidence comes a lifecycle governed by one rule that carries the whole milestone: **seeing is
not acting.** A reply or a reaction proves a moderator saw the message; it moves the incident to
*acknowledged* and never further. Only enforcement against the sender, or an explicit human
confirmation, *resolves* it. Because those are different claims they are measured as different
numbers — acknowledgement time, handling-confirmation time and observed-enforcement time — each from its
own evidence, each with its own sample count, and never folded into one.

Six things ship:

1. **An operator can open an incident on any stored message, and it is dated twice.** Once from when the
   message was posted, taken from the platform's clock, and once from when it was flagged. The distance
   between the two is the system's latency — in this milestone, the operator's — and is kept as a
   separate figure that is never charged to a moderator. The moderator responsible is the one who owned
   the group when the incident was flagged, resolved from ownership history and written onto the
   incident, exactly as TG-M3 did for questions.
2. **What moderators observably do becomes typed, attributed, timestamped evidence.** Removals and
   restrictions of members, reactions by moderators, and moderators' direct replies are recognised as
   evidence as they arrive — whether or not an incident exists yet — in an append-only trail that is the
   audit record of every incident.
3. **A lifecycle that cannot be argued with.** Open, acknowledged, resolved, or closed as a false
   positive. An incident can go straight from open to resolved — a ban needs no prior reply. Every
   transition is the same guarded, write-once step; nothing ever leaves a terminal state; and no
   transition is ever driven by an inferred deletion, by the absence of evidence, or by the passage of
   time.
4. **An operator can confirm what the platform cannot see, and can withdraw a false accusation.** They
   can acknowledge, resolve with a note — which is how a silent deletion a moderator reports gets
   recorded, as the operator's statement — or close the incident as a false positive with a reason.
   False positives are the labelled negatives that TG-M5 will need, and they leave every handled and
   missed figure entirely.
5. **One screen answers six questions about any incident**: what happened, when each step happened, why
   it was flagged, who handled it, how long each step took, and whether it was corrected — beneath a
   standing statement that the platform does not report deletion in groups.
6. **Three timings, separately named, and handled versus missed — all reproducible by hand.** Every
   figure is a definition written once and shared; no average and no composite score appear anywhere.

TG-M4 still **calls no model and sends nothing.** No message is recognised as a violation automatically,
no alert fires, and the bot never bans, restricts, deletes, reacts or posts — the evidence this milestone
measures is always somebody else's act, which is precisely what makes it evidence. Both silence
guarantees from TG-M1 continue to hold and continue to be tested. Every figure TG-M3 defined is left
exactly as it was: a reaction still closes no question.

The smoke test runs in the **development group**, not the live pilot: the operator runbook's §C row for
this milestone asks for a disposable third account in the dev group that the operator is willing to ban.

## Clarifications

### Session 2026-09-24

- Q: Evidence can be strictly after the message was posted but before the operator flagged it — the spammer was banned at 10:04, the incident opened at 10:10 — and every moderator timing is measured from the flagging moment, so it would read −6 minutes. Does it count, and how is its timing reported? → A: It counts. Opening an incident evaluates the evidence already recorded through the **same** matcher as evidence that arrives later, so the incident opens directly in the state that evidence implies, with the real actor. For each of the three timings, an incident whose earliest evidence of that kind precedes the flagging moment is reported in a separate **"acted before flagging"** count shown beside that timing, and contributes no value to its middle, slow end or slowest figure. Rationale: it mirrors TG-M3's first clarification — one matcher, two entry points — and loses nothing: the moderator who acted before anyone flagged the message is credited in the state, the actor and the handled count, while the distributions contain only durations that actually mean "time from flagging". Recording zero was rejected because it flatters the middle figure with values that are not response times; ignoring the evidence was rejected because it leaves already-handled incidents open until they are counted as missed.
- Q: The source plan snapshots an incident's category and severity from the model's classification, which does not exist until TG-M5. When an operator opens an incident by hand, what is recorded? → A: Both a **category** — spam or advert, abuse, or other — and a **severity** — low, medium or high — required at opening, taken from the source plan's own taxonomy (D-TG-08) and recorded as operator-assigned. Rationale: the incidents screen's category and severity filters work from the first day; TG-M5 inherits labelled examples in the vocabulary it will itself predict; and the alert milestone, which the source plan allows to run on hand-opened incidents alone, can route them by severity. The cost is two choices per incident. The labels are not edited in this milestone: a wrong flag is closed as a false positive, and correcting a label is TG-M8's review path.
- Q: The source plan's literal definition counts an incident as handled whenever it is resolved, so an incident resolved at hour 30 of a 24-hour ceiling moves from missed to handled and a past period's handled share rises after the fact. Is a late resolution handled or missed? → A: **Missed.** Handled means resolved *within* the age ceiling, judged by the resolution evidence's own moment, so each incident's outcome is settled once its window closes and never changes afterwards. The incident's state still becomes resolved when the evidence arrives, and how late it was remains visible in its timings. Rationale: TG-M3 built every figure so that a past period's numbers never move; a handled share that improves retroactively whenever a moderator finally acts is a number the team learns to argue with. The one exception is written down rather than hidden: evidence *dated* inside the window but *processed* after it — a capture backlog — corrects the record, because the outcome follows the platform's timestamp, not the processing order.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - An operator flags an offending message, and the incident is dated both when it was posted and when it was flagged (Priority: P1)

An operator sees a competitor's advert in a measured group and opens an incident on that message from the
control panel, choosing its category and severity. The incident records when the advert was posted, from
the platform's own timestamp, and separately when the operator flagged it. It records who opened it, the
labels the operator chose, and the moderator who owned the group at the moment it was flagged. It opens
once: flagging the same message again is refused rather than creating a second incident. If a moderator
had already banned the sender or reacted to the advert before the operator flagged it, the incident opens
already in the state that evidence implies.

**Why this priority**: Nothing else in the milestone exists without an incident to attach evidence to. And
the two timestamps are the milestone's first defence against an unfair number: if the flagging moment
were used as the posting moment, the operator's own delay would vanish; if the posting moment were used
for the moderator timings, every minute the operator took to notice would be billed to a moderator.

**Independent Test**: With a controlled clock and no network, open incidents against stored messages:
one ordinary message, the same message twice, a service announcement, a message from a bot account, a
message in a group with no owner at the flagging moment, and a message in a group whose ownership changes
afterwards. Confirm one incident per message, both moments recorded correctly, the refusal on the second
attempt, and the recorded responsible moderator unmoved by the later reassignment.

**Acceptance Scenarios**:

1. **Given** a stored message in a measured group, **When** an operator opens an incident on it, **Then**
   exactly one incident exists, its posting moment is the message's platform send timestamp, its
   detection moment is when it was opened, it is marked as operator-opened, and the opening panel account
   is recorded.
2. **Given** a message that already anchors an incident, in any state, **When** an operator tries to open
   another on it, **Then** they are prevented and no second incident exists.
3. **Given** two groups whose messages happen to share the same platform message number, **When** an
   incident is opened on one of them, **Then** the other remains free to anchor its own incident.
4. **Given** a group with a primary owner at the detection moment, **When** an incident opens, **Then** that
   owner is recorded as the responsible moderator; **and given** a group with no owner at that moment,
   **Then** the responsible moderator is absent and the incident is visible as unassigned.
5. **Given** an incident has opened, **When** the group's ownership is reassigned afterwards, **Then** the
   incident's responsible moderator has not changed.
6. **Given** a service announcement such as a member joining, **When** an operator tries to open an
   incident on it, **Then** they are prevented.
7. **Given** a message posted by a bot account — the commonest source of spam — **When** an operator opens
   an incident on it, **Then** the incident opens normally.
8. **Given** a message that already anchors a waiting question from TG-M3, **When** an operator opens an
   incident on it, **Then** the incident opens and the question item is left exactly as it was.
9. **Given** a waiting question on the Live Attention Queue, **When** the operator chooses to open an
   incident from that row, **Then** the incident opens against the question's anchoring message.
10. **Given** an operator opening an incident, **When** they submit without choosing a category and a
    severity, **Then** the incident is not opened; **and when** they choose both, **Then** both are recorded
    on the incident as operator-assigned.
11. **Given** the sender was banned after posting but before the operator flagged the message, **When** the
    incident opens, **Then** it is already resolved, with the ban's performer and moment recorded, and its
    observed-enforcement time is reported as "acted before flagging" rather than as a negative or zero
    duration.
12. **Given** a moderator reacted to the message before it was flagged, **When** the incident opens,
    **Then** it is already acknowledged, with that moderator and moment recorded.

---

### User Story 2 - A moderator's reply or reaction records that the message was seen — and never that it was dealt with (Priority: P2)

A moderator reacts ✅ to the advert, or replies to it directly. The incident moves to *acknowledged*, with
the moment taken from the platform's timestamp and the moderator named. It does not resolve, however many
replies and reactions follow, because a reaction proves the moderator saw the message, not that they did
anything about it.

**Why this priority**: This is the rule the source plan names as the milestone's acceptance: no path may
set *resolved* from an acknowledgement alone. It is also the easiest one to get wrong in a way that
flatters everyone — a ✅ costs nothing, and a system that accepted it as handling would teach the team to
react instead of act.

**Independent Test**: Script evidence against open incidents with a controlled clock: a moderator's
reaction, a moderator's direct reply, a moderator's plain message that replies to nothing, a reaction by
a student, a reaction by an anonymous administrator, a reaction removed again, the sender reacting to
their own message, and twenty acknowledgements in a row. Confirm which incidents become acknowledged,
the moment and actor recorded, and that none becomes resolved.

**Acceptance Scenarios**:

1. **Given** an open incident, **When** a person recorded as a moderator at that moment adds a reaction to
   the incident's message, **Then** the incident is acknowledged, with the reaction's platform timestamp,
   the reacting moderator, and the kind recorded as a reaction.
2. **Given** an open incident, **When** a moderator's message directly replies to the incident's message,
   **Then** the incident is acknowledged, with the reply's platform timestamp, the replying moderator, and
   the kind recorded as a reply.
3. **Given** an acknowledged incident, **When** any number of further replies and reactions arrive,
   **Then** it remains acknowledged, and every one of them appears in its evidence trail.
4. **Given** an open incident, **When** a moderator posts a message in the group that replies to nothing,
   **Then** the incident is not acknowledged — only a direct reply to the offending message counts.
5. **Given** an open incident, **When** someone who was not a moderator at that moment reacts to or replies
   to the offending message, **Then** nothing changes — even if that person is made a moderator later.
6. **Given** an open incident, **When** a reaction arrives that the platform attributes to no person, such
   as one made anonymously on behalf of the group, **Then** nothing changes.
7. **Given** an open incident, **When** a moderator removes a reaction without adding one, **Then** nothing
   changes.
8. **Given** an incident on a message sent by a moderator, **When** that same moderator reacts to their own
   message, **Then** nothing changes — the offending message's own sender can never acknowledge it.
9. **Given** a moderator's reply or reaction whose platform timestamp is not strictly after the message was
   posted, **When** it is evaluated, **Then** it does not count, regardless of the order it was stored in.
10. **Given** a moderator's reply that says in words that the message was deleted, **When** the incident is
    inspected, **Then** it is acknowledged only; the system reads no meaning from the words.

---

### User Story 3 - Removing or restricting the sender resolves the incident, attributed to whoever the platform says did it (Priority: P3)

A moderator restricts the account that posted the advert. The platform reports the restriction, and names
who performed it. The incident resolves — directly from open if nobody had replied or reacted first — with
the moment taken from the platform's report and the performer recorded. If the performer was a moderator,
they are credited. If it was an administrator nobody mapped, another bot, or an anonymous administrator,
the incident is still resolved, because the violation was dealt with, but no moderator is credited for
it.

**Why this priority**: Enforcement is the strongest moderation evidence the platform gives, and the only
kind that is attributable with certainty. It is also where a careless implementation resolves the wrong
incident: a ban of a different member, in a different group, or before the message was even posted.

**Independent Test**: Script membership changes against open and acknowledged incidents with a controlled
clock: the sender banned, removed without a ban, restricted, unbanned again, leaving of their own accord;
a different member banned; the same member banned in a different group; a ban performed by an unmapped
administrator, by another bot, and anonymously; and one ban of a spammer with three open incidents.
Confirm exactly which incidents resolve, the actor recorded, and that nothing else moves.

**Acceptance Scenarios**:

1. **Given** an open incident, **When** the platform reports its message's sender banned or removed from
   that group by someone other than the sender, **Then** the incident is resolved, with the platform's
   timestamp, the performer, and the kind recorded as enforcement — without passing through acknowledged.
2. **Given** an acknowledged incident, **When** the platform reports the sender restricted in that group,
   **Then** the incident is resolved, and its earlier acknowledgement remains recorded.
3. **Given** a spammer with three open incidents in one group, **When** they are banned once, **Then** all
   three are resolved by that one piece of evidence.
4. **Given** an open incident, **When** a different member is banned, or the same member is banned in a
   different group, **Then** nothing changes.
5. **Given** an open incident, **When** its sender leaves the group of their own accord, **Then** nothing
   changes — leaving is not enforcement.
6. **Given** a resolved incident, **When** its sender is unbanned or their restriction lifted, **Then** the
   reversal appears in the evidence trail and the incident stays resolved, and the reversal enters no
   timing.
7. **Given** a ban performed by someone recorded as a moderator who does not own the group, **When** the
   incident is inspected, **Then** it is resolved, that moderator is recorded as the actor, and the
   responsible moderator is unchanged.
8. **Given** a ban performed by an administrator who is not a mapped moderator, by another bot, or
   anonymously, **When** the incident is inspected, **Then** it is resolved, no moderator is credited, and
   the performer is shown as the platform identified them — or as anonymous.
9. **Given** a ban whose platform timestamp is not strictly after the message was posted, **When** it is
   evaluated, **Then** it does not resolve the incident.
10. **Given** an incident on a message sent on behalf of a channel or of the group itself rather than by a
    person, **When** the incident is inspected, **Then** the screen states that membership evidence cannot
    arrive for it and that it can only be resolved by confirmation.

---

### User Story 4 - An operator can confirm what the platform cannot see, and can withdraw a false accusation (Priority: P4)

A moderator tells the operator they deleted the advert. The platform will never report that. The operator
resolves the incident in the control panel with a note saying so, and the record states plainly that it
was the operator's confirmation — not an observation. Elsewhere, the operator realises an incident they
opened was not a violation at all, and closes it as a false positive with a reason. Neither incident can
be reopened by anything that happens later.

**Why this priority**: Without confirmation, every silently deleted message stays open forever and is
counted as missed, which punishes exactly the moderators who act fastest. Without false-positive closure,
one mistaken flag is a permanent accusation in someone's figures.

**Independent Test**: Acknowledge, resolve and close incidents from the panel in each permitted and
forbidden state; submit the same action twice; let evidence arrive after a terminal state. Confirm the
recorded account, moment, note and reason, the refusals, and that nothing leaves a terminal state.

**Acceptance Scenarios**:

1. **Given** an open incident, **When** an operator acknowledges it in the panel, **Then** it is
   acknowledged, recorded as the operator's act with their account and moment.
2. **Given** an open or acknowledged incident, **When** an operator resolves it with a note, **Then** it is
   resolved, recorded as a confirmation by that account with the note, and nothing on it claims the
   platform observed anything.
3. **Given** an open or acknowledged incident, **When** an operator closes it as a false positive with a
   reason, **Then** it is closed as such, with the reason, account and moment recorded.
4. **Given** a resolved or false-positive incident, **When** later evidence arrives — a reaction, a reply,
   a ban, an unban — **Then** it is recorded in the trail and the incident's state does not change.
5. **Given** a resolved or false-positive incident, **When** an operator looks for a control to change its
   state, **Then** none is offered; **and when** the same panel action is submitted twice, **Then** the
   second submission changes nothing.
6. **Given** false-positive incidents in a period, **When** the figures are computed, **Then** they appear
   in no handled, missed or timing figure, and their own count is shown separately.
7. **Given** the incidents screen, **When** the operator looks for a way to act on several incidents at
   once, **Then** there is none.

---

### User Story 5 - One screen answers the six questions about any incident (Priority: P5)

The operator opens an incident and, on one screen, reads: what was posted and its content flags; when it
was posted, flagged, acknowledged and resolved; why it was flagged and by whom; every piece of evidence in
platform-time order, with who did what to whom and the captured event it came from; how long each of the
three steps took; and whether it was corrected. Beneath it, always: *Telegram does not report message
deletion in groups; no removal evidence is available.*

**Why this priority**: The incident is only as defensible as its explanation. A moderator shown a slow
figure will ask "slow compared to what, and based on what?" — and this screen is the answer, with every
number traceable to an event the platform reported.

**Independent Test**: Seed incidents in every state with known evidence, including one with no evidence,
one whose text has passed retention, one in a group where the bot is not currently an administrator, and
one resolved by an unmapped performer. Load the list and detail screens and confirm each question is
answered, the timings match hand computation, the absences are stated as absences, and no wording
anywhere implies a deletion was observed.

**Acceptance Scenarios**:

1. **Given** incidents in several states, **When** the list is loaded, **Then** each shows its group, its
   status, its responsible moderator or an explicit unassigned marker, when it was posted, when it was
   flagged and how long it has been open or took, and the list can be filtered by status, category,
   severity, group, responsible moderator and detection date.
2. **Given** an incident with evidence, **When** its detail is opened, **Then** the evidence is listed in
   platform-time order, each entry naming its kind, its strength, its actor, the member it affected where
   relevant, its moment and the captured event it came from.
3. **Given** an incident that is missing one or more kinds of evidence, **When** its timings are shown,
   **Then** each missing one reads as "no evidence", never as zero and never as a guess.
4. **Given** any incident, **When** its detail is opened, **Then** the standing statement that the platform
   does not report deletion is present, and no field, label, evidence kind or figure anywhere in the panel
   implies a deletion was observed.
5. **Given** an incident in a group where the bot is not currently an administrator, **When** its detail
   is opened, **Then** the screen states that reaction and membership evidence cannot arrive from that
   group while this is so.
6. **Given** an incident whose message text has passed its retention window, **When** it is opened, **Then**
   its moments, evidence, timings and attribution are intact and the text is shown as removed.
7. **Given** Arabic message text, **When** it is displayed, **Then** it renders in its own reading
   direction without the surrounding panel changing direction.
8. **Given** the incident screens, **When** the operator looks for a control that would post a message,
   ban, restrict, delete, react, call a model, run a bulk job or change the store's shape, **Then** there is
   none.

---

### User Story 6 - Three timings, separately named, and handled versus missed — all reproducible by hand (Priority: P6)

For a chosen period, group and moderator, the operator sees how many incidents were flagged, acknowledged,
handled, missed and closed as false positives, and for each of the three timings the middle, the slow end
and the slowest single value, each with the number of incidents it was built from. The system's own
latency is shown as its own figure and never appears against a moderator. Too few measurements for a
percentile to mean anything produce a stated reason instead of a number. No average appears, and no single
score is computed for anyone.

**Why this priority**: These are the numbers the milestone exists to produce, and the acceptance of every
figure in this domain is that a hand computation matches the screen exactly.

**Independent Test**: Load a fixed set of incidents with known moments and evidence — some with one kind
of evidence, some with two, some with all three, some false positives, some past the age ceiling — and
compare every displayed figure against values computed by hand, including the percentile suppression and
the period boundaries.

**Acceptance Scenarios**:

1. **Given** an incident with a reaction, a restriction and a panel resolution, **When** its timings are
   computed, **Then** acknowledgement time, observed-enforcement time and handling-confirmation time are
   each the earliest evidence of their own kind minus the detection moment, and each matches hand
   computation exactly.
2. **Given** an incident resolved by a ban with no prior reply or reaction, **When** its timings are
   computed, **Then** it has an observed-enforcement time and no acknowledgement time.
3. **Given** a fixed set of incidents, **When** the figures are computed for a period, **Then** each
   timing's middle, slow end and slowest value match hand computation, the count each was built from is
   shown beside it, and the slow end is withheld with a stated reason below the percentile threshold.
4. **Given** incidents in a period, **When** handled and missed are counted, **Then** acknowledged incidents
   are shown separately and not counted as handled, false positives are in neither, and the handled share
   is handled divided by handled plus missed.
5. **Given** an incident resolved thirty hours after it was flagged under a twenty-four-hour ceiling,
   **When** its outcome is computed, **Then** it is missed, its state is resolved, and its timings show how
   late the resolution came; **and when** the figures for its period are computed again a month later,
   **Then** they are unchanged.
6. **Given** incidents whose earliest acknowledgement or enforcement preceded the flagging moment, **When**
   the timing figures are computed, **Then** each such incident appears in that timing's "acted before
   flagging" count beside the figure, contributes nothing to its middle, slow end or slowest value, and is
   counted as handled if it was resolved.
7. **Given** any moderator, **When** their figures are shown, **Then** the detection latency appears in none
   of them, no average appears, and no combined score exists.
8. **Given** a period boundary, **When** incidents are selected into it, **Then** selection uses each
   incident's detection moment, inclusive at the start and exclusive at the end.
9. **Given** a moderator whose ownership of a group changed inside the period, **When** their figures are
   computed, **Then** each incident counts towards whoever owned the group when it was flagged.

---

### Edge Cases

- **The moderator acted before anyone flagged the message.** A spammer is banned at 10:04 and the operator
  opens the incident at 10:10. The evidence is real and after the posting, so the incident opens already
  resolved, crediting whoever performed the ban. Its enforcement time is not −6 minutes and not zero: it is
  counted as "acted before flagging" beside the figure and kept out of the distribution.
- **Evidence from before the posting.** A ban of the same member *before* the flagged message was posted —
  they were banned, unbanned, and posted again — is never counted, before or after flagging.
- **One ban, several incidents.** A spammer who posted three flagged messages is banned once; all three
  resolve on the same evidence.
- **A spammer banned, unbanned, and posting again.** The new message's incident is not resolved by the
  earlier ban, which happened before it was posted.
- **Removed, not banned.** Removing a member without banning them is reported by the platform as a ban
  followed by an unban. The first part is enforcement; the second is a reversal, recorded and inert.
- **A restriction loosened but not lifted.** A member left under some restriction by someone else is still
  a member under enforcement; the change is recorded as enforcement. This is rare and accepted.
- **The sender leaves by themselves before anyone acts.** Not enforcement. The incident stays open until
  someone confirms or closes it.
- **An anti-spam bot bans the spammer.** The violation was dealt with, so the incident resolves; no
  moderator is credited, and the bot is shown as the performer.
- **An administrator acts anonymously.** A ban resolves the incident with the performer shown as
  anonymous; an anonymous reaction is not acknowledgement, because acknowledgement exists to say that a
  person saw it.
- **A moderator replies "تم الحذف" ("deleted").** Acknowledged only. The words are the moderator's claim;
  nothing parses them, and the platform still reported no deletion.
- **A moderator deletes the spam silently.** Nothing arrives. The incident stays open and ages until an
  operator records the moderator's report as a confirmation — which is exactly what confirmation exists
  for — or until it is counted as missed.
- **Evidence processed out of order.** A reaction at 10:07 is stored after a ban at 10:12 has already
  resolved the incident. The state stays resolved, and the acknowledgement still counts towards the
  acknowledgement time, because timings come from platform timestamps, never from processing order.
- **The same captured event processed twice** — after a restart, a retry, or a re-derivation. One piece of
  evidence results and nothing moves twice.
- **Two pieces of evidence race.** Two workers apply a reaction and a ban to the same incident at once.
  Exactly one final state results, and it is the same as if they had been applied one after the other in
  either order.
- **A moderator reacts to their own flagged message.** The offending message's own sender can never
  acknowledge or confirm it.
- **The bot is not an administrator in the group.** Reactions and membership changes do not arrive at all,
  silently. The incident screen says so, because an absence of evidence there is not evidence of inaction.
- **The capture process was off during the moderator's action.** The evidence was never captured and the
  incident stays open. The unobserved windows are already recorded; rendering a figure incomplete where it
  overlaps one is TG-M7's job, and the limitation is written down.
- **A message sent as a channel or as the group itself.** The platform reports no membership change for
  such senders, so no enforcement evidence can arrive; the screen says so and confirmation is the only
  route to resolution.
- **A flagged message also opened a question item.** The two are independent: the incident changes nothing
  about the item, and dismissing the item is a separate act.
- **The message's text passes its retention window.** The incident, its moments, its evidence and its
  timings survive; only the words are gone.
- **The group is promoted to a supergroup mid-incident.** Incidents and their evidence follow the surviving
  group, as ownership assignments and question items already do.
- **An operator flags a message from a group that is later un-measured.** The incident stays, with its
  evidence so far; no further evidence is derived from that group.
- **Ownership changes in the same second an incident is flagged.** The existing interval boundary rule
  decides, identically every time.
- **An incident's outcome after the age ceiling.** An incident still open or acknowledged past the ceiling
  stays in its state — incidents never expire — and is counted as missed. If it is resolved afterwards its
  state becomes resolved, but its outcome stays missed: handled means handled in time, and a past period's
  figures do not move.
- **Resolution evidence dated inside the window but processed after it.** A capture backlog delivers a ban
  from hour 20 at hour 26. The outcome follows the platform's timestamp, so the incident is handled; this is
  the record being corrected with a fact that arrived late, not a definition changing, and it is the only
  way a settled outcome can differ from what was shown earlier.
- **An operator chose the wrong category or severity.** The labels are not edited in this milestone. A flag
  that was wrong altogether is closed as a false positive; a flag that was right but mislabelled is
  corrected through TG-M8's review path.

## Requirements *(mandatory)*

### Functional Requirements

#### Opening an incident

- **FR-001**: The system MUST let an operator open an incident against a specific stored message in a
  measured group from the control panel, including directly from a waiting question on the Live Attention
  Queue.
- **FR-002**: The system MUST allow at most one incident per message, ever, identifying the message by its
  group and its platform message number together, because the platform numbers messages separately in
  each group; a competing attempt MUST fail harmlessly, and the panel MUST prevent it in the form rather
  than by an error.
- **FR-003**: The system MUST record an incident's posting moment as the offending message's platform send
  timestamp, and MUST NOT substitute the time it was stored, derived or flagged.
- **FR-004**: The system MUST record an incident's detection moment as the moment it was flagged, and MUST
  keep the posting and detection moments as two separate facts, neither ever standing in for the other.
- **FR-005**: The system MUST record on every incident that an operator opened it and which panel account
  did so, and MUST reserve — but never write — an automatic source for the milestone that adds model
  detection.
- **FR-006**: When an operator opens an incident, the system MUST require a category — spam or advert,
  abuse, or other — and a severity — low, medium or high — both drawn from the source plan's taxonomy,
  MUST record them as operator-assigned so they can never be mistaken for a model's prediction, and MUST
  NOT allow them to be edited afterwards in this milestone.
- **FR-007**: The system MUST NOT allow an incident on a service announcement, and MUST allow one on any
  other stored message, including messages from bot accounts and messages sent on behalf of a channel or
  of the group itself.
- **FR-008**: The system MUST NOT alter any question item, any message record, or any figure defined by
  TG-M3 when an incident is opened; an incident and a question item MAY exist on the same message
  independently.
- **FR-009**: The system MUST NOT open any incident automatically in this milestone — by rule, by model or
  by any other means.

#### Recording evidence

- **FR-010**: The system MUST recognise, as enforcement evidence, every change the platform reports that
  leaves a member of a measured group banned, removed or restricted, performed by someone other than that
  member, recording the performer the platform names, the member affected, the group and the platform's
  timestamp — whether or not any incident exists at the time.
- **FR-011**: The system MUST recognise, as acknowledgement evidence, every reaction added by a person
  recorded as a moderator at that moment to a message in a measured group, recording the moderator, the
  message and the platform's timestamp — whether or not any incident exists at the time.
- **FR-012**: The system MUST recognise, as acknowledgement evidence, a message sent by a person recorded as
  a moderator at send time that directly replies to an incident's message, from the message record already
  stored, without keeping a second copy of the message's facts.
- **FR-013**: The system MUST NOT treat as evidence of anything: a reaction by someone who was not a
  moderator at that moment; a reaction the platform attributes to no person; the removal of a reaction; a
  member leaving of their own accord; a member joining; or a change to anyone's administrator status.
- **FR-014**: The system MUST record the reversal of an enforcement — an unban or a lifted restriction — in
  the evidence trail, and MUST NOT let a reversal resolve, reopen or alter any incident, or enter any
  timing.
- **FR-015**: The system MUST decide whether a reacting or performing person was a moderator once, when the
  evidence is recorded, by the same rule the previous milestone applies to message senders, and MUST NOT
  recompute it afterwards.
- **FR-016**: The system MUST NOT count any evidence produced by the offending message's own sender towards
  that message's incident.
- **FR-017**: The system MUST record each panel act on an incident — acknowledge, resolve, close as a false
  positive — as evidence carrying the panel account and the moment.
- **FR-018**: The system MUST never alter or remove the recorded facts of a piece of evidence — what
  happened, who did it, to whom, where and when.
- **FR-019**: The system MUST produce exactly one piece of evidence from a given captured event however many
  times that event is interpreted.
- **FR-020**: The system MUST NOT name, label or describe any kind of evidence, field or figure in a way that
  implies a message deletion or its author was observed.

#### Acknowledgement

- **FR-021**: The system MUST move an open incident to acknowledged on its first acknowledgement evidence: a
  moderator's reaction added to the incident's message, a moderator's direct reply to it, or a panel
  acknowledgement.
- **FR-022**: The system MUST record on an acknowledged incident the acknowledgement's moment, its actor and
  its kind, where the first acknowledgement is the earliest by platform timestamp rather than the first
  processed.
- **FR-023**: The system MUST NOT resolve an incident on acknowledgement evidence, whatever its amount or
  combination.
- **FR-024**: The system MUST NOT treat a moderator's message that does not directly reply to the incident's
  message as acknowledgement.
- **FR-025**: The system MUST count only evidence whose platform timestamp is strictly after the incident's
  posting moment, regardless of the order in which evidence and message were stored.

#### Resolution

- **FR-026**: The system MUST resolve an open or acknowledged incident on enforcement evidence against the
  sender of the incident's message, in the same group, with a platform timestamp strictly after the posting
  moment.
- **FR-027**: The system MUST resolve an open or acknowledged incident when an operator resolves it in the
  panel with a note, recorded as a confirmation.
- **FR-028**: The system MUST allow an incident to go from open to resolved directly, without passing through
  acknowledged.
- **FR-029**: The system MUST record on a resolved incident the resolution's moment, its actor and whether it
  was enforcement or confirmation.
- **FR-030**: The system MUST resolve every open or acknowledged incident whose message the affected member
  sent in that group before the enforcement, from one piece of enforcement evidence.
- **FR-031**: The system MUST NOT resolve an incident on enforcement against a different member, in a
  different group, or dated at or before the posting moment.
- **FR-032**: The system MUST resolve an incident on enforcement performed by someone who is not a mapped
  moderator — an unmapped administrator, another bot, or an anonymous administrator — MUST credit no
  moderator for it, and MUST show the performer as the platform identified them or as anonymous.
- **FR-033**: The system MUST state, on an incident whose message was sent on behalf of a channel or of the
  group rather than by a person, that no enforcement evidence can arrive for it and that confirmation is
  its only route to resolution.

#### Operator confirmation and false positives

- **FR-034**: The system MUST let an operator acknowledge an open incident in the panel.
- **FR-035**: The system MUST let an operator resolve an open or acknowledged incident in the panel with a
  required note, and MUST present the result as the operator's confirmation, never as a platform
  observation — including when the note records a moderator's report that they removed the message.
- **FR-036**: The system MUST let an operator close an open or acknowledged incident as a false positive,
  recording a required reason, the panel account and the moment.
- **FR-037**: The system MUST exclude false-positive incidents from every handled count, every missed
  count and every timing figure, MUST report their number separately, and MUST keep them retrievable as a
  labelled set of flags that proved wrong.
- **FR-038**: The panel MUST offer no action that applies to several incidents at once.

#### Lifecycle integrity

- **FR-039**: The system MUST give an incident exactly one of four states — open, acknowledged, resolved,
  closed as a false positive — where resolved and closed as a false positive are terminal.
- **FR-040**: The system MUST perform every state change as a single guarded step that succeeds only from its
  permitted prior states, so that repetition and concurrency are harmless and exactly one outcome results.
- **FR-041**: The system MUST NOT move an incident out of a terminal state — not on later evidence, not on a
  second panel action, not on a reversal.
- **FR-042**: The system MUST NOT change an incident's state on an inferred deletion, on the absence of
  evidence, or on the passage of time.
- **FR-043**: The system MUST, when an incident opens, evaluate the evidence already recorded with a
  platform timestamp strictly after the posting moment — including evidence dated before the detection
  moment — and MUST open the incident directly in the state that evidence implies, recording its actual
  moments and actors.
- **FR-044**: The system MUST apply one implementation of the evidence-matching rules both to evidence
  arriving after an incident opens and to evidence already recorded when it opens, so the two can never
  disagree.
- **FR-045**: The system MUST reach the same final state and the same timings for an incident from the same
  set of evidence regardless of the order in which that evidence is processed; evidence recorded after an
  incident is resolved still counts towards the timings of its own kind without changing the state.

#### Attribution

- **FR-046**: The system MUST resolve each incident's responsible moderator as the group's primary owner at
  the incident's **detection** moment, using the existing ownership history, and MUST record the result
  onto the incident rather than looking it up when read.
- **FR-047**: The system MUST leave the responsible moderator absent, rather than guessing, when the group had
  no primary owner at that moment, and MUST make such incidents visible as a coverage problem.
- **FR-048**: The system MUST NOT change an incident's recorded responsible moderator when ownership is later
  reassigned.
- **FR-049**: The system MUST record the actor of each acknowledgement and resolution separately from the
  responsible moderator, so that a colleague's help is visible as help, and MUST NOT treat it as a penalty.
- **FR-050**: The system MUST attribute each incident, in every per-moderator figure, to its recorded
  responsible moderator.

#### Timings and outcomes

- **FR-051**: The system MUST compute an incident's acknowledgement time as its earliest acknowledgement
  evidence's moment minus its detection moment.
- **FR-052**: The system MUST compute an incident's handling-confirmation time as its earliest confirmation's
  moment minus its detection moment.
- **FR-053**: The system MUST compute an incident's observed-enforcement time as its earliest enforcement
  evidence's moment minus its detection moment.
- **FR-054**: The system MUST compute an incident's detection latency as its detection moment minus its
  posting moment, MUST report it only as a figure about the system, and MUST NOT include it in any figure
  attributed to a moderator.
- **FR-055**: The system MUST compute each timing independently, so an incident may contribute to none, one,
  two or all three, and MUST let a missing kind of evidence contribute no value — never zero, never an
  invented maximum.
- **FR-056**: The system MUST treat an incident whose earliest evidence of a kind precedes its detection
  moment as having "acted before flagging" for that timing: it MUST contribute no value to that timing's
  middle, slow end or slowest figure, MUST be counted in a separate "acted before flagging" figure reported
  beside that timing, and MUST NOT be reported with a negative or zero duration anywhere.
- **FR-057**: The system MUST NOT define, compute or display any deletion or removal timing.
- **FR-058**: The system MUST use a configurable incident age ceiling, defaulting to twenty-four hours from
  the detection moment, solely to decide an incident's outcome.
- **FR-059**: The system MUST classify each non-false-positive incident's outcome as: **handled** when its
  resolution's moment falls no later than its detection moment plus the age ceiling; **missed** when the
  ceiling has passed without such a resolution — whether the incident is still open or acknowledged, or was
  resolved only afterwards; and **within its window** otherwise.
- **FR-060**: The system MUST judge the outcome by the resolution evidence's own moment — the platform's
  timestamp for enforcement, the panel moment for a confirmation — never by when the evidence was processed,
  so that an incident's outcome is settled once its window closes and a later resolution changes its state
  but never its outcome.
- **FR-061**: The system MUST NOT count an acknowledged incident as handled, and MUST show acknowledged
  incidents separately.
- **FR-062**: The system MUST compute the handled share as handled divided by handled plus missed, with false
  positives in neither the numerator nor the denominator.
- **FR-063**: The system MUST report, per group and per moderator for a chosen period: incidents flagged,
  acknowledged, handled, missed and closed as false positives; and for each of the three timings, the
  middle, the slow end and the slowest single value together with the number of incidents each was built
  from and the "acted before flagging" count, withholding the slow end with a stated reason below the
  existing percentile threshold.
- **FR-064**: The system MUST select incidents into a period by their detection moment, inclusive at the
  start and exclusive at the end, never by when a row was written.
- **FR-065**: The system MUST NOT display an average of any timing, and MUST NOT compute any combined score
  for any moderator or group.
- **FR-066**: The system MUST produce figures reproducible by hand from stored incidents and evidence alone,
  and MUST document each figure's definition in one place shared by every screen that shows it.

#### The screens

- **FR-067**: The control panel MUST provide an incidents screen within the domain's existing navigation
  group, listing incidents with group, status, responsible moderator or an explicit unassigned marker,
  posting moment, detection moment and age, filterable by status, category, severity, group, responsible
  moderator and detection date.
- **FR-068**: The incident detail MUST answer on one screen: what was posted, with its content flags; when it
  was posted, flagged, acknowledged and resolved or closed; why it was flagged, by whom, and with what
  operator-assigned category and severity; who handled it; how long each of the three steps took — or that
  the moderator acted before flagging — and the detection latency; its outcome; and whether it was closed as
  a false positive and why.
- **FR-069**: The incident detail MUST list the evidence in platform-time order, each entry with its kind,
  strength, actor, affected member where relevant, moment, and a reference to the captured event it came
  from.
- **FR-070**: The incident detail MUST always show the statement that the platform does not report message
  deletion in groups and that no removal evidence is available.
- **FR-071**: The incident detail MUST state when the bot is not currently an administrator in the
  incident's group, because reaction and membership evidence cannot arrive from that group while it is so.
- **FR-072**: The Live Attention Queue MUST gain an action that opens an incident from a waiting question's
  row, and MUST otherwise remain as TG-M3 shipped it.
- **FR-073**: The incident screens MUST NOT offer any control that posts a message, bans, restricts, deletes,
  reacts, calls a model, runs a bulk job or changes the store's shape.
- **FR-074**: The control panel MUST display Arabic content in its own reading direction per field, leaving
  the panel's language and direction unchanged.
- **FR-075**: The control panel MUST render every moment in the operator's local timezone and every duration
  in human units, while the store keeps a single universal reference.
- **FR-076**: The control panel MUST still show an incident whose message text has been removed by retention,
  with its moments, evidence, timings and attribution intact and its text marked as removed.
- **FR-077**: Where the detail shows how an incident was flagged, the control panel MUST show that no model
  classification exists yet, rather than leaving the space blank or implying one ran.

#### Boundaries, silence and observability

- **FR-078**: The system MUST make no model call, send no outbound message and expose no inbound endpoint in
  this milestone, and the bot MUST perform no moderation act of any kind.
- **FR-079**: The system MUST keep the bot silent in every group, and this MUST remain covered by an automated
  test.
- **FR-080**: The system MUST keep the domain's module boundaries intact, including that nothing outside the
  platform provider speaks to the platform and that no assessment-side module imports this domain.
- **FR-081**: The system MUST NOT write any message text, in any form, into any log line, and MUST carry an
  incident's identifier as a correlation identifier on the log records of the steps that open and transition
  incidents.
- **FR-082**: The system MUST make incidents and their evidence follow a group through a platform-side group
  promotion, exactly as ownership assignments and question items already do.
- **FR-083**: The system MUST NOT derive evidence from captured events retroactively on its own: ordinary
  interpretation MUST derive evidence only from this milestone onwards, and no screen control MUST trigger a
  bulk derivation.
- **FR-084**: The operator's existing re-derivation command MUST gain an opt-in that also derives evidence
  for the named group and an optional window, MUST be idempotent across repeated runs, and MUST report how
  much evidence it recorded and how many incidents it moved.
- **FR-085**: The system MUST treat operator acts — opening an incident, panel acknowledgements,
  confirmations and false-positive closures — as human facts that re-derivation preserves and never
  recreates, discards or overrides.
- **FR-086**: The system MUST leave every TG-M3 figure and behaviour unchanged; in particular a reaction MUST
  still close no question.
- **FR-087**: The system MUST make every automated test in this milestone pass with no platform credential
  set, no network access and no model runtime running.

### Out of Scope (deferred to named later milestones)

- Recognising a violation automatically, the classification taxonomy as a model output, confidence, the
  confidence floor that routes a flag to review instead of an incident, and redaction in a live path —
  **TG-M5**. The automatic source on an incident is reserved and never written here.
- Alert rules, thresholds, quiet hours, the private moderators' group, the alert buttons — including the
  "Handled" and "Not an issue" confirmations those buttons produce — and any outbound message — **TG-M6**.
  The lifecycle defined here is the one those buttons will drive; nothing about it changes when they arrive.
- The overview screen, team and group performance screens, the ingestion-health banner, coverage badges,
  and the marker that renders a figure incomplete where it overlaps an unobserved window — **TG-M7**. The
  figures defined here are shown on this milestone's own screen and defined once for TG-M7 to arrange.
- Classification review, correction history and reprocessing — **TG-M8**, including correcting an
  operator-assigned category or severity. The "was it corrected?" question is answered here only by
  false-positive closure.
- Scheduled digests and any endpoint an external tool calls — **TG-M9**.
- The job that removes message text and names at the end of retention, and the proof that re-deriving every
  captured event reproduces identical derived state — **TG-M10**. Both are shaped for here: incidents and
  evidence store no message text, and every derivation is idempotent.
- Any bot action in a group: banning, restricting, deleting, warning, reacting or replying. Excluded from
  the whole first version — doing it would destroy the very measurement this milestone builds.
- A deletion probe or any other attempt to infer that a message was removed, when, or by whom. Excluded
  from the whole first version by decision, and the platform reports none of it.
- Any composite score for any moderator or group. Excluded from the whole first version, not deferred.
- Treating an acknowledgement as a resolution, in this or any later milestone.
- Escalation of an incident's severity over time, re-opening a closed incident, and merging incidents.
- A full localisation of the control panel.

### Key Entities

- **Moderation incident**: One message that needed a moderator to act — the derived unit of enforcement. It
  knows when the message was posted and when it was flagged, who flagged it, who owned the group at the
  flagging moment, its current state, and — once acknowledged, resolved or closed — when, by whom and on
  what evidence. Anchored on exactly one message, which can anchor no other incident.
- **Moderation evidence**: One observed act, append-only — a removal, a restriction, a reversal, a
  moderator's reaction, a moderator's direct reply, or a panel act. It carries a kind, a strength
  (acknowledgement, enforcement or confirmation), the actor as the platform identified them, the member
  affected where relevant, the platform's timestamp or the panel moment, and a reference to the captured
  event it came from. Evidence is the audit trail; incident state is derived from it.
- **Evidence strength**: The claim a piece of evidence supports. *Acknowledgement* — someone saw it.
  *Enforcement* — the sender was removed or restricted, as the platform reported. *Confirmation* — a person
  stated it was handled. Each strength produces its own timing and none substitutes for another.
- **Operator-assigned labels**: The category and severity an operator chose when flagging the message, from
  the source plan's taxonomy. Recorded as the operator's, fixed at opening, and kept distinct from the model
  predictions that arrive at TG-M5.
- **Incident outcome**: Handled in time, missed, still within its window, or a false positive — a figure
  about an incident, distinct from its state, and settled once its window closes. False positives leave
  every outcome count; acknowledged incidents are never handled; an incident resolved after its ceiling is
  resolved in state and missed in outcome.
- **The three timings and the system's latency**: acknowledgement time, handling-confirmation time and
  observed-enforcement time, each measured from the detection moment and attributed to the responsible
  moderator — or, where the moderator acted before the message was flagged, counted as "acted before
  flagging" instead of measured; and detection latency, measured from the posting moment and attributed to
  nobody.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The runbook's smoke test passes as written in the development group: an incident opened on a
  real message; a ✅ reaction by the operator's moderator identity moves it to acknowledged; restricting the
  disposable account moves it to resolved with the operator's name as the performer; and the
  observed-enforcement time shown equals the hand-computed difference exactly.
- **SC-002**: No sequence of replies, reactions and panel acknowledgements — of any length, in any order —
  resolves an incident, verified across the full set of evidence combinations.
- **SC-003**: Every permitted transition succeeds exactly once, and every forbidden transition — out of a
  terminal state, back to open, from acknowledged to open — changes nothing and raises no error; the full
  transition table is covered.
- **SC-004**: A ban of the sender with no prior reply or reaction resolves the incident directly, which then
  has an observed-enforcement time and no acknowledgement time.
- **SC-005**: The same evidence for an incident, processed in three different orders, produces an identical
  final state and identical timings each time.
- **SC-006**: Interpreting the same captured event three times produces one piece of evidence, and opening
  an incident on the same message twice produces one incident.
- **SC-007**: A ban of a different member, a ban in a different group, a member leaving of their own accord,
  a reaction by a non-moderator, an anonymous reaction and a removed reaction each change no incident.
- **SC-008**: One ban of a spammer with three open incidents in the group resolves all three.
- **SC-009**: For a fixed fixture of incidents, each of the three timings — middle, slow end and slowest —
  matches hand computation exactly, each shown with its sample count, and the slow end is withheld with a
  stated reason when fewer than ten incidents contribute.
- **SC-010**: False-positive incidents appear in no handled, missed or timing figure, and their count is
  shown separately.
- **SC-011**: Detection latency appears in no figure attributed to any moderator.
- **SC-012**: Reassigning a group's ownership after an incident was flagged leaves that incident's
  responsible moderator and every per-moderator figure unmoved.
- **SC-013**: No field name, label, evidence kind, figure or screen text anywhere in the panel claims that a
  deletion was observed, and every incident detail carries the standing statement that the platform does
  not report deletion.
- **SC-014**: No average timing and no combined per-moderator or per-group score appears anywhere in the
  panel.
- **SC-015**: A ban performed by an unmapped administrator, by another bot, or anonymously resolves the
  incident with no moderator credited and the performer shown.
- **SC-016**: Every TG-M3 figure computed over the same traffic is identical before and after this
  milestone's evidence is derived, and a moderator's reaction on a waiting question still closes nothing.
- **SC-017**: An incident whose message text has been removed by retention still shows its moments,
  evidence, timings and attribution.
- **SC-018**: A group promoted to a supergroup mid-incident keeps every incident and every piece of evidence.
- **SC-019**: Re-deriving a group with the evidence opt-in records evidence for the window, moves the
  incidents it should, reports both counts, and changes nothing at all when run a second time.
- **SC-020**: The complete automated test suite and the quality gate pass with no platform credential set,
  no network access and no model runtime running.
- **SC-021**: No log line produced anywhere in this milestone contains message text, verbatim or
  normalised, and this is enforced by the existing automated check.
- **SC-022**: Over one full smoke run, the bot posts nothing anywhere and performs no moderation act.
- **SC-023**: An incident opened after the sender was already banned opens resolved, crediting the ban's
  performer, and its enforcement time appears only in the "acted before flagging" count — no negative or
  zero duration appears in any figure.
- **SC-024**: An incident resolved after its age ceiling is resolved in state and missed in outcome, and the
  figures for its period are identical when recomputed a month later.
- **SC-025**: Every incident opened carries an operator-assigned category and severity; an attempt to open
  one without both is refused; and filtering the incidents screen by either returns exactly the incidents
  carrying that label.

## Assumptions

These are reasonable defaults taken where the milestone description did not specify details. Each is drawn
from the source plan, the operator runbook, the constitution, or a previous milestone.

- **Definition of done.** A milestone is done only when implementation exists, tests exist and pass,
  documentation and configuration are updated, a manual smoke test succeeds, no unrelated scope was added,
  and known limitations are written down. From the source plan's §25 preamble.
- **Seeing is not acting.** From §10.8, §14.2–14.3 and D-TG-07: a reply or a reaction is acknowledgement,
  and only enforcement or a human confirmation is resolution. The source plan names "no path sets resolved
  from an acknowledgement alone" as this milestone's acceptance, which is why it is stated as a requirement
  (FR-023) rather than left implicit in the state diagram.
- **Nothing here is ever called a deletion.** From §5.2, §14.3, §20.3 and runbook §F. The platform reports
  no deletion in groups and never its author. Where a screen would naturally say "removed", it says there is
  no removal evidence. A moderator's report that they deleted something is recorded as the operator's
  confirmation, which is honest about whose statement it is.
- **Only operators open incidents in this milestone.** From §14.1 and §25: automatic opening arrives with
  the classifier at TG-M5, and until then there is no AI detection at all.
- **Operators label what they flag, in the model's future vocabulary.** Confirmed in this session. The
  category is limited to the three taxonomy values that describe a violation — spam or advert, abuse,
  other — because the question and chit-chat categories describe messages that are not incidents; the
  severity omits the taxonomy's "none" for the same reason. The labels are fixed at opening: editing them
  would retroactively change what a later alert rule routed on, and a correction path with history is
  TG-M8's.
- **Evidence before flagging counts, and is reported apart from the distribution.** Confirmed in this
  session. It follows TG-M3's rule that opening evaluates what is already stored through the one matcher.
  The moderator gets the state, the credit and the handled count; the timing distributions keep only
  durations that genuinely mean "time since flagging". Only acknowledgement and enforcement can precede
  flagging — a panel confirmation is made on an incident that already exists.
- **Two moments, deliberately.** From §10.8 and §14.1: the posting moment is the platform's timestamp; the
  detection moment is when the incident was flagged; the three moderator timings are measured from detection
  so that detection delay — the classifier's later, the operator's now — is never billed to a moderator, and
  detection latency is reported as a system figure.
- **The responsible moderator is the owner at detection, not at posting.** From §10.8 and §12, and the
  deliberate counterpart of measuring the moderator timings from detection. It differs from TG-M3, where
  questions attribute to the owner at the moment the student spoke; the difference follows from where each
  clock starts and is kept on purpose.
- **Any moderator's reaction counts, not only ✅.** §14.2 and §10.9 say "a moderator reaction", and
  acknowledgement means only that the message was seen; the ✅ in the runbook's smoke test is an example,
  not a filter. The emoji used is kept on the evidence so a later milestone could narrow it.
- **Only a direct reply to the offending message acknowledges it.** A plain message from a moderator is not
  addressed to anything, and TG-M3's next-message rule was built for answering questions, not for proving a
  moderator saw a particular message.
- **Enforcement resolves the incident whoever performed it.** The violation is dealt with when the sender is
  gone. Crediting is separate: a moderator is credited only when the platform names one, and an anti-spam
  bot, an unmapped administrator or an anonymous administrator is shown as such. Refusing to resolve on a
  bot's ban would leave every group that uses one with a permanent wall of missed incidents.
- **A reversal is recorded and does nothing.** The source plan's §10.9 table lists unban alongside ban and
  restrict as enforcement-strength. This spec narrows that: an unban or a lifted restriction appears in the
  trail but never resolves, reopens or times anything, because counting the undoing of an enforcement as
  enforcement would let it stand as the earliest enforcement on a later incident. Escalated in the plan as a
  narrowing rather than taken quietly.
- **False-positive closure is allowed from acknowledged as well as open.** The §10.8 diagram draws it only
  from open, but a moderator can react to a message that later proves not to be a violation, and leaving
  such an incident uncloseable would force it into missed. §14.4 places no restriction.
- **Evidence is recorded as it arrives, not only once an incident exists.** Incidents are opened by hand,
  often after a moderator already acted; a membership change or reaction that was only kept inside the
  captured event would be lost to the incident when that event's payload reaches the end of its retention.
  Only moderators' reactions are kept, since nobody else's reaction is evidence of anything.
- **Missed is a figure, not a state.** From §10.8 and §18.5: an incident past its age ceiling stays open or
  acknowledged and is counted as missed; incidents never expire. This differs from TG-M3's questions, which
  do expire, because an unhandled violation is still unhandled tomorrow.
- **Handled means handled in time, and settled outcomes do not move.** Confirmed in this session, narrowing
  §18.5's literal definition — under which a late resolution would turn a past missed incident into a
  handled one and raise last month's handled share after the fact. The outcome is decided by the
  resolution's own timestamp against the ceiling; a late resolution still resolves the incident and its
  lateness is visible in its timings.
- **The incident age ceiling defaults to twenty-four hours and is configurable.** The source plan names an
  incident age ceiling but gives no value; twenty-four hours mirrors the only ceiling it does define, the
  question age ceiling. Urgency — "a violation visible for ten minutes" — belongs to TG-M6's alert
  thresholds, which are data rather than code.
- **The percentile threshold is the existing one.** Ten measurements, interpolating, suppressing rather than
  approximating, as TG-M3 established; no new threshold is introduced for incidents.
- **This milestone shows its figures on its own screen; it does not build the dashboard.** As in TG-M3: the
  figures are defined once and shown on the incidents screen, and TG-M7 arranges them rather than redefining
  them.
- **The Live Attention Queue gains exactly one action.** §17 lists "open incident" among the queue's row
  actions; it is added without changing anything else TG-M3 shipped, and opening an incident never
  dismisses the question — the operator does that separately if it is warranted.
- **The bot's standing is shown as it is now, not as it was.** The group record keeps the bot's current
  standing and when it last changed, not a history, so the incident screen warns about the present
  condition only; a historical coverage view belongs to TG-M7.
- **No automatic backfill; the operator's command can, on request.** Mirrors TG-M3's decision exactly.
  Captured membership and reaction events from before this milestone were marked handled without being
  interpreted; ordinary interpretation does not reach back to them, and the existing re-derivation command
  gains an opt-in that does.
- **Operator acts are facts, not derivations.** Opening an incident and every panel act are human decisions
  that cannot be recomputed from captured events, so re-derivation preserves them and re-applies only
  evidence-driven transitions around them.
- **The panel reads the same store directly with its restricted role, owns no schema change, and its tests
  wrap each case in a transaction.** The established pattern, not revisited. Panel accounts are not
  moderators, so a panel confirmation credits the account that made it and no moderator.
- **The panel per-field reading direction from TG-M2 is reused unchanged.**
- **Tests are written where the risk is.** Following Principle I: every legal and illegal transition;
  acknowledgement never resolving; enforcement resolving with the right actor and only for the right member
  and group; processing-order independence; idempotency of evidence and of opening; false positives leaving
  every outcome figure; the timing arithmetic with its suppression threshold; attribution at an ownership
  boundary; the absence of deletion wording; and the silence guarantee. No test is written for screen
  listing behaviour, framework wiring or column types.
- **No real platform access is needed to develop or verify this milestone.** Everything is exercised against
  scripted stand-ins and a controlled clock, as previous milestones established; real access is needed only
  for the operator's manual smoke test.
- **The smoke test runs in the development group with the development bot.** Runbook §B.2 and §C: a
  disposable third account the operator is willing to ban, the operator's own account mapped as a moderator
  of the dev group, and the dev bot an administrator there so that membership and reaction events are
  delivered. Because one machine never holds both credentials (runbook §B.4), running it may mean choosing a
  window when the live pilot's capture is not running on the same machine; that choice is the operator's.
- **Migration numbering is linear and first-come.** This domain reserved a block of revision identifiers and
  consumes the fourth of them here.
- **Nothing in this milestone judges behaviour on its own.** Every incident exists because a person flagged
  a message; the system measures what moderators then observably did. That boundary is what makes the
  figures defensible before a model with a measured baseline arrives at TG-M5.

## Dependencies

- **TG-M3 must be complete and merged**, as it is: question items and their anchoring on a group and message
  together, the Live Attention Queue this milestone adds one action to, the guarded write-once transition
  pattern, the percentile threshold and its suppression, the shared single-place figure definitions, the
  recurring background step, and the opt-in pattern on the re-derivation command.
- **TG-M2 must remain in place**: typed messages with the platform's send time, sender, reply target and
  content flags; the write-once record of whether a sender was a moderator, and the rule that decides it;
  sender identities; declared moderators; the time-versioned ownership history and its point-in-time
  lookup; the measurement flag; and the operator's re-derivation command.
- **TG-M1 must remain in place**: the append-only captured-event record, which already contains every
  membership change and reaction since capture began; the explicit subscription to membership and reaction
  events; the group records with the bot's current standing; identifier-migration linking; the
  unobserved-window records; and the diagnostic command that reports whether the bot is an administrator.
- **TG-M0 must remain in place**: the domain package boundary and its enforcement, the configuration block,
  the correlation-identifier whitelist (which already includes an incident identifier), and the
  no-message-text rule.
- **M0 and M1 must remain in place**: the running environment, migrations as the sole owner of schema
  change, the queue and background worker, the control panel shell with its restricted role and
  transaction-per-test pattern, and the quality gate with its enforced test-store isolation.
- **The source plan** `docs/plan/telegram/telegram-moderation-intelligence.md` — §5.1–5.2 for what the
  platform reports and does not, §9 for fact versus derived, §10.8–10.9 for the incident and evidence
  records and the state machine, §12 for attribution, §14 for opening, acknowledgement, resolution, false
  positives and the rejected deletion probe, §17 for the incidents screen and its six questions, §18.4–18.6
  for the timings, handled versus missed and the absence of any composite, §20 for idempotency and failure
  scenarios, §22 for which tests are earned, §25 for this milestone's own definition, and §27 for the
  certain attribution gap this milestone states rather than hides.
- **The operator runbook** `docs/runbooks/tg-operator-prerequisites.md` — §B.2 for the dev group's third
  identity, §C's TG-M4 row for the prerequisite and the smoke test, and §F for what the platform will never
  report.
- **Operator-supplied**: a disposable third account in the development group that the operator is willing
  to ban and restrict; the operator's own account mapped as a moderator of that group; and the dev bot an
  administrator there. Without them the milestone is fully developable and fully testable, but not
  smoke-testable.
- **No model runtime, no network access and no credential** are required by anything in this milestone's
  automated verification, including its tests.
