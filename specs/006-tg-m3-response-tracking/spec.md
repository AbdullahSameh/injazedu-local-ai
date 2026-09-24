# Feature Specification: TG-M3 — Deterministic Response Tracking

**Feature Branch**: `m3/response-tracking` *(operator-created; see Principle IV)*
**Spec Directory**: `specs/006-tg-m3-response-tracking`
**Created**: 2026-09-21
**Status**: Draft
**Milestone**: TG-M3 (fourth milestone of `docs/plan/telegram/telegram-moderation-intelligence.md` §25) — 🎯 *the first usable slice*
**Input**: User description: "read docs/plan/telegram/telegram-moderation-intelligence.md and check the docs/runbooks/tg-operator-prerequisites.md, the start specify Milestone number 3 'response tracking'"

## Overview

TG-M2 produced the subjects of measurement and refused to measure anything. TG-M3 is where the
domain finally makes a claim: **this student waited this long, and this named person was responsible
for the group while they waited.**

That claim is the product. Everything that comes afterwards — incidents, alerts, the dashboard, the
model — is either a different kind of subject or a prettier rendering of a number this milestone
computes. So the whole of TG-M3 is spent making that one number impossible to argue with. It is
computed from the platform's own timestamps, never from when the machine noticed; its start is the
moment the student first spoke, not the moment a rule recognised them; its owner is the moderator who
held the group *then*, resolved from ownership history rather than from whoever holds it today; and
the rule that decided a message deserved an answer is recorded by version on the item it opened, so a
number produced by last month's rule can never be silently re-explained by this month's.

It does this with **no model call at all**. That is deliberate and it is the milestone's second
purpose. A rule set written by hand, in one module, versioned by an integer, is the only way to get a
*measured* false-positive and false-negative rate — because the operator's dismissals and manual
additions are exactly that measurement. Without those counts, replacing the rules with a model at
TG-M5 would be an act of faith. With them it is an experiment with a baseline.

Six things ship:

1. **A settled question becomes one item of work.** Consecutive messages from the same person in the
   same group and thread, close together in time, are one thing said — the student who greets, then
   introduces themselves, then finally asks, asked once. The item opens against the **first** of those
   messages, because that is the instant the student began waiting. Recognition is deliberately
   delayed by a short settle window so the whole of what was said is judged together; the delay
   changes the decision, never the clock.
2. **A hand-written, versioned rule set decides what deserves an answer.** It is written for how
   people actually type in these groups: Arabic and dialect interrogatives, support phrasings, a
   trailing question mark that is usually absent, and a stoplist of thanks and emoji that must never
   be mistaken for a question. It is a pure function over normalised text, and the version that opened
   each item is stored beside it.
3. **A moderator's answer closes the item, and the gap is the number.** Two ways to answer are
   recognised — a direct reply to any message of the question, and simply being the next moderator to
   speak in that group and thread — and they are distinguished on the record, because they are not
   equally good evidence. A direct reply can settle an older question out of order. A plain next
   message settles only the oldest waiting item, because one sentence cannot be credited with clearing
   a backlog. An answer that arrived, in the platform's own time, before the question could not have
   answered it, and never closes it.
4. **What is still waiting is on a screen, oldest first, ageing live.** This is the first screen in
   the domain that a moderator would open on purpose rather than an operator opening to configure
   something. It is ordered by how long someone has been waiting, because that is the order the work
   should be done in.
5. **The rule set's mistakes are correctable, and the corrections are the measurement.** An operator
   can dismiss an item the rules should not have opened and can open one by hand that the rules
   missed. Both are recorded as human acts, distinct from rule-opened items, and together they are the
   raw material for the precision and recall figures that decide when the rules have earned their
   replacement.
6. **An abandoned question stops distorting today's picture.** An item nobody ever answered ages until
   a ceiling, then expires. It is still permanently counted as unanswered — that is the honest
   record — but it is excluded from the response-time distribution, which it has no value to
   contribute to, and from "oldest still waiting", which it would otherwise pin at three days forever.

TG-M3 still **judges no behaviour**: no message is categorised, no violation is recognised, no
incident opens, no alert fires, no model is called, and the bot still posts nothing anywhere. It
measures waiting and answering, and nothing else. Both silence guarantees from TG-M1 continue to hold
and continue to be tested.

This is the milestone the operator runbook marks 🎯, and the first one whose smoke test names a
**real pilot group with real students in it**. Two operator decisions that were optional until now
become prerequisites: which group is the pilot and who moderates it, and where the capture process
runs — because from here on an unobserved window is indistinguishable from a moderator who was fast.

## Clarifications

### Session 2026-09-22

- Q: A moderator can answer inside the settle window — a student posts at 10:03:10 and a moderator replies at 10:03:30, before the item is even opened at 10:04:40. Does an item open at all? → A: The item opens normally, and opening immediately evaluates the messages **already stored** after its start using the **same** response-matching rules, so it is answered in the same breath with its true response time of 20 seconds. Rationale: the alternative silently removes the fastest responses from the very distribution that exists to reward them, and corrupts the answered share by dropping its best cases from the denominator. Reusing the one matcher rather than writing a second path at insert time is what keeps the number re-derivable: two implementations are two ways to disagree. A brief window in which a live screen shows an already-answered item as waiting is accepted; the screen corrects itself on its next refresh.
- Q: An edit that adds a question to a burst that previously did not qualify must open a new item dated from the edit. But TG-M2 decided an edit updates the message record's text in place, so by the time the rules re-run there is no stored pre-edit text to prove the burst previously did not qualify. How is the "previously unqualifying" condition decided? → A: The rules re-run over the burst's **current** text, and an item opens only when no item already exists for any message of that burst — "previously unqualifying" becomes "no item exists". The new item anchors on the edited message and starts at the edit's timestamp. Rationale: recovering the pre-edit text from the immutable captured event was rejected because that payload is removed at the end of its retention window, which would make the same edit produce a different item next year than it does today — disqualifying in the one milestone whose claim is that its numbers are reproducible. Two consequences are accepted and written down: a burst whose item was already dismissed or expired does not reopen on an edit, and the resulting item is anchored on the edited message rather than on the burst's first.
- Q: When this milestone ships there are already stored messages from TG-M2's development and smoke testing, and the operator's re-derivation command can produce more at any time. Are attention items opened for messages that were stored before the rules existed? → A: No automatic backfill. Ordinary derivation never reaches backwards, and the operator's existing re-derivation command gains an **opt-in** that also evaluates attention for the named group and optional window, idempotently, reporting how many items it opened, answered and expired. Rationale: it mirrors the previous milestone's own decision exactly — one explicit operator command, never a bulk job hidden behind a screen toggle — and it strictly contains the no-backfill option, since the operator simply does not pass the flag. Because opening also matches already-stored answers, a backfill reconstructs genuine response times for questions that were answered rather than producing a wall of expired items; the ones nobody answered still land expired, which is why the command reports its counts before anyone trusts the figures.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A student's question becomes one item of work, dated when they actually spoke (Priority: P1)

A student writes three messages in a measured group within a minute — a greeting, a sentence about
who they are, and finally the actual problem. That is one question, and it opens **one** item of
work. The item is dated from the *first* of the three, because that is when the student began
waiting. The rules that recognised it record which version of themselves did so. The moderator
recorded as responsible is the one who owned that group at that instant, not the one who owns it when
the item is looked at.

**Why this priority**: Nothing else in the milestone exists without this. If a question does not
become an item, there is nothing to close, nothing to age, nothing to count and nothing to show. And
if the item is dated from when the machine noticed rather than when the student spoke, every response
time in the product is quietly short by the length of the settle window — a number that flatters the
team and cannot be defended.

**Independent Test**: Feed scripted message sets through the recogniser with a controlled clock:
three messages inside the settle window, three spread beyond it, an identical set replayed twice, and
sets from a group nobody marked measured. Confirm one item per settled question, its start equal to
the first message's platform timestamp, one item still after replay, none at all for unmeasured
groups, and the recorded rule version present on every item. No platform credential, no network and
no model are involved.

**Acceptance Scenarios**:

1. **Given** three messages from the same person in the same group and thread, each within the settle
   window of the one before, at least one of which asks something, **When** the question is judged,
   **Then** exactly one item exists, its start is the first message's platform timestamp, and all
   three messages are recorded as belonging to it.
2. **Given** two messages from the same person separated by more than the settle window, both asking
   something, **When** they are judged, **Then** two separate items exist with their own starts.
3. **Given** two people asking in the same group at the same time, **When** they are judged, **Then**
   two items exist, one per person, and neither absorbs the other's messages.
4. **Given** the same messages judged a second time — after a restart, a retry, or a re-derivation —
   **When** they are judged again, **Then** no second item is created, no field of the existing item
   is altered, and the operation completes without error.
5. **Given** a burst whose messages arrive out of order, **When** it is judged, **Then** the item's
   start is still the earliest platform timestamp in the burst, not the first one stored.
6. **Given** a burst in a group that is not marked measured, **When** the stored messages are
   examined, **Then** no item exists and none is ever created for it.
7. **Given** a burst in a forum-style group carrying a thread identifier, **When** it is judged,
   **Then** the burst is confined to that thread, and a message from the same person in a different
   thread of the same group does not extend it.
8. **Given** an item opens, **When** it is inspected, **Then** it records that a rule opened it, which
   version of the rule set did so, and which moderator owned the group at the item's start — with that
   moderator absent rather than guessed when the group had no owner at that instant.
9. **Given** the group's ownership is reassigned after an item opened, **When** the item is inspected
   again, **Then** its responsible moderator has not changed.

---

### User Story 2 - A moderator's answer closes the item, and the gap between is the number (Priority: P2)

A moderator answers. The item stops waiting, the moment of the answer is recorded from the platform's
own timestamp, and the difference between that and the item's start is the first-response time. How
the answer was given — a direct reply to the question, or simply the next thing a moderator said in
that group — is recorded separately, because a direct reply is proof and a next message is inference.
Whoever answered is recorded too, even when it was not the responsible moderator, so that a colleague
covering for someone is visible as help rather than hidden as credit.

**Why this priority**: This is the claim the product is built on. It is also where every plausible
implementation is quietly wrong in a way nobody notices: crediting one message with clearing three
waiting questions, letting a message that arrived before the question close it, or attributing the
response time to whoever happens to own the group today.

**Independent Test**: With a controlled clock and no network, script a group's traffic: a direct
reply, a plain next moderator message, a moderator message in the wrong thread, one in a different
group, a second student's message, a reply arriving with an earlier platform timestamp than the
question, and a single moderator message while three items wait. Confirm exactly which items close,
which stay open, the kind recorded on each, and the computed gap against a hand-calculated value.

**Acceptance Scenarios**:

1. **Given** an open item and a moderator message that directly replies to any message of its burst,
   **When** the answer is matched, **Then** the item is answered, its response moment is the reply's
   platform timestamp, the kind is recorded as a direct reply, and the answering moderator is recorded.
2. **Given** an open item and a moderator message in the same group and thread that replies to nothing,
   sent after the item's start, **When** the answer is matched, **Then** the item is answered and the
   kind is recorded as a plain group message.
3. **Given** three open items in one group and one plain moderator message, **When** the answer is
   matched, **Then** only the oldest item is answered and the other two remain open.
4. **Given** two open items and a moderator message directly replying to the **older** one, **When**
   the answer is matched, **Then** the older item is answered out of order and the newer one remains
   open.
5. **Given** a moderator message that both directly replies to one item and is the next message after
   an older one, **When** the answer is matched, **Then** the direct reply wins and only the replied-to
   item is answered.
6. **Given** a moderator message whose platform timestamp is not strictly after an open item's start,
   **When** the answer is matched, **Then** the item is not closed, regardless of the order the two
   were stored in.
7. **Given** a moderator message in a different thread of the same group, or in a different group,
   **When** the answer is matched, **Then** no item in the original thread is closed.
8. **Given** a moderator who does not own the group answers an item owned by someone else, **When** the
   item is inspected, **Then** it is answered, the responsible moderator is unchanged, and the
   answering moderator is recorded separately.
9. **Given** a message from someone who was not a moderator when they sent it, **When** the answer is
   matched, **Then** no item is closed — even if that person has since been made a moderator.
10. **Given** a message from any bot, including this domain's own, **When** the answer is matched,
    **Then** no item is closed.
11. **Given** a moderator reacts to a student's question with an emoji rather than replying, **When**
    the item is inspected, **Then** it is still open and still ageing — a reaction is not an answer.
12. **Given** an already-answered item and a later moderator message, **When** the answer is matched,
    **Then** the recorded response moment and answering moderator are unchanged.

---

### User Story 3 - What is still waiting is on one screen, oldest first, ageing live (Priority: P3)

The operator opens one screen and sees every question still waiting across every measured group,
oldest at the top, each showing how long it has been waiting right now, which group it is in, the
beginning of what was actually asked, and who is responsible for it. Groups nobody has been made
responsible for are visible as exactly that, rather than quietly absent.

**Why this priority**: The numbers only change behaviour if somebody sees them while the waiting is
still happening. A report produced tomorrow about yesterday's misses is an audit; this screen is the
working queue, ordered the way the work should be done.

**Independent Test**: Seed items with known starts, some answered, some open, some in groups with no
owner. Load the screen and confirm ordering, the displayed waiting times against hand computation, the
truncated question text rendering readably for Arabic content, the unowned groups appearing marked as
such, and the waiting times advancing without the operator reloading the page.

**Acceptance Scenarios**:

1. **Given** several open items with different starts, **When** the screen is loaded, **Then** they are
   listed with the longest-waiting first, and each shows its group, the beginning of the question, the
   responsible moderator, its status and its current waiting time.
2. **Given** the screen is left open, **When** time passes, **Then** the waiting times advance on their
   own without the operator reloading, and a newly answered item leaves the waiting list.
3. **Given** an item in a group with no responsible moderator at its start, **When** the screen is
   loaded, **Then** it is shown as unassigned rather than omitted or attributed to anyone.
4. **Given** question text written in Arabic, **When** it is displayed on any screen in this milestone,
   **Then** it renders in its own reading direction without the surrounding panel changing direction.
5. **Given** an item whose text has passed its retention window and been removed, **When** the screen is
   loaded, **Then** the item is still listed with its timings intact and its text shown as removed.
6. **Given** the screen, **When** the operator looks for a control that would post a message, run a
   bulk job, change the store's shape or call a model, **Then** there is none.

---

### User Story 4 - The rule set's mistakes are correctable, and the corrections are the measurement (Priority: P4)

An operator sees an item the rules should never have opened — a student saying "تمام, شكرا" that
tripped a pattern — and dismisses it as a false positive, with the reason recorded. They also see a
real question the rules missed entirely, and open an item for it by hand. Both acts are recorded as
human acts, distinguishable forever from what the rules did on their own, and both are counted.

**Why this priority**: Without this the rule set's accuracy is an opinion. With it, the false-positive
and miss rates are arithmetic over stored rows — which is the evidence that decides, at TG-M5, whether
a model is actually better than the rules rather than merely newer.

**Independent Test**: Open items by rule, dismiss some with reasons, add some by hand against specific
messages, then compute the accuracy figures from stored rows alone and check them against hand
arithmetic. Confirm a dismissed item never returns to waiting and never contributes a response time,
and that a hand-added item behaves in every other way exactly like a rule-opened one.

**Acceptance Scenarios**:

1. **Given** an open item, **When** an operator dismisses it as a false positive, **Then** it is closed
   with that reason, who closed it and when, it no longer ages, it is not counted as unanswered, and it
   contributes no response time.
2. **Given** a message the rules did not recognise, **When** an operator opens an item against it by
   hand, **Then** an item exists dated from that message's platform timestamp, marked as
   operator-opened with no rule version, and from then on it ages, closes and counts exactly like any
   other.
3. **Given** a message that already anchors an item, **When** an operator tries to open a second item
   against it, **Then** they are prevented rather than creating a duplicate.
4. **Given** a student's question that has genuinely disappeared from the group, **When** an operator
   dismisses the item, **Then** the recorded reason states it was a human judgement that the message
   was removed, and nothing anywhere claims the platform reported a deletion.
5. **Given** a set of rule-opened, dismissed and hand-added items, **When** the accuracy figures are
   computed, **Then** they are derivable from the stored rows alone, and hand-added and dismissed items
   are each counted on the correct side.
6. **Given** a dismissed item, **When** any later moderator message would otherwise have matched it,
   **Then** it is not reopened and not answered.

---

### User Story 5 - An abandoned question stops distorting today's picture without being forgotten (Priority: P5)

A question nobody ever answered ages for a day and then expires. It is permanently counted among the
unanswered, because it was. It contributes no response time, because there was no response. And it
stops being "the oldest thing still waiting", because a screen pinned at three days by one abandoned
item from last week tells the operator nothing about today.

**Why this priority**: This is the difference between a metric that survives contact with a real group
and one the team learns to ignore. It is also the single easiest place to be accidentally dishonest —
in either direction. Treating unanswered items as infinitely slow corrupts the median; dropping them
quietly flatters the team.

**Independent Test**: With a controlled clock, seed items straddling the age ceiling, run the ageing
step twice, and confirm which expired, that running it again changes nothing, and that the expired
items appear in the unanswered count, are absent from the response-time figures, and are excluded from
the oldest-waiting figure while their own count is reported beside it.

**Acceptance Scenarios**:

1. **Given** an item open past the configured age ceiling, **When** the ageing step runs, **Then** it
   becomes expired, with the moment recorded.
2. **Given** an item open but not yet past the ceiling, **When** the ageing step runs, **Then** it is
   untouched and keeps ageing.
3. **Given** the ageing step has already run, **When** it runs again over the same items, **Then**
   nothing changes and no error occurs.
4. **Given** expired items exist, **When** the figures are computed, **Then** they are counted as
   unanswered, contribute no response time, are excluded from the oldest-still-waiting figure, and
   their own count is shown beside it.
5. **Given** an expired item, **When** a moderator answers that question much later, **Then** the
   expired item is not silently reopened, and whatever happens is a recorded decision rather than a
   number quietly changing.

---

### User Story 6 - Every number on the screen can be reproduced by hand (Priority: P6)

For a chosen period, a chosen group and a chosen moderator, the operator sees: how many questions were
asked, how many were answered, the middle and the slow end of the response times, the slowest single
one, how many are still unanswered both as a count and as a share, and how long the oldest one has
been waiting. Each figure states how many measurements it was built from. Where there are too few
measurements for a percentile to mean anything, the screen says so instead of printing a number built
from four points. No average appears anywhere, and no single score is computed for any person.

**Why this priority**: The milestone's acceptance is literally that a hand-computed number matches the
screen exactly. A figure nobody can reproduce is a figure nobody will act on — and the first time the
operator's spreadsheet and the screen disagree, the product loses the argument regardless of which one
is right.

**Independent Test**: Load a fixed set of items with known starts and response moments, including a
group with fewer than the percentile threshold, and compare every displayed figure against values
computed by hand. Confirm periods select on when questions were asked rather than when rows were
written, that unanswered items never enter the response-time figures, and that the percentile is
withheld below the threshold.

**Acceptance Scenarios**:

1. **Given** a fixed set of answered items, **When** the figures are computed for a period, **Then** the
   middle and slow-end response times match hand computation exactly, and the count of measurements is
   displayed beside each.
2. **Given** a period boundary, **When** items are selected into it, **Then** selection uses when each
   question was asked, never when its row was written, and the boundary is inclusive at the start and
   exclusive at the end.
3. **Given** fewer measurements than the percentile threshold, **When** the figures are computed,
   **Then** the slow-end figure is withheld with a stated reason rather than printed.
4. **Given** open, expired and dismissed items in the period, **When** the response-time figures are
   computed, **Then** none of them contributes a value.
5. **Given** any period, **When** the unanswered figure is shown, **Then** it appears as a count and as
   a share of the questions asked, never as a bare number.
6. **Given** any moderator, **When** their figures are shown, **Then** no average appears and no single
   combined score is computed anywhere.
7. **Given** a moderator whose ownership of a group changed inside the period, **When** their figures
   are computed, **Then** each item counts towards whoever owned the group when that question was
   asked.
8. **Given** times are stored in a single universal reference, **When** any moment is displayed,
   **Then** it is rendered in the operator's local timezone, and durations are shown in units a person
   reads rather than raw seconds.

---

### Edge Cases

- **A moderator answers inside the settle window.** The question is not yet recognised when the answer
  arrives. The item opens anyway and is answered in the same breath, from the messages already stored, with
  the true response time measured from the student's first message to the moderator's reply. For a moment
  the queue may show it as waiting; the next refresh corrects it.
- **A student edits a message to add the question.** The words did not exist when the moderator could have
  answered, so the wait is dated from the edit, not from the original send. An item opens only if the burst
  has none already; the rules judge the text as it now stands and never consult the pre-edit wording.
- **A student edits a message to remove the question.** The item already opened; it is not retracted
  automatically, because an edit is not a statement that the question was never asked. An operator may
  dismiss it. The same holds in reverse: an edit to a burst whose item was already dismissed or expired does
  not bring it back.
- **The student answers their own question** ("لقيتها، شكرا"). The item stays open — the sender is not a
  moderator — and ages until a moderator responds, an operator dismisses it, or it expires. The
  acknowledgement stoplist prevents a *new* item opening, but does not close the existing one.
- **A burst of pure thanks and emoji.** Every message matches the acknowledgement stoplist, so no item
  opens even though one message ends in a question mark used decoratively.
- **A single emoji, a sticker, a photo with no caption, or a two-character message.** No item opens.
- **A message with a question mark inside a shared link** and nothing else. The question signal must not
  come from a link's query string.
- **A student mentions a moderator by name without asking anything.** A mention is a question signal in
  its own right, so an item opens; this is a known false-positive source and precisely what the
  dismissal count is for.
- **A student replies directly to a moderator's earlier message with "تمام".** The direct reply is a
  question signal but the content is purely an acknowledgement — the stoplist must win, or every thanks
  opens an item.
- **A message so long it is split by the platform** into consecutive parts. The settle window groups
  them, which is the intended behaviour.
- **A moderator posts several messages answering one question.** Only the first one counts as the
  response; the rest change nothing.
- **A moderator's message arrives with a platform timestamp earlier than the question's** because of
  clock skew or a delayed delivery. It never closes the item.
- **Two moderators answer simultaneously.** Exactly one is recorded as the answering moderator — the one
  with the earlier platform timestamp, with the lower message identifier settling an exact tie — and the
  outcome is the same however many times the matching runs.
- **A group is un-measured while items are open.** Existing items keep their timings and remain visible;
  no new messages are derived, so no new items open and nothing new can close the open ones.
- **A group is promoted to a supergroup while items are open.** The items must follow the surviving
  group, just as ownership assignments did in the previous milestone, or a group's entire waiting queue
  silently disappears.
- **The capture process was off for a window overlapping an item.** Nothing in this milestone claims the
  gap did not happen; a question asked during it was never captured and therefore never opens an item,
  and an answer given during it never closes one — which will show as an unanswered item with a response
  that "never came". The unobserved windows are already recorded; rendering a report as incomplete where
  it overlaps one is a later milestone's job, and this limitation is written down rather than papered
  over.
- **An item's text passes its retention window** and is removed. The item, its timings and its
  attribution survive; only the words are gone.
- **The ownership handover happens in the same second a question is asked.** The interval boundary rule
  from the previous milestone decides it, and the decision is the same every time it is recomputed.
- **A group has no responsible moderator at all.** Items still open, with no responsible moderator, and
  are visible as a coverage problem rather than hidden.
- **A person who sent a message as a student is made a moderator afterwards.** Their old messages still
  count as a student's, because what they were was written onto the message when it was stored.
- **The same question is judged concurrently by two workers.** One item results, and the second attempt
  fails harmlessly rather than producing a duplicate.
- **A message arrives for a thread that no longer exists**, or with a thread identifier where earlier
  messages had none. Threads scope the burst; a change of thread identifier starts a new burst.
- **The operator re-derives a group over a past window.** Questions answered back then come back answered,
  with their real response times; questions nobody answered come back already past the age ceiling and
  expire. The command says how many of each before the figures are read, so a week of development traffic is
  never mistaken for a week of missed students.

## Requirements *(mandatory)*

### Functional Requirements

#### Burst formation — one question, however many messages it took

- **FR-001**: The system MUST group consecutive messages into a burst when they share the same group,
  the same sender and the same thread, and each is separated from the previous by no more than the
  configured settle window.
- **FR-002**: The system MUST treat a difference in group, sender or thread as ending a burst, where
  "no thread" is itself a distinct thread value that only matches other messages with no thread.
- **FR-003**: The system MUST order and bound a burst by the platform's own send timestamps, never by
  the order in which messages were stored or derived.
- **FR-004**: The system MUST open at most one item of work per burst.
- **FR-005**: The system MUST anchor each item to the burst's earliest message and set the item's start
  to that message's platform send timestamp.
- **FR-006**: The system MUST record which messages belong to the item's burst, so that a direct reply to
  any of them can be recognised as answering it.
- **FR-007**: The system MUST make anchoring exclusive: one message can anchor at most one item ever, and
  a competing attempt MUST fail harmlessly rather than create a duplicate.
- **FR-008**: The system MUST delay the judgement of a burst until the settle window has elapsed after
  the message being judged, and MUST NOT let that delay affect the item's start, which is always the
  first message's own timestamp.
- **FR-009**: The system MUST produce the same single item when the same messages are judged repeatedly —
  after a restart, a retried job, or an operator re-derivation — with no field of an existing item
  altered.
- **FR-010**: The system MUST NOT open an item for any message in a group that is not marked measured.

#### The rule set — what deserves an answer

- **FR-011**: The system MUST decide whether a burst deserves an answer using a pure function of the
  burst's normalised text and its senders' recorded properties, with no model call, no network access
  and no reliance on the current time.
- **FR-012**: The system MUST version the rule set by an integer and MUST record on every rule-opened
  item the version that opened it.
- **FR-013**: The system MUST NOT open an item when the burst's sender was recorded as a moderator at the
  moment of sending, is a bot, or is the group or a channel speaking rather than a person.
- **FR-014**: The system MUST NOT open an item for a burst containing a service announcement.
- **FR-015**: The system MUST NOT open an item when every message in the burst matches the
  acknowledgement stoplist, which MUST cover common Arabic and English thanks and confirmations, bare
  emoji, and messages of two characters or fewer.
- **FR-016**: The system MUST open an item when the burst is not purely an acknowledgement and at least
  one of its messages carries a question signal.
- **FR-017**: The system MUST recognise as question signals: an Arabic or Latin question mark; a match
  against the versioned list of Arabic, dialect and English interrogative and support phrasings; a
  mention of a moderator; and a direct reply to a moderator's message.
- **FR-018**: The system MUST NOT require a trailing question mark, because most real questions in these
  groups carry none.
- **FR-019**: The system MUST match against the normalised form of the text produced by the existing
  normaliser, and MUST NOT modify that normaliser.
- **FR-020**: The system MUST keep the rule set, its stoplist and its phrasing list in one place, so that
  what the rules are can be read and reviewed without tracing code paths.
- **FR-021**: The system MUST make the stoplist and phrasing checks robust to the ways people actually
  type — diacritics, repeated letters, mixed Arabic and Latin, and surrounding punctuation — to the
  extent the existing normaliser already provides, and MUST NOT introduce a second normalisation.
- **FR-022**: The system MUST re-run the rules over a burst's **current** text when one of its messages is
  edited, and MUST NOT depend on the message's pre-edit text for that decision.
- **FR-023**: The system MUST open an item on such an edit only when no item already exists for any message
  of that burst, MUST anchor it on the edited message, and MUST set its start to the edit's platform
  timestamp — because the words could not have been answered before they existed.
- **FR-024**: The system MUST NOT reopen, retract or alter an existing item — waiting, answered, dismissed
  or expired — because a message in its burst was edited.

#### Matching an answer and closing the item

- **FR-025**: The system MUST close an open item when a message satisfies all of: same group; its sender
  was recorded as a moderator at send time; not a bot; and its platform send timestamp is strictly later
  than the item's start.
- **FR-026**: The system MUST, at the moment an item opens, evaluate the messages **already stored** with a
  platform timestamp after the item's start using these same matching rules, so that an answer given inside
  the settle window — before the question was recognised — closes the item with its true response moment.
- **FR-027**: The system MUST use one implementation of the matching rules for both that evaluation and the
  matching of newly arriving messages, so the two can never disagree.
- **FR-028**: The system MUST recognise a direct reply — a message replying to any message of the item's
  burst — and MUST record the closure as such.
- **FR-029**: The system MUST recognise a plain group message — the first qualifying moderator message in
  the same group and thread after the item's start — and MUST record the closure as such.
- **FR-030**: The system MUST prefer a direct reply over a plain group message when a single message
  could satisfy both.
- **FR-031**: The system MUST allow a direct reply to close an item out of order, so a moderator
  answering the older of two waiting questions closes the one they answered.
- **FR-032**: The system MUST allow a plain group message to close only the **oldest** open item in that
  group and thread, so one message is never credited with clearing a backlog.
- **FR-033**: The system MUST NOT close an item with a message whose platform timestamp is not strictly
  after the item's start, regardless of the order the two were stored in.
- **FR-034**: The system MUST NOT close an item with a message in a different thread, a different group,
  or from any bot.
- **FR-035**: The system MUST NOT close an item on a reaction. A reaction is not an answer and MUST NOT
  affect any figure in this milestone.
- **FR-036**: The system MUST record on a closed item: the moment of the response, taken from the
  platform's timestamp; which message it was; which moderator sent it; and which of the two kinds of
  closure applied.
- **FR-037**: The system MUST accept a response from **any** moderator, not only the responsible one, and
  MUST record the answering moderator separately from the responsible one.
- **FR-038**: The system MUST leave an already-closed item's recorded response untouched when later
  qualifying messages arrive.
- **FR-039**: The system MUST produce the same outcome when the same messages are matched repeatedly, and
  MUST produce exactly one answering moderator when two moderators answer at the same instant, resolving
  an exact timestamp tie deterministically.
- **FR-040**: The system MUST NOT close a dismissed or expired item.

#### Ageing and expiry

- **FR-041**: The system MUST age an open item continuously from its start until it is answered,
  dismissed or expired.
- **FR-042**: The system MUST expire an item that is still open once its age exceeds the configured
  ceiling, recording the moment of expiry.
- **FR-043**: The system MUST run the ageing step on a schedule and MUST make repeated runs over the same
  items change nothing.
- **FR-044**: The system MUST count expired items permanently among the unanswered.
- **FR-045**: The system MUST exclude expired items from the response-time figures, since they have no
  response, and from the oldest-still-waiting figure, while reporting the expired count beside it.

#### Attribution

- **FR-046**: The system MUST resolve each item's responsible moderator as the group's primary owner at
  the item's **start**, using the ownership history from the previous milestone, and MUST record the
  result onto the item rather than looking it up when the item is read.
- **FR-047**: The system MUST leave the responsible moderator absent, rather than guessing one, when the
  group had no primary owner at that instant, and MUST make such items visible as a coverage problem.
- **FR-048**: The system MUST NOT change an item's recorded responsible moderator when the group's
  ownership is later reassigned.
- **FR-049**: The system MUST attribute an item to whoever the recorded responsible moderator is, in every
  figure computed per moderator, and MUST NOT attribute it to the moderator who answered it.
- **FR-050**: The system MUST make a moderator's answers in groups they do not own visible as a separate
  figure, and MUST NOT treat them as a penalty anywhere.

#### Operator correction

- **FR-051**: The system MUST let an operator dismiss an open item, recording the reason, who dismissed it
  and when, and MUST offer at minimum the reasons "not a real question" and "the message was removed".
- **FR-052**: The system MUST make a dismissed item stop ageing, contribute no response time, and be
  excluded from the unanswered count.
- **FR-053**: The system MUST NOT reopen or close a dismissed item on any later message.
- **FR-054**: The system MUST let an operator open an item by hand against a specific stored message,
  recording it as operator-opened with no rule version, dated from that message's platform timestamp.
- **FR-055**: The system MUST prevent a hand-opened item anchoring on a message that already anchors one.
- **FR-056**: The system MUST make a hand-opened item behave identically to a rule-opened one in every
  other respect — ageing, closure, expiry and every figure.
- **FR-057**: The system MUST make the rule set's false-positive and miss rates computable from stored
  rows alone, from the counts of rule-opened, dismissed and operator-opened items.
- **FR-058**: The system MUST record that a dismissal for a removed message is a human judgement, and MUST
  NOT present it anywhere as something the platform reported.

#### The screen

- **FR-059**: The control panel MUST provide a screen listing every open item across every measured group,
  ordered longest-waiting first.
- **FR-060**: The screen MUST show, per item: the group, the beginning of the question's text, the
  responsible moderator or an explicit unassigned marker, the status, and the current waiting time.
- **FR-061**: The screen MUST update its waiting times on its own while it is open, without the operator
  reloading.
- **FR-062**: The screen MUST offer dismissal and hand-opening, and MUST NOT offer any control that posts
  a message, calls a model, runs a bulk job or changes the store's shape.
- **FR-063**: The control panel MUST display Arabic content in its own reading direction per field, and
  MUST leave the panel's own language and direction unchanged.
- **FR-064**: The control panel MUST show, per group and per moderator for a chosen period: questions
  asked, answered, the middle and slow-end response times with the count each was built from, the slowest
  single response, the unanswered count and share, and the oldest still-waiting age.
- **FR-065**: The control panel MUST render every moment in the operator's local timezone and every
  duration in human units, while the store keeps a single universal reference.
- **FR-066**: The control panel MUST still show an item whose text has been removed by retention, with its
  timings and attribution intact and its text marked as removed.
- **FR-067**: The screens added here MUST join the domain's existing navigation group without altering the
  screens shipped by previous milestones.

#### Measurement arithmetic

- **FR-068**: The system MUST compute a first-response time as the difference between the recorded
  response moment and the item's start, for answered items only.
- **FR-069**: The system MUST select items into a period by the item's start, never by when its row was
  written, with the period inclusive at its start and exclusive at its end.
- **FR-070**: The system MUST exclude open, expired and dismissed items from every response-time figure.
- **FR-071**: The system MUST report the middle, the slow end, the slowest single value and the number of
  measurements together, and MUST withhold the slow-end figure, with a stated reason, when there are
  fewer than ten measurements.
- **FR-072**: The system MUST report the unanswered figure as both a count and a share of the questions
  asked in the period, never as a bare number.
- **FR-073**: The system MUST compute the oldest still-waiting age from currently open items only.
- **FR-074**: The system MUST NOT display an average of any response time, and MUST NOT compute any single
  combined score for any moderator or group.
- **FR-075**: The system MUST produce figures that are reproducible by hand from the stored items, and
  MUST document each figure's definition in one place shared by every screen that shows it.

#### Boundaries, silence and observability

- **FR-076**: The system MUST make no model call, open no incident, send no outbound message and expose no
  inbound endpoint in this milestone.
- **FR-077**: The system MUST keep the bot silent in every group, and this MUST remain covered by an
  automated test.
- **FR-078**: The system MUST keep the domain's module boundaries intact, including that nothing outside
  the platform provider speaks to the platform and that no assessment-side module imports this domain.
- **FR-079**: The system MUST NOT write any message text, in any form, into any log line; correlation MUST
  use identifiers only.
- **FR-080**: The system MUST carry an item's identifier as a correlation identifier on the log records of
  the steps that open, close and expire items.
- **FR-081**: The system MUST make items and their closures follow a group through a platform-side group
  promotion, exactly as ownership assignments already do.
- **FR-082**: The system MUST NOT backfill items automatically: ordinary derivation MUST open items only
  for messages derived from this milestone onwards, and no screen control MUST trigger a bulk evaluation.
- **FR-083**: The operator's existing re-derivation command MUST gain an opt-in that also evaluates
  attention for the named group and an optional window, MUST be idempotent across repeated runs, and MUST
  report how many items it opened, answered and expired.
- **FR-084**: The system MUST make every automated test in this milestone pass with no platform credential
  set, no network access and no model runtime running.

### Out of Scope (deferred to named later milestones)

- Recognising a message as a policy violation, opening an incident, its lifecycle, and the moderator
  actions and enforcement evidence derived from membership and reaction events — **TG-M4**. Those events
  are captured already; nothing here interprets them, and a reaction explicitly changes no figure in this
  milestone.
- Every model call, the classification taxonomy, confidence, severity, and redaction in a live path —
  **TG-M5**. The classification link on an item is shaped for that milestone and left empty here. The
  measured accuracy of this milestone's rule set is the gate that milestone must pass.
- Alert rules, thresholds, quiet hours, the private moderators' group, and any outbound message —
  **TG-M6**. A question waiting past a threshold produces a visible item here and no notification.
- The overview screen, its widgets, the team-performance screen, the ingestion health banner, and the
  marker that renders a report incomplete where it overlaps an unobserved window — **TG-M7**. The figures
  this milestone defines are shown on this milestone's own screens; the dashboard that arranges them is
  later.
- Classification review and reprocessing — **TG-M8**.
- Scheduled digests, the automation tool's configuration, and any endpoint an external tool calls —
  **TG-M9**.
- The job that removes names and message text at the end of their retention period, and the proof that
  re-deriving every captured event reproduces identical derived state — **TG-M10**. Both are shaped for
  here: items survive their text's removal, and opening is idempotent.
- Any composite score for any moderator or group. Excluded from the whole first version, not deferred.
- A conversation model: cross-sender threading, treating a different student's follow-up as part of the
  same question, and any thread hierarchy. The thread identifier scopes a burst and models nothing.
- Inferring that a message was deleted, or who deleted it. The platform reports neither, and nothing here
  will pretend otherwise.
- Treating a reaction as an answer, in this or any later milestone.
- Learning, tuning or adapting the rule set automatically. It changes only when a person edits it and
  raises its version.
- An automatic backfill of items over messages stored before this milestone. Recognition reaches backwards
  only through the operator's own re-derivation command, and only when asked.
- A full localisation of the control panel.

### Key Entities

- **Attention item**: One question waiting for an answer — the derived unit of work this whole domain is
  organised around. It knows when the student began waiting, which messages made up the question, which
  rule version recognised it or which person opened it by hand, who was responsible for the group at that
  instant, and, once answered, when and by whom and on what evidence. It is derived and rebuildable; the
  messages beneath it are the facts.
- **Burst**: Not a stored thing but the grouping rule — what counts as one question when a person sent
  three messages. Defined by same group, same sender, same thread and a gap no longer than the settle
  window, and anchored on its earliest message.
- **Rule set version**: An integer naming a specific set of stoplist entries and phrasings. Recorded on
  every item the rules opened, so a figure produced under one version can never be re-explained by
  another.
- **Response evidence**: How the item was answered — a direct reply to the question, or the next thing a
  moderator said. Recorded distinctly because they are not equally strong evidence, and a later argument
  about a number will be an argument about which of the two it was.
- **Item outcome**: One of waiting, answered, dismissed by a person, or expired unanswered. The four are
  counted differently and deliberately: only answered items produce a response time, only waiting items
  produce an oldest age, dismissed items leave the count entirely, and expired ones stay in the
  unanswered count forever.
- **First-response time**: Not a stored value but the claim the milestone exists to make — the distance
  between the student's first word and the moderator's first answer, defensible because both ends come
  from the platform's own clock.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For a question asked at a known moment and answered at another, the first-response time
  shown on screen equals the hand-computed difference **exactly**, for both a direct reply and a plain
  next moderator message.
- **SC-002**: Three messages from one student inside the settle window produce exactly **one** item whose
  start is the first of the three, and the same three messages spread beyond the window produce two.
- **SC-003**: Judging the same stored messages three times — including with the messages presented in a
  different order — produces one item with identical field values every time.
- **SC-004**: An item's responsible moderator is the one who owned the group at the item's start; changing
  the group's ownership afterwards leaves that item's number and attribution unmoved. This is the
  runbook's own smoke-test check for this milestone.
- **SC-005**: One moderator message while three questions wait closes exactly **one** item — the oldest —
  and a direct reply to the second-oldest closes that one instead.
- **SC-006**: A moderator message whose platform timestamp precedes a question's closes **no** item, in
  every storage order.
- **SC-007**: A reaction by a moderator on a waiting question closes nothing and changes no figure.
- **SC-008**: Across a fixture set of real Arabic and dialect messages, every question the operator marks
  as genuinely needing an answer opens an item, and no message in the acknowledgement stoplist opens one.
- **SC-009**: The rule set's false-positive and miss rates for any period are computable from stored rows
  alone, without reading a log or re-running the rules.
- **SC-010**: An item past the age ceiling is expired by the scheduled step, is counted unanswered,
  contributes no response time, and does not appear in the oldest-still-waiting figure; running the step
  again changes nothing.
- **SC-011**: For a group with fewer than ten answered items in a period, the slow-end figure is withheld
  with a stated reason rather than printed.
- **SC-012**: No average response time and no combined per-moderator score appears anywhere in the panel.
- **SC-013**: The unanswered figure is never displayed without its share of the questions asked.
- **SC-014**: Items selected into a period are selected by when the question was asked; moving a period
  boundary by one second moves exactly the items whose questions fall across it.
- **SC-015**: The waiting queue is ordered longest-waiting first and its waiting times advance while the
  screen is left open, without a reload.
- **SC-016**: A group with no responsible moderator still accumulates items, and those items are visibly
  marked unassigned rather than omitted from the queue.
- **SC-017**: An item whose text has been removed by retention still shows its timings and attribution.
- **SC-018**: The complete automated test suite and the quality gate pass with no platform credential set,
  no network access and no model runtime running.
- **SC-019**: No log line produced anywhere in this milestone contains message text, verbatim or
  normalised, and this is enforced by the existing automated check.
- **SC-020**: Over one full smoke run in a real group, the bot posts nothing anywhere, and no outbound
  message of any kind is sent.
- **SC-021**: The runbook's smoke test passes as written: a question posted at 10:03 and answered at 10:11
  shows **8m**, recorded as a direct reply, attributed to the moderator responsible at 10:03; and
  reassigning the group afterwards does not move the number.
- **SC-022**: A group promoted to a supergroup mid-life keeps every open item and every closed item's
  timings.
- **SC-023**: A question asked at 10:03:10 and answered at 10:03:30 — inside the settle window, before the
  question was recognised — produces an answered item with a response time of **20 seconds**, counted in the
  answered share and in the response-time distribution.
- **SC-024**: Editing a message to add a question opens an item dated from the **edit**, and editing a
  message in a burst that already has an item — waiting, answered, dismissed or expired — opens none and
  alters none.
- **SC-025**: Re-deriving a group over a past window with the attention opt-in opens items for that window,
  answers the ones that were answered with their real response times, expires the rest, reports the three
  counts, and changes nothing at all when run a second time.

## Assumptions

These are reasonable defaults taken where the milestone description did not specify details. Each is
drawn from the source plan, the operator runbook, the constitution, or a previous milestone.

- **Definition of done.** A milestone is done only when implementation exists, tests exist and pass,
  documentation and configuration are updated, a manual smoke test succeeds, no unrelated scope was
  added, and known limitations are written down. Taken from the source plan's §25 preamble.
- **The settle window changes the decision, never the clock.** The source plan is explicit that a delayed
  judgement is deterministic and unit-testable with a controlled clock, and that the item's start is the
  platform's own timestamp. A ninety-second decision delay is irrelevant against thresholds measured in
  minutes; a ninety-second error in the *start* would shorten every response time in the product.
- **Opening an item also looks backwards once, through the same matcher.** Confirmed in this session. A
  moderator can answer before the settle window closes, so opening evaluates the messages already stored
  after the item's start rather than waiting for the next arrival. It reuses the one matching implementation
  instead of a second path at insert time: two implementations of the same rule are two ways for the number
  to disagree with itself, and re-derivability is the point of the milestone. The cost is a brief window
  where a live screen shows an already-answered item as waiting, which the screen's own refresh corrects.
- **An edit is judged on the text as it now stands, and never on what it used to say.** Confirmed in this
  session. The previous milestone made an edit update the message record in place, so the pre-edit wording
  survives only inside the captured event — and only until that payload's retention window ends. Deciding
  anything from it would mean the same edit produces a different item next year than it does today, which is
  exactly the property this milestone cannot afford. "Previously unqualifying" is therefore read as "no item
  exists for this burst". Two consequences are accepted rather than worked around: a dismissed or expired
  burst does not reopen on an edit, and the item an edit opens is anchored on the edited message rather than
  on the burst's first.
- **Recognition never reaches backwards on its own; the operator's command can, on request.** Confirmed in
  this session, mirroring the previous milestone's decision about re-derivation exactly. An automatic
  backfill would greet the operator with a queue of expired development traffic and put TG-M2's smoke testing
  into the first week's unanswered count. An opt-in on the existing command strictly contains the
  do-nothing option, and because opening also matches already-stored answers a backfill reconstructs genuine
  response times rather than a wall of expiries. The command reports what it opened, answered and expired,
  because a backfill writes unanswered history and that should be a thing the operator saw happen.
- **Judgement is anchored on the burst's first message, and may run more than once.** A burst is only
  definitively settled a full window after its *last* message, which is not knowable in advance. Rather
  than predicting it, judgement is scheduled per message and each run computes the same anchor, so
  repeated runs converge on one item. This is why exclusivity on the anchor is a store-enforced rule
  rather than something the code must remember — the same reasoning that made the previous milestone put
  exactly-one-current-primary in the store.
- **Both configuration values already exist and are consumed here for the first time.** The settle window
  and the age ceiling were added by TG-M0 and deliberately left unread. This milestone reads them; no new
  configuration is expected beyond what tuning the rule set or the percentile threshold requires.
- **The percentile threshold is ten measurements, and it suppresses rather than approximates.** From the
  source plan's §18.1, on the grounds that roughly five moderators is a small sample and a percentile
  built from four points is worse than no percentile. Interpolation, not nearest-rank, and no averages
  displayed at all.
- **Any moderator's answer ends the student's wait; only the responsible moderator carries the
  attribution.** The source plan's §12 separates these deliberately, so that a colleague covering for
  someone shows as help rather than as either a penalty or a silent transfer of credit.
- **The rule set is code, not configuration.** The source plan says it lives in one module and is versioned
  by an integer. Making the stoplist and phrasings operator-editable would make the version number
  meaningless and put an untested regular expression on the path of every message; changing them is a code
  change with a version bump and a test.
- **The rule set will be wrong often, and that is the design.** A hand-written rule set on real Arabic
  group chat will open items it should not and miss ones it should not. This is not a defect to be tuned
  away before shipping — the dismissal and hand-addition counts are the milestone's second deliverable,
  and they are what makes TG-M5's model a measurable improvement rather than an assumed one.
- **Expired items are counted unanswered forever, and excluded from two figures.** From §13.5 and §18.3.
  The asymmetry is deliberate and is the honest treatment: they were never answered, so the count must
  keep them; they have no response time, so including them would require inventing one; and they would
  otherwise pin the oldest-waiting figure indefinitely.
- **The ageing step runs on a schedule, reusing the existing background scheduling already in place.** No
  new scheduling mechanism is introduced, and repeated runs are harmless by construction.
- **Reactions are captured, used for nothing here, and interpreted at TG-M4.** The source plan is explicit
  that a reaction is acknowledgement evidence for incidents only and never closes a question. Stating this
  as a requirement rather than an omission is deliberate: it is the most tempting wrong implementation in
  the milestone.
- **A message from someone who was not a moderator at send time never closes an item**, because what they
  were is written onto the message and never recomputed — the previous milestone's rule, relied on here for
  the first time.
- **Items follow a group through a platform-side promotion**, for the same reason ownership assignments do:
  otherwise a group's entire waiting queue disappears at the moment the group becomes a supergroup, silently
  and with every health signal green. The previous milestone's finding about that promotion applies
  unchanged.
- **This milestone shows figures on its own screens; it does not build the dashboard.** The source plan
  assigns the overview and team-performance screens to TG-M7 but requires per-group and per-moderator
  response-time columns here, and the milestone's acceptance is a hand-check of exactly those numbers.
  Every figure is defined once and shared, so TG-M7 arranges them rather than redefining them.
- **The panel per-field reading direction from the previous milestone is reused unchanged.** Per-navigation
  group direction does not exist in the panel framework; the previous milestone measured this and settled on
  per-field direction with the panel's own language left alone. Nothing here revisits it.
- **The panel reads the same store directly with its restricted role, owns no schema change, and its tests
  wrap each case in a transaction.** The established pattern, not revisited.
- **Tests are written where the risk is.** Following Principle I: burst grouping, the rule set against real
  Arabic fixtures, every branch of response matching including out-of-order and oldest-only, attribution at
  an ownership boundary, the arithmetic of the figures including the suppression threshold, ageing and
  expiry, idempotency of opening and closing, and the silence guarantee. No test is written for screen
  listing behaviour, framework wiring, or column types.
- **No real platform access is needed to develop or verify this milestone.** Everything is exercised against
  scripted stand-ins and a controlled clock, as previous milestones established. Real access is needed only
  for the operator's manual smoke test.
- **Operator prerequisites are the runbook's §C row for TG-M3**: the pilot group and its moderator named,
  the live bot added to it as an administrator, and the live credential on the machine that will run the
  capture process — with §B and the previous milestone's §C row still holding. Without these the milestone
  is fully developable and fully testable, but not smoke-testable.
- **Where the capture process runs becomes a real decision at this milestone, and it is the operator's.**
  The runbook's §D states the three options and the consequence of not choosing: a sleeping machine over a
  weekend permanently loses that window, and the resulting gap is indistinguishable from good performance.
  This milestone does not make that choice and does not work around it; it records the limitation.
- **An unobserved window makes a report incomplete, and this milestone does not say so on screen.** The
  windows are recorded already and TG-M7 renders the incompleteness. Until then the limitation is written
  into the milestone's known limitations rather than displayed, and the smoke test is run in a window the
  operator knows was observed.
- **Migration numbering is linear and first-come.** This domain reserved a block of revision identifiers and
  consumes the third of them here. If an assessment milestone lands first it takes the next free number and
  whichever ships second rebases its predecessor link.
- **Nothing in this milestone judges behaviour.** No category, no severity, no confidence, no violation and
  no score. It measures waiting and answering. Stated as an assumption because it is the boundary most
  likely to be crossed by accident: a rule set that recognises "مشكلة" is one small step from a rule set
  that decides how serious it is, and that step belongs to a milestone with a measured baseline and a human
  review path.

## Dependencies

- **TG-M2 must be complete and merged**, as it is: typed messages with the platform's send time, the
  sender, the reply target, the thread, the verbatim and normalised text and the content flags; the
  write-once record of whether a sender was a moderator; sender identities; declared moderators; the
  time-versioned ownership history with exactly one current primary enforced by the store and its
  point-in-time lookup; the deliberate measurement flag and its screen; and the operator's re-derivation
  command. This milestone is the first consumer of all of them.
- **TG-M1 must remain in place**: the append-only captured-event record and its idempotency key, the
  durable capture position, the unobserved-window records, the group records and the bot's standing, the
  identifier-migration linking, the ingestion health section, and the diagnostic command.
- **TG-M0 must remain in place**: the domain package boundary and its automated enforcement, the moderation
  configuration block including the settle window and the age ceiling consumed here, the Arabic normaliser,
  the correlation-identifier whitelist on log records, and the no-message-text rule.
- **M0 and M1 must remain in place**: the running environment, migrations as the sole owner of schema
  change, the queue and background worker including its delayed and scheduled execution, the control panel
  shell with its restricted database role and its transaction-per-test pattern, the health report, and the
  quality gate with its enforced test-store isolation.
- **The source plan** `docs/plan/telegram/telegram-moderation-intelligence.md` — §7.2 for the response-tracking
  flow, §10.7 for the item record, §11 for the burst rule and the deliberate absence of a conversation model,
  §12 for the attribution rules, §13.1–13.5 for the rule set, the response definition, deletions, edits and
  ageing, §17 for the screen, §18.1–18.3 and §18.7 for the exact arithmetic and the accuracy figures, §19.2
  for retention, §20 for idempotency and the failure scenarios, §21 for the correlation identifiers, §22 for
  which tests are earned, §25 for this milestone's own definition, and §26 for why this is the first vertical
  slice.
- **The operator runbook** `docs/runbooks/tg-operator-prerequisites.md` — §C's TG-M3 row for the prerequisites
  and the smoke test, §D for the capture-process decision that must be settled before the pilot, §E's go-live
  checklist, and §F for what the platform will never report.
- **Operator-supplied**: the pilot group and the name of its moderator; the live bot added to that group as an
  administrator; the live credential on the machine that will run the capture process; and a decision on where
  that process runs. Without them the milestone can be fully developed and fully tested, but not smoke-tested
  against real students.
- **No model runtime, no network access and no credential** are required by anything in this milestone's
  automated verification, including its tests.
