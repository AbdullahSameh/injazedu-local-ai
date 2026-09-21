# Feature Specification: TG-M2 — Groups, Users, Messages and Moderator Ownership

**Feature Branch**: `m2/moderator-ownership` *(operator-created; see Principle IV)*
**Spec Directory**: `specs/005-tg-m2-groups-and-ownership`
**Created**: 2026-09-12
**Status**: Draft
**Milestone**: TG-M2 (third milestone of `docs/plan/telegram/telegram-moderation-intelligence.md` §25)
**Input**: User description: "read docs/plan/telegram/telegram-moderation-intelligence.md and check the docs/runbooks/tg-operator-prerequisites.md, the start specify Milestone number 2 'Groups, users, messages and moderator ownership'"

## Overview

TG-M1 captured everything and interpreted nothing. TG-M2 is where the captured stream becomes
**facts a person can be held to**: which group a message was in, who sent it, whether that sender was
a moderator **at the moment they sent it**, and which moderator was responsible for that group **at
that instant**.

That last phrase is the whole milestone. Every number the domain will ever publish — a response time,
an unanswered count, a missed incident — is attributed to a named person, and an attribution is only
as honest as its timestamp. If ownership of a group is stored as "who owns it now", then next month's
reassignment silently re-attributes last month's misses to someone who was not there, and there is no
way to recover the truth because the previous value was overwritten. Ownership is therefore stored as
**history from the first day**, not retrofitted once someone notices — because retrofitting it is
impossible.

The same reasoning drives the second non-obvious decision here: whether a sender was a moderator is
**snapshotted onto each message at the moment the message is stored**, not looked up later. Promoting
a helpful student to moderator next month must not retroactively convert last month's student
questions into last month's moderator answers, which is exactly what a live lookup would do.

Five things ship:

1. **Typed messages, derived and re-derivable.** Each captured event belonging to a measured group
   becomes one message record: the platform's own send time, the sender, the reply target, the thread,
   the text verbatim, a normalised form for later matching, and coarse flags for links, phone numbers,
   mentions and forwards. Deriving the same event twice produces the same single record, so the
   interpretation step is now genuinely replayable — which is what TG-M1's append-only record was for.
2. **Sender identities, kept as pseudonyms.** Every person the bot observes gets one identity record
   keyed by the platform's numeric identifier. That number is a pseudonym and survives forever so
   historical counts stay joinable; the human-readable name beside it is personal data and is shaped
   from the start so it can be removed later without breaking a single metric.
3. **Deliberate measurement, and a way to catch up.** A group the bot happens to be in is still not a
   group anyone agreed to measure. Measurement stays an explicit act. Because TG-M1 captured events
   for unmeasured groups too, opting a group in later can reach back — through one operator command
   that re-derives the stored events for that group, never through a switch that silently starts a
   bulk job.
4. **Moderators as declared people, with time-versioned ownership of groups.** A moderator is someone
   the operator named, with a stable display name of their own that a platform profile rename cannot
   change. Ownership binds a moderator to a group over a half-open interval. Exactly one *current*
   primary owner per group is a rule **the store enforces**, not a rule someone must remember, and a
   reassignment closes the outgoing interval and opens the incoming one as a single atomic act — so
   there is never an instant with two owners or none.
5. **The first screens in the domain.** Two of them: the groups list, where measurement is switched on
   one group at a time and the bot's standing is visible; and the moderators list with its assignments
   view, where people are mapped and ownership is handed over. These are the first screens in a new
   navigation group, and the panel's existing model-roster screen is given a group of its own in the
   same change so nothing is left orphaned at the root.

TG-M2 deliberately **judges nothing**. No message is recognised as a question, no item is opened, no
response is matched, no violation is categorised, no duration is computed, no model is called, and no
dashboard number appears. It produces the *subjects* of every later measurement and none of the
measurements. The bot remains silent and the machine remains closed: both TG-M1 guarantees continue
to hold and continue to be tested.

## Clarifications

### Session 2026-09-12

- Q: TG-M1 promised that opting a group into measurement later works retroactively within the retention window, but TG-M1's handling step already marked every captured event handled. How should events captured *before* a group was measured be derived? → A: One explicit operator command that re-derives the stored events for a named group, optionally bounded by date, idempotently. The measurement switch documents the command but never runs it. Rationale: it keeps TG-M1's promise at the smallest honest scope, and a bulk re-derivation is a decision the operator should make deliberately rather than a hidden consequence of flipping a switch in a screen.
- Q: The source plan §9 says an edited message is "stored as a new version of the text, never overwriting the original", but §10.6 gives the message record a single verbatim/normalised text pair plus an edit timestamp, and no version table exists anywhere in the data model. How is an edit stored? → A: The message record's text is updated and its edit time recorded; the pre-edit text survives verbatim in the append-only captured event that carried it, for the retention window. "Never overwriting the original" is already satisfied by the captured event being immutable, and the verbatim/normalised pair keeps its actual meaning — raw text versus normalised text, not pre-edit versus post-edit. No additional table, no additional join on every text read.
- Q: A moderator record points at a sender identity, which only exists once that person has been observed posting — but the operator runbook has the operator collect raw numeric identifiers at TG-M2, possibly before those people have posted anything. → A: Mapping a raw numeric identifier creates a placeholder identity record with no name and no first-observation time; the real profile fills in on first observation. This keeps one identity table and one relational link, and lets the runbook's "collect the ids" step work before anyone has posted — which is also what makes the smoke test's ordering trap disappear.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Captured events become typed messages, exactly once (Priority: P1)

A student posts in a measured group. The captured event is interpreted into one message record
carrying the platform's own send time, who sent it, what it replies to, which thread it is in, its
text exactly as posted, and a normalised form of that text for later matching. Interpreting the same
captured event again — after a restart, after a re-drive, after a bug fix — produces the same single
record with the same values. Interpreting an event from a group nobody agreed to measure produces no
message record at all.

**Why this priority**: This is the milestone's product. Every later milestone reads message records,
not captured events, and every metric is arithmetic over their timestamps. Idempotent derivation is
what makes the append-only capture record from TG-M1 worth having: without it, "replay the stream"
means "double every count". On its own this story turns an opaque event log into a queryable record
of what was said, when, by whom, and in reply to what.

**Independent Test**: Feed a scripted set of captured events through the interpreting step, then feed
the identical set again, then feed it a third time with the events shuffled. Confirm one message
record per distinct message, identical field values across all three passes, send times taken from
the platform's own stamp rather than from when interpretation ran, and zero message records for
groups not marked measured. No platform credential and no network access are involved.

**Acceptance Scenarios**:

1. **Given** a captured event carrying a message in a measured group, **When** it is interpreted,
   **Then** one message record exists holding the group, the platform's message identifier, the
   sender, the platform's send time, the text verbatim, a normalised form of that text, the thread
   identifier where present, and a link back to the captured event it came from.
2. **Given** a message record already exists, **When** the same captured event is interpreted again,
   **Then** no second record is created, no field is corrupted, and the operation completes without
   error.
3. **Given** a captured event whose group is not marked measured, **When** it is interpreted, **Then**
   no message record, no sender identity and no other interpreted state is created, and the captured
   event is still marked handled.
4. **Given** a message that replies to an earlier one, **When** it is interpreted, **Then** the reply
   target is recorded as the platform's own message identifier, and this works even when the replied-to
   message was never captured because it predates measurement.
5. **Given** a message posted by the group or a channel acting without a personal sender, **When** it
   is interpreted, **Then** the record represents that sender form distinctly rather than inventing a
   person or discarding the message.
6. **Given** a captured event that is a service announcement rather than something a person typed,
   **When** it is interpreted, **Then** it is recorded and flagged as a service announcement rather
   than discarded or counted as a person speaking.
7. **Given** a message carrying media, a link, a phone number, a mention or a forward marker, **When**
   it is interpreted, **Then** the coarse kind of media and those content flags are recorded, without
   this milestone drawing any conclusion from them.
8. **Given** a captured event reporting that a message was edited, **When** it is interpreted, **Then**
   the message record's text and normalised form are updated, its edit time is recorded, and its
   original send time is unchanged — the pre-edit text remaining available in the immutable captured
   event that carried it.
9. **Given** any message record, **When** its send time is compared with the time its captured event
   was stored, **Then** the platform's send time is the one used for ordering and the storage time is
   never substituted for it.

---

### User Story 2 - A group is measured only when someone decides it is (Priority: P2)

The bot is an administrator in several groups; only some of them are ones the organisation agreed to
measure. The operator opens the groups screen, sees each group with its title, the bot's standing in
it and when anything last happened there, and switches measurement on for one group, deliberately. A
group switched on today can be made to cover the days before, by running one command that re-derives
what was already captured for it — reported, bounded, and never triggered by the switch itself.

**Why this priority**: Presence is not consent. The bot being in a group is an accident of how the
operator set it up; measuring the people in it is a decision with consequences for real moderators,
and the plan is explicit that it must be taken one group at a time. This also delivers the first
screen in the domain, which is what turns TG-M1's database rows into something the operator can act
on. It ranks below derivation because without derivation there is nothing to measure.

**Independent Test**: With captured events present for two groups, mark one measured, interpret, and
confirm messages exist for it and none for the other. Then mark the second measured and run the
re-derivation command for it, and confirm its previously-captured events now produce messages with
their original timestamps, that running the command twice changes nothing, and that switching
measurement on by itself produced nothing.

**Acceptance Scenarios**:

1. **Given** a newly discovered group, **When** it is first recorded, **Then** it is not measured, and
   it becomes measured only by a deliberate act.
2. **Given** the groups screen, **When** the operator views it, **Then** each group shows its
   identifier, kind, title, the bot's standing and when that was observed, whether the bot holds the
   ability to remove messages there, when anything last happened there, and whether it is measured.
3. **Given** a group on that screen, **When** the operator switches measurement on, **Then** events
   arriving from that moment produce message records, and **no** bulk re-derivation of earlier events
   is started by the switch.
4. **Given** a group newly switched on with captured events predating the switch, **When** the operator
   runs the re-derivation command for that group, **Then** those events produce message records
   carrying their original send times, and the command reports how many events it examined, derived
   and skipped.
5. **Given** the re-derivation command has already run for a group, **When** it is run again over the
   same range, **Then** no duplicate message records are created and the report shows nothing new
   derived.
6. **Given** captured events whose content has already been removed by retention, **When**
   re-derivation reaches them, **Then** they are reported as skipped-because-purged rather than
   producing an empty message record or failing the run.
7. **Given** the re-derivation command, **When** it is invoked, **Then** it targets one named group,
   accepts an optional date bound, and is the only path by which earlier events are interpreted — no
   screen performs it.
8. **Given** a group switched back off, **When** later events arrive from it, **Then** they are still
   captured, produce no new message records, and the message records already derived are left intact.

---

### User Story 3 - Moderators are named people, and a message remembers what its sender was (Priority: P3)

The operator maps themselves and their colleagues as moderators, using the numeric identifiers
collected from the platform — which works whether or not those people have posted yet. From then on,
every message stored carries whether its sender was a moderator **at the time of that message**.
Mapping a new moderator next month changes nothing about last month's messages, because the answer
was written down rather than looked up.

**Why this priority**: This single flag is the dividing line the entire product rests on: a message
is either something that needs answering or part of the answering. Getting it from a live lookup would
mean every promotion silently rewrites history — the flattering direction, which is the worst kind of
error to have. It ranks below measurement because a group must be measured before its senders matter.

**Independent Test**: Map a moderator by raw numeric identifier before that person has been observed,
confirm a placeholder identity exists with no name, then interpret a message from them and confirm
the placeholder fills in and the message is flagged as from a moderator. Separately, interpret a
message from an unmapped sender, then map that sender as a moderator, and confirm the earlier
message's flag has not changed.

**Acceptance Scenarios**:

1. **Given** a person observed sending a message in a measured group, **When** it is interpreted,
   **Then** one sender identity record exists for them keyed by the platform's numeric identifier,
   holding the username and display name as observed, whether they are a bot, when they were first
   observed and when last observed.
2. **Given** an existing sender identity, **When** the same person is observed again with a changed
   username or display name, **Then** the record reflects the new values and its last-observed time
   advances, while its first-observed time does not move.
3. **Given** a numeric identifier for someone never yet observed, **When** the operator maps them as a
   moderator, **Then** a placeholder identity record is created with no name and no first-observed
   time, and the mapping succeeds.
4. **Given** such a placeholder, **When** that person is first observed sending a message, **Then**
   the placeholder fills in with their observed name and first-observed time rather than a second
   identity being created.
5. **Given** a mapped moderator, **When** they send a message in a measured group, **Then** the
   message is recorded as being from a moderator.
6. **Given** a message already recorded as **not** from a moderator, **When** its sender is later
   mapped as a moderator, **Then** that earlier message's flag is unchanged.
7. **Given** a moderator whose platform display name later changes, **When** reports name them,
   **Then** the operator-set display name is used, so a platform profile rename cannot alter who a
   report is about.
8. **Given** an attempt to map one sender identity to two moderators, or one moderator to two sender
   identities, **When** it is attempted, **Then** the store refuses it.
9. **Given** a moderator who has left, **When** the operator marks them inactive, **Then** their
   record, their assignment history and every message flag that referenced them are preserved, and
   only their availability for new assignments changes.

---

### User Story 4 - Ownership of a group is history, not a current value (Priority: P4)

The operator assigns a moderator as the primary owner of a group, and optionally others as backups.
Three weeks later ownership is handed over. Asked who was responsible for that group at a specific
past instant, the system answers with the person who was responsible **then** — and reassigning
ownership today does not move that answer by a single second. At every instant there is at most one
current primary owner, and the store is what guarantees it.

**Why this priority**: This is the fact that makes attribution defensible rather than merely
plausible. It is also the one piece of this milestone that cannot be added later: once a current-owner
value has been overwritten, the previous owner is unrecoverable and every historical report is quietly
wrong. It ranks below the sender flag only because messages must exist before their groups' owners
matter.

**Independent Test**: Open an assignment, close it, open a successor, and query responsibility at
instants before, exactly at, inside and after each interval — confirming the interval start is
inclusive, its end exclusive, and that no query returns the current owner for an instant they did not
cover. Separately, attempt to open a second current primary for the same group and confirm the store
refuses it.

**Acceptance Scenarios**:

1. **Given** a group and a moderator, **When** an assignment is opened, **Then** it records the group,
   the moderator, the role, the instant it takes effect, an open-ended expiry, and an optional note
   explaining it.
2. **Given** a group with a current primary owner, **When** a second current primary assignment for
   that group is attempted, **Then** the store refuses it and no partial state remains.
3. **Given** a group with a current primary owner, **When** ownership is handed over, **Then** the
   outgoing assignment's expiry and the incoming assignment's effective instant are set in a single
   atomic act, leaving no instant with two primary owners and no instant with none.
4. **Given** a closed assignment interval, **When** responsibility is queried at its effective
   instant, **Then** it is returned; **When** queried at its expiry instant, **Then** it is not — the
   interval is closed at its start and open at its end.
5. **Given** an instant covered by no assignment at all, **When** responsibility is queried, **Then**
   nothing is returned, and the current owner is explicitly **not** substituted.
6. **Given** a past instant with a known owner, **When** ownership is reassigned today and the same
   past instant is queried again, **Then** the answer is unchanged.
7. **Given** a group with backup owners alongside a primary, **When** responsibility is queried,
   **Then** the primary is the responsible owner and the backups are recorded and visible but are not
   returned as responsible.
8. **Given** any assignment, past or current, **When** ownership changes, **Then** no assignment row is
   deleted or rewritten — the history is append-and-close only.
9. **Given** a measured group with no primary owner, **When** it is examined, **Then** it is recorded
   and surfaced as unassigned rather than being given an implied owner.

---

### User Story 5 - The operator runs all of this from screens, not from SQL (Priority: P5)

Everything in the three stories above is managed from two screens. The groups screen switches
measurement on and shows coverage. The moderators screen maps people, and its assignments view opens,
closes and hands over ownership — with reassignment as one action rather than two edits the operator
must remember to pair. When mapping candidates, the screen proposes the people the platform has been
observed treating as administrators of that group, so the operator confirms rather than types
identifiers.

**Why this priority**: The runbook's TG-M2 step is an operator sitting down and doing exactly this,
and the smoke test for the whole milestone is performed through these screens. It also removes the
class of error that matters most here — a hand-edited reassignment that leaves two current primaries
or a gap — by making the correct sequence the only available action. It ranks below the facts
themselves because the facts are what get tested; the screens are how they are entered.

**Independent Test**: Exercise each screen's actions against a test store inside a transaction:
switch measurement, add a moderator from a proposed candidate, open an assignment, and perform a
reassignment — confirming the reassignment is atomic by asserting that an induced failure partway
leaves the original owner intact and no second current primary. Confirm the panel makes no platform
call and runs no schema change.

**Acceptance Scenarios**:

1. **Given** the control panel, **When** it is opened, **Then** the two new screens appear under a
   single navigation group for this domain, and the panel's existing model-roster screen is placed
   under a navigation group of its own rather than left at the root.
2. **Given** the moderators screen, **When** the operator adds a moderator, **Then** they may supply a
   stable display name and either pick an observed sender identity or enter a numeric identifier that
   has not been observed yet.
3. **Given** a group whose administrators the platform has been observed reporting, **When** the
   operator maps a moderator for it, **Then** those observed administrators are offered as candidates,
   and confirming one is what creates the mapping — the platform's view is a proposal, never an
   automatic grant.
4. **Given** a group with a current primary owner, **When** the operator performs the reassign action,
   **Then** the incumbent interval closes and the successor interval opens in one atomic act, and if
   any part fails the previous state is intact.
5. **Given** the assignments view, **When** the operator inspects a group's history, **Then** every
   past and current assignment is listed with its role, its interval and its note, in chronological
   order.
6. **Given** either screen, **When** any action on it runs, **Then** the panel makes no call to the
   platform, initiates no model call, and performs no schema change.
7. **Given** these screens, **When** they render, **Then** their direction and labels suit the
   operator's language for this navigation group, without altering the rest of the panel.
8. **Given** measured groups, **When** the groups screen is viewed, **Then** those with no primary
   owner and those where the bot is not an administrator are distinguishable at a glance.
9. **Given** the optional reference to a course in the organisation's main application, **When** the
   operator sets it on a group, **Then** it is stored as a plain value with no relational link and no
   validation against that other system, which lives elsewhere and is not consulted.

---

### User Story 6 - Identity changes and coverage loss do not break the record (Priority: P6)

A group is promoted and its platform identifier changes. Ownership follows the group, not the
identifier: the assignments continue uninterrupted, because a technical migration is not a handover.
Elsewhere, the bot is quietly demoted and several kinds of event stop arriving with no error anywhere
— the standing change is recorded, the group stays marked measured so the loss is visible rather than
tidied away, and it is surfaced as a coverage problem. And every human-readable name in this milestone
is stored so that it can later be removed without breaking a single count.

**Why this priority**: These are the ways the record silently degrades. The plan names a lost
administrator right as the single most likely way the whole system stops working, and an identifier
migration as the classic trap in this platform. Each costs little here and is expensive or impossible
to repair later. It is last because it protects the five stories above rather than adding a capability.

**Independent Test**: Feed a group-promotion sequence and confirm the assignments are re-pointed to
the surviving identity, that no assignment interval was closed or opened by the migration, and that
messages before and after count as one group's history. Feed a demotion and confirm the standing is
recorded, measurement is not switched off, and the group appears as a coverage problem. Assert that
every name field carries the marker a later removal job needs, and that removing a name leaves every
timestamp and count intact.

**Acceptance Scenarios**:

1. **Given** a measured group with ownership assignments, **When** its platform identifier changes
   because it was promoted, **Then** the assignments are re-pointed to the surviving identity in one
   atomic act, with no interval closed and no interval opened — a migration is not an ownership change.
2. **Given** the same migration, **When** messages from before and after it are examined, **Then** they
   are countable as one group's continuous history and none is lost or double-counted.
3. **Given** the bot is demoted in a measured group, **When** that is observed, **Then** the recorded
   standing changes, measurement is **not** switched off, and the group is surfaced as a coverage
   problem.
4. **Given** the bot is removed from a measured group, **When** that is observed, **Then** the standing
   reflects it, the group's existing messages and assignments are untouched, and the decision to stop
   measuring is left to the operator.
5. **Given** a sender identity, **When** it is examined, **Then** the platform's numeric identifier is
   present as the durable pseudonym and the human-readable name beside it carries a marker showing
   whether it has been removed.
6. **Given** a sender identity linked to a moderator, **When** the retention rules are applied, **Then**
   its name is excluded from removal, because reports must be able to name the person responsible.
7. **Given** a message record, **When** it is examined, **Then** its text carries a marker for later
   removal, and removing the text leaves the group, sender, send time, reply target, moderator flag and
   every other timing intact.
8. **Given** any of these removal markers, **When** this milestone runs, **Then** nothing is actually
   removed — only the shape exists here, and the removal job belongs to a later milestone.

---

### Edge Cases

- **The same event interpreted twice, concurrently.** Two workers picking up the same captured event at
  once must still produce one message record. Uniqueness has to be the store's guarantee, not a
  check-then-insert the application performs.
- **A reply to a message that was never captured.** The replied-to message may predate measurement or
  predate the bot joining. The reply target is the platform's own identifier, deliberately not a
  relational link, so this is the normal case rather than a violation.
- **A sender who is a bot.** Recorded as such, and never treated as a moderator regardless of mapping
  attempts, because a bot's message can never be a human answering.
- **A message with no personal sender at all.** Anonymous administrators and channel posts carry a
  group or channel as the sender instead of a person. Both must be representable, and neither may be
  silently attributed to a person.
- **A message with no text.** A sticker, a photo with no caption, a voice note. The record exists with
  no text, its coarse media kind recorded; the normalised form is absent rather than an empty string
  that later matching would treat as content.
- **Text that normalises to nothing.** A message of only punctuation or invisible characters. The
  verbatim text is preserved; the normalised form may legitimately be empty, and later matching must
  not mistake that for a missing record.
- **A person promoted to moderator between two of their own messages.** The earlier message stays
  flagged as not from a moderator and the later one as from a moderator. This is correct, will look
  inconsistent to someone reading a transcript, and must be documented rather than smoothed over.
- **A moderator demoted, then re-mapped.** The flag on each message reflects the mapping at that
  message's time. Nothing is rewritten in either direction.
- **A reassignment whose effective instant is in the past or the future.** Backdating a handover is a
  legitimate operator correction. It must not be able to produce two overlapping current primaries, and
  the constraint must hold for the instant that matters — the present — without pretending to police
  every historical overlap.
- **Two operators reassigning the same group at once.** One must fail cleanly. The invariant is the
  store's, so the loser gets a refusal rather than a corrupted pair of intervals.
- **A group promoted while an assignment reassignment is mid-flight.** Both touch the same group's
  assignments. Each must be atomic on its own, and the combination must leave exactly one current
  primary.
- **A group whose promotion was observed only from the new identity.** The surviving identity may
  appear without its predecessor having been recorded. The link must still be establishable, and the
  absence of prior history must not be mistaken for a group with no history.
- **Measurement switched on for a group whose captured content has already been removed by retention.**
  Re-derivation must report those events as skipped rather than creating hollow message records or
  aborting the run.
- **Re-derivation run for a group that is not measured.** It must refuse, so that a bulk derivation
  cannot be used as a back door around the deliberate measurement decision.
- **Re-derivation run twice, or run while events are still arriving.** It must converge on the same
  records either way, and must not interfere with ordinary live derivation.
- **A very large re-derivation.** It must proceed in bounded batches and report progress, so the
  operator can tell a long run from a stalled one.
- **An event whose group has never been recorded.** The group record must be created rather than the
  event being dropped — the same rule TG-M1 established, and it must keep holding here.
- **A moderator mapped to an identifier that turns out to belong to someone else.** The mapping is
  operator-entered and can be wrong. Unmapping and re-mapping must be possible, must not delete history,
  and must not retroactively change any message flag already written.
- **Clock skew between the platform's stamp and the machine's.** The platform's stamp orders everything;
  the machine's clock only records when interpretation happened. A skewed machine clock must not
  reorder messages or shift an assignment boundary decision.
- **A message whose send time falls exactly on an assignment boundary.** The interval is closed at its
  start and open at its end, so exactly one owner covers that instant. This must be tested at the
  boundary, not near it.
- **Names that are absent, extremely long, or contain only emoji.** A stable operator-set display name
  exists precisely so reports never depend on what a platform profile happens to contain.

## Requirements *(mandatory)*

### Functional Requirements

**Deriving typed messages**

- **FR-001**: The system MUST interpret each captured event that carries a message in a measured group
  into exactly one message record, holding the group, the platform's message identifier, the sender,
  the platform's send time, the verbatim text, a normalised form of that text, the thread identifier
  where present, the reply target where present, and a link back to the captured event it came from.
- **FR-002**: Deriving the same captured event more than once MUST produce the same single message
  record with the same values. Idempotency MUST be guaranteed by a uniqueness constraint in the store
  on the pair of group and platform message identifier, not by an application-level check.
- **FR-003**: The platform's own send time MUST be the authoritative time for a message's ordering and
  for every later measurement. The time the system stored or interpreted it MUST NOT be substituted.
- **FR-004**: The reply target MUST be recorded as the platform's own message identifier and MUST NOT
  be a relational link, because the replied-to message may never have been captured.
- **FR-005**: A message with no personal sender — posted anonymously by an administrator, or by a
  channel — MUST be representable distinctly, without inventing a person and without discarding the
  message.
- **FR-006**: A service announcement MUST be recorded and flagged as such rather than discarded or
  counted as a person speaking.
- **FR-007**: The coarse kind of any attached media and flags for the presence of a link, a phone
  number, a mention and a forward marker MUST be recorded. This milestone MUST draw no conclusion from
  them.
- **FR-008**: The normalised form MUST be produced by the normaliser the previous milestone introduced.
  The verbatim text MUST never be modified by normalisation.
- **FR-009**: A message with no text MUST produce a record with no text and no normalised form, rather
  than an empty string.
- **FR-010**: When a captured event reports that a message was edited, the system MUST update that
  message record's text, normalised form and edit time, and MUST leave its original send time
  unchanged. The pre-edit text MUST remain available in the immutable captured event that carried it;
  no additional text-version record is created.
- **FR-011**: Interpretation MUST handle the kinds of captured event this milestone covers — a message,
  an edited message, and a change in the bot's own standing in a group — and MUST leave every other
  kind stored and marked handled without deriving anything from it.
- **FR-012**: Interpretation MUST remain confined to the background worker. The capture process MUST
  NOT derive any interpreted state, and the request-serving process MUST NOT either.
- **FR-013**: The system MUST provide a way to hand every not-yet-interpreted captured record to the
  interpreting process in the platform's assigned order, so a backlog accumulated while that process
  was stopped drains without loss or duplication.

**Sender identities**

- **FR-014**: The system MUST record one sender identity per distinct person observed, keyed uniquely
  by the platform's numeric identifier for them, holding the username and display name as observed,
  whether they are a bot, when they were first observed and when they were last observed.
- **FR-015**: Observing an existing sender again MUST refresh the observed name values and advance the
  last-observed time, and MUST NOT move the first-observed time.
- **FR-016**: The platform's numeric identifier MUST be treated as a durable pseudonym and MUST be
  retained indefinitely, so historical counts stay joinable after names are removed.
- **FR-017**: A sender recorded as a bot MUST NOT be treated as a moderator under any circumstances.

**Deliberate measurement, and catching up**

- **FR-018**: A group MUST NOT be measured on discovery. Becoming measured MUST require a deliberate
  act, performed on a screen in this milestone.
- **FR-019**: Events from groups that are not measured MUST continue to be captured and MUST produce no
  message record, no sender identity and no other interpreted state.
- **FR-020**: The system MUST provide one operator-run command that re-derives the stored captured
  events for a single named group, optionally bounded by date, so that measuring a group can reach back
  over what was already captured.
- **FR-021**: Re-derivation MUST be idempotent, MUST proceed in bounded batches, and MUST report how
  many captured events it examined, derived and skipped.
- **FR-022**: Re-derivation MUST NOT be triggered by switching measurement on, MUST NOT be invocable
  from a screen, and MUST refuse to run for a group that is not measured.
- **FR-023**: Captured events whose content has already been removed by retention MUST be reported as
  skipped by re-derivation, and MUST NOT produce a message record with no content and MUST NOT abort
  the run.
- **FR-024**: Switching measurement off MUST stop new message records being derived for that group and
  MUST leave the records already derived intact.

**Moderator identity**

- **FR-025**: A moderator MUST be an operator-declared person holding a display name that is stable and
  independent of any platform profile, an active flag, an optional free reference to a user of the
  organisation's main application with no relational link to it, and an optional note.
- **FR-026**: A moderator MUST be linked to exactly one sender identity, and a sender identity to at
  most one moderator. Both MUST be enforced by the store.
- **FR-027**: Mapping a moderator MUST be possible using a numeric platform identifier for someone never
  yet observed. Doing so MUST create a placeholder sender identity with no name and no first-observed
  time.
- **FR-028**: When a person with a placeholder identity is first observed, that placeholder MUST fill in
  with the observed values rather than a second identity being created.
- **FR-029**: Reports MUST use the operator-set display name, so a platform profile rename cannot change
  who a report is about.
- **FR-030**: Marking a moderator inactive MUST preserve their record, their assignment history and
  every message flag referencing them, and MUST affect only their availability for new assignments.
- **FR-031**: Being a moderator MUST be a fact this domain holds, never read live from the platform's
  administrator list. The platform's observed administrators MAY be offered as candidates, and
  confirming one MUST be what creates the mapping.

**The moderator snapshot on each message**

- **FR-032**: Every message record MUST carry whether its sender was a moderator, resolved at the moment
  the record is written.
- **FR-033**: That flag MUST NOT be recomputed. Mapping, unmapping or deactivating a moderator later
  MUST leave every already-written flag unchanged.
- **FR-034**: The flag MUST depend only on whether the sender was a declared moderator at that time, and
  MUST NOT depend on whether they owned the group in question — anyone answering ends a student's wait.

**Time-versioned ownership**

- **FR-035**: An ownership assignment MUST bind a moderator to a group with a role of primary or backup
  over an interval that is closed at its effective instant and open at its expiry, with an open-ended
  expiry meaning current, and MUST carry an optional note.
- **FR-036**: At most one **current primary** assignment per group MUST exist, and this MUST be enforced
  by a constraint in the store rather than by application discipline.
- **FR-037**: Handing over ownership MUST close the incumbent interval and open the successor interval
  in a single atomic act, leaving no instant with two primary owners and no instant with none. A partial
  failure MUST leave the previous state intact.
- **FR-038**: Assignment history MUST be append-and-close only. No assignment record may be deleted, and
  no closed interval may be rewritten.
- **FR-039**: A measured group with no current primary assignment MUST be recorded and surfaced as
  unassigned, and MUST NOT be given an implied owner.
- **FR-040**: Backup assignments MUST be recorded and visible, and MUST NOT be returned as the
  responsible owner.

**Responsibility at a point in time**

- **FR-041**: The system MUST answer, for a given group and instant, which moderator was the responsible
  primary owner then: the assignment whose effective instant is at or before it and whose expiry is
  absent or strictly after it.
- **FR-042**: When no assignment covers the instant, the answer MUST be that there was none. The current
  owner MUST NOT be substituted.
- **FR-043**: Changing an assignment today MUST NOT change the answer for any past instant.
- **FR-044**: The boundary behaviour MUST be exact: an interval's effective instant is included and its
  expiry instant is excluded, so precisely one primary owner covers any instant that is covered at all.

**Operator screens**

- **FR-045**: The control panel MUST gain a single navigation group for this domain containing a groups
  screen and a moderators screen. In the same change, the panel's existing model-roster screen MUST be
  placed under a navigation group of its own rather than left at the root.
- **FR-046**: The groups screen MUST show, per group: its identifier, kind, title, the bot's standing
  and when that was observed, whether the bot holds the ability to remove messages there, when anything
  last happened there, and whether it is measured. It MUST allow measurement to be switched, and MUST
  allow an optional plain reference to a course in the organisation's main application to be set, with
  no relational link and no validation against that system.
- **FR-047**: The moderators screen MUST allow a moderator to be added with a stable display name and
  either an observed sender identity or a not-yet-observed numeric identifier, and MUST allow a
  moderator to be marked inactive.
- **FR-048**: The moderators screen MUST include an assignments view listing every past and current
  assignment for a moderator with its group, role, interval and note, and MUST offer a single reassign
  action that performs the atomic handover of FR-037 — never two separate edits the operator must
  remember to pair.
- **FR-049**: The screens MUST distinguish, at a glance, measured groups with no primary owner and
  measured groups where the bot is not an administrator.
- **FR-050**: The panel MUST make no call to the platform, MUST initiate no model call, and MUST perform
  no schema change.
- **FR-051**: The new navigation group's reading direction and labels MUST suit the operator's language,
  and this MUST NOT alter the rest of the panel.

**Continuity and coverage**

- **FR-052**: When a group's platform identifier changes because it was promoted, the system MUST
  re-point that group's ownership assignments to the surviving identity in a single atomic act, without
  closing any interval and without opening any — a technical migration is not an ownership change.
- **FR-053**: Messages captured under a group's old and new identifiers MUST be countable as one group's
  continuous history, with none lost and none double-counted.
- **FR-054**: When the bot's standing in a measured group changes to a level that loses coverage, the
  system MUST record the change, MUST NOT switch measurement off, and MUST surface the group as a
  coverage problem.

**Retention shape**

- **FR-055**: Human-readable sender names MUST carry a marker for later removal, leaving the durable
  numeric pseudonym, the first- and last-observed times and every count intact.
- **FR-056**: A sender identity linked to a moderator MUST be excluded from name removal, because
  reports must be able to name the person responsible.
- **FR-057**: A message record's verbatim and normalised text MUST carry a marker for later removal,
  leaving its group, sender, send time, reply target, moderator flag, flags and every timing intact.
- **FR-058**: This milestone MUST remove nothing. Only the shape exists here; the removal job belongs to
  a later milestone.

**Safety, and what this milestone must not do**

- **FR-059**: The system MUST NOT recognise a question, open an item of work, match a response, compute
  a duration, categorise a violation, or call a model.
- **FR-060**: The system MUST NOT send a message, set a reaction, delete a message, remove a member or
  restrict a member on the platform. No such capability may exist in this milestone's change set.
- **FR-061**: No inbound network port may be opened, and the platform's inbound delivery mechanism MUST
  remain unconfigured and unconfigurable from this milestone.
- **FR-062**: All platform communication MUST remain confined to the domain's platform-provider area,
  and the domain boundary established two milestones ago MUST continue to hold and to be enforced by the
  quality gate.
- **FR-063**: Log records MUST carry only the correlation identifiers already established and MUST
  contain no message text. This MUST remain enforced by the quality gate.
- **FR-064**: The credential MUST remain environment-supplied only and MUST NOT be stored in the store,
  written to a log, or committed.
- **FR-065**: Every new setting MUST have a documented default, MUST appear in the environment example
  file, and MUST be rejected at startup when given a value outside its permitted range.
- **FR-066**: The full quality gate MUST pass offline, with no credential configured and no model runtime
  running, and MUST require no real platform access. Behaviour MUST be exercised against scripted
  stand-ins.
- **FR-067**: This milestone MUST make no change inside the read-only reference application.

**Schema ownership**

- **FR-068**: Every new table MUST be created by a migration, which remains the sole owner of schema
  change, and MUST consume the second of the revision identifiers reserved for this domain. The reverse
  of that migration MUST be exercised.
- **FR-069**: The invariants this milestone rests on MUST be constraints in the store, not conventions:
  uniqueness of a message within its group, uniqueness of a sender identity by platform identifier,
  uniqueness of the moderator-to-identity link in both directions, and at most one current primary owner
  per group.
- **FR-070**: Panel tests MUST run inside a transaction against the isolated test store, and MUST NOT
  reset, re-migrate or recreate any database.

### Out of Scope (deferred to named later milestones)

- Recognising that a message needs an answer, the burst window that groups a multi-message question,
  opening an item of work, matching a response to it, and first-response measurement — **TG-M3**. This
  milestone produces the messages those rules will read and applies none of them. The burst window
  remains configured-but-unconsumed.
- The live queue screen, and any first-response, median or percentile figure anywhere — **TG-M3**.
- Policy incidents, their lifecycle, moderator actions, and the enforcement signals derived from
  membership and reaction events — **TG-M4**. Those events are captured already and interpreted there;
  this milestone interprets only messages, edits and the bot's own standing.
- Any model call, the classification taxonomy, confidence, and redaction in a live path — **TG-M5**. The
  normaliser and the redactor already exist and the redactor stays unused.
- A model profile for this domain and the widening of the roles the model roster accepts — **TG-M5**.
- Alert rules, thresholds, quiet hours, the private moderators' group, and any outbound message —
  **TG-M6**.
- Every dashboard, every metric query, the overview screen, team performance, and the marker that
  renders a report incomplete where it overlaps an unobserved window — **TG-M7**. The unobserved windows
  are already recorded; nothing here displays them.
- Classification review and reprocessing — **TG-M8**.
- Scheduled digests, the automation tool's configuration, and any endpoint an external tool calls —
  **TG-M9**.
- The job that removes names and message text at the end of their retention period, and the proof that
  re-deriving every captured event reproduces identical interpreted state — **TG-M10**. Both are shaped
  for here: the removal markers exist and derivation is idempotent, which is what makes the convergence
  proof possible later.
- A relational link, an automatic mapping, or any read of the organisation's main application. The
  course reference on a group is a plain operator-entered value; automatic mapping would need a change
  inside that application and is post-v1, operator-manual work when it comes.
- Composite scoring of any moderator. Explicitly excluded from the whole first version, not merely
  deferred.
- Cross-sender conversation threading and a thread hierarchy. The thread identifier is recorded as a
  fact and used to scope nothing yet.
- Support for more than one bot credential at a time.
- A full localisation of the control panel. Only this milestone's navigation group is given the
  operator's reading direction and labels.

### Key Entities

- **Message**: One thing said in a measured group, with the platform's own send time, its sender, what
  it replies to, its thread, its text verbatim, a normalised form for later matching, coarse content
  flags, and — written once, never recomputed — whether its sender was a moderator at that moment.
  Every later measurement is arithmetic over these.
- **Sender identity**: One person the bot has observed, keyed by the platform's numeric identifier for
  them. That number is a durable pseudonym; the name beside it is personal data shaped for later
  removal. May exist as a placeholder, created by a mapping, before the person has ever been observed.
- **Moderator**: A person the operator declared, with a display name of their own that no platform
  profile rename can alter, linked to exactly one sender identity. Being a moderator is this domain's
  fact, informed by what the platform reports but never granted by it.
- **Ownership assignment**: A moderator bound to a group in a role over an interval closed at its start
  and open at its end. At most one is the current primary for a group, guaranteed by the store. The
  history is append-and-close only, because it is the only way a past attribution can be defended.
- **Group record**: Extended here from the previous milestone with the deliberate measurement decision
  and the optional plain reference to a course in the organisation's main application. Presence is
  discovered; measurement is always chosen.
- **Responsibility at an instant**: Not a stored row but the question the whole milestone exists to
  answer — which moderator owned this group at this moment — answered from the assignment history and
  therefore stable no matter what changes afterwards.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Interpreting a scripted set of captured events 3 times produces exactly 1 message record
  per distinct message on 100% of runs, with byte-identical field values across all 3 passes.
- **SC-002**: 100% of message records take their send time from the platform's own stamp; 0 take it from
  the time of capture or interpretation, verified against a fixture whose two times differ by a known
  amount.
- **SC-003**: Captured events from groups not marked measured produce 0 message records, 0 sender
  identities and 0 other interpreted state, on 100% of runs, while 100% of those events are still marked
  handled.
- **SC-004**: Across the 6 message shapes — a plain message, a reply to an uncaptured message, an
  anonymous or channel post, a service announcement, a message with media and no text, and an edited
  message — each is recorded correctly on 100% of runs, with 0 discarded and 0 attributed to an invented
  person.
- **SC-005**: An edit updates the text and edit time and changes the original send time 0 times, and the
  pre-edit text remains readable from the captured event on 100% of runs.
- **SC-006**: A group switched on after its events were captured yields, after one re-derivation run,
  100% of its in-window captured messages as records with their original send times; a second identical
  run derives 0 further records.
- **SC-007**: Re-derivation reports 3 counts — examined, derived, skipped — on 100% of runs, refuses to
  run for a not-measured group on 100% of attempts, and is invocable from 0 screens.
- **SC-008**: Captured events whose content was already removed are reported as skipped on 100% of runs,
  produce 0 empty message records, and abort the run 0 times.
- **SC-009**: A moderator mapped by a numeric identifier never yet observed succeeds on 100% of
  attempts, creating exactly 1 placeholder identity; the first observation of that person fills the
  placeholder in and creates 0 additional identities.
- **SC-010**: Re-observing a sender with a changed name advances the last-observed time on 100% of runs
  and moves the first-observed time 0 times.
- **SC-011**: A message written before its sender was mapped as a moderator has its moderator flag
  changed 0 times by that later mapping, by a later unmapping, or by a later deactivation — verified
  across all 3 events.
- **SC-012**: Attempting to open a second current primary assignment for a group is refused by the store
  on 100% of attempts, and leaves 0 partial rows.
- **SC-013**: A reassignment leaves exactly 1 current primary on 100% of runs; with a failure induced
  partway, the original owner remains current on 100% of runs and 0 successor assignments are left open.
- **SC-014**: Responsibility queried at the 4 boundary positions of an interval — before its start,
  exactly at its start, exactly at its expiry, and after its expiry — returns the correct answer on 100%
  of runs, with the start included and the expiry excluded.
- **SC-015**: For an instant covered by no assignment, the query returns no owner on 100% of runs and
  substitutes the current owner 0 times.
- **SC-016**: Reassigning ownership today changes the answer for a past instant 0 times, across at least
  3 past instants spanning 2 different owners.
- **SC-017**: Backup assignments are returned as the responsible owner 0 times while being visible on
  100% of runs.
- **SC-018**: Assignment records are deleted 0 times and closed intervals rewritten 0 times across a
  sequence of at least 3 handovers.
- **SC-019**: A group promotion re-points 100% of that group's assignments to the surviving identity
  while closing 0 intervals and opening 0 intervals, and messages either side of it are countable as 1
  group's history with 0 lost and 0 double-counted.
- **SC-020**: A bot demotion in a measured group records the new standing on 100% of runs, switches
  measurement off 0 times, and surfaces the group as a coverage problem on 100% of runs.
- **SC-021**: The control panel gains exactly 1 navigation group for this domain containing exactly 2
  screens, and leaves exactly 0 screens orphaned at the panel root.
- **SC-022**: Every panel action makes 0 platform calls, 0 model calls and 0 schema changes, verified by
  inspection and by a runtime check.
- **SC-023**: 100% of measured groups with no primary owner, and 100% of measured groups where the bot
  is not an administrator, are distinguishable on the groups screen without opening a record.
- **SC-024**: A backlog of at least 100 not-yet-interpreted captured records is handed to the
  interpreting process in the platform's assigned order with 100% interpreted and 0 duplicates.
- **SC-025**: 100% of name and text fields subject to retention carry a removal marker; removing a name
  or a text in a test leaves 100% of timestamps, flags and counts intact, and names linked to a moderator
  are removed 0 times. This milestone removes 0 rows and 0 field values in normal operation.
- **SC-026**: 0 questions are recognised, 0 items of work are opened, 0 durations are computed and 0
  model calls are made anywhere in the change set.
- **SC-027**: 0 outbound sends, reactions, deletions, removals or restrictions exist anywhere in the
  change set, and 0 inbound ports are opened — both verified by inspection and by a runtime check.
- **SC-028**: The full quality gate passes with 0 credentials configured, 0 model runtimes running and 0
  external network calls, on 2 out of 2 consecutive runs producing identical results.
- **SC-029**: 0 log lines contain message text, and the correlation-identifier rule remains enforced by
  the quality gate on 100% of runs.
- **SC-030**: This milestone adds exactly 1 migration revision, consuming the second identifier reserved
  for this domain, and its reverse runs cleanly on 100% of attempts.
- **SC-031**: The 4 invariants of FR-069 are each enforced by the store: a direct attempt to violate each
  one raises a constraint failure on 100% of attempts.
- **SC-032**: 100% of new settings have a documented default, appear in the environment example file, and
  cause startup to fail with a message naming the setting when given an out-of-range value.
- **SC-033**: 0 files inside the read-only reference application are created, modified or deleted, and 0
  credentials appear in version-controlled files — both verified by a repository scan.
- **SC-034**: 0 panel tests reset, re-migrate or recreate a database, and 100% of them run against a
  store whose name carries the test marker.
- **SC-035**: The operator can complete the milestone's smoke test — mark a group measured, map
  themselves as its moderator, post as a student identity and as a moderator identity, and see both
  messages with the correct moderator flag — in under 10 minutes and with 0 direct database edits.

## Assumptions

These are reasonable defaults taken where the milestone description did not specify details. Each is
drawn from the source plan, the operator runbook, the constitution, or a previous milestone.

- **Definition of done.** A milestone is done only when implementation exists, tests exist and pass,
  documentation and configuration are updated, a manual smoke test succeeds, no unrelated scope was
  added, and known limitations are written down. Taken from the source plan's §25 preamble.
- **The sender's moderator flag is a snapshot, and the resulting inconsistency is accepted
  deliberately.** The source plan calls it denormalised on purpose: it is the truth at the time of the
  message, so promoting someone next month does not rewrite last month's response times. The visible
  cost is that a transcript spanning a promotion shows the same person flagged both ways. That is the
  correct record and the wrong-looking one, and it is documented rather than smoothed over — the
  alternative is a live lookup that silently flatters every historical number in the promotion's
  direction.
- **Exactly one *current* primary owner is enforced; historical overlap is not.** Confirmed by the
  source plan's §10.5, including its explicit rejection of a range-exclusion constraint that would
  prevent all historical overlap: that stricter form is correct but needs an extension enabled at
  database creation time on an already-shipped database. A partial uniqueness constraint on the current
  primary plus an atomic reassign action buys the invariant that actually matters, at no infrastructure
  cost. Historical overlap is covered by a test instead, and this trade is recorded so a later milestone
  knows it was chosen rather than missed.
- **Ownership intervals are half-open: the effective instant is included, the expiry excluded.** The
  source plan's lookup rule states it directly. It is restated as a requirement because an off-by-one at
  this boundary produces a plausible-looking wrong answer at exactly the moment a handover happens,
  which is when someone is most likely to dispute the number.
- **Responsibility follows the primary owner only, but any moderator's message is still a moderator's
  message.** The source plan's §12 separates these: the responsible owner is the primary at the relevant
  instant, while anyone's answer ends a student's wait. The first drives attribution, the second drives
  the flag on a message. Keeping them separate here is what lets a later milestone show "covered by a
  colleague" without turning it into a penalty.
- **Retroactive derivation is one explicit operator command.** Confirmed in this session. The previous
  milestone promised that measuring a group later works retroactively within the retention window, and
  stores events for unmeasured groups precisely so that it can; but its handling step already marked
  every captured event handled, so ordinary draining will not revisit them. One command, bounded and
  reported, keeps the promise. Hiding a bulk derivation behind a screen toggle was rejected: the
  operator should choose when it runs.
- **An edit updates the message record; the immutable captured event is the archive.** Confirmed in this
  session. The source plan's §9 phrase "never overwriting the original" is already satisfied by the
  append-only captured event, and the message record's verbatim/normalised pair means raw versus
  normalised text, not pre-edit versus post-edit. The consequence — that pre-edit text is only available
  while the captured event's content survives retention — is accepted and recorded here rather than
  discovered later.
- **A moderator can be mapped before being observed, via a placeholder identity.** Confirmed in this
  session. The runbook's TG-M2 step has the operator collect numeric identifiers, which may precede
  anyone posting. A placeholder keeps one identity table and one relational link, and removes the
  ordering trap where a moderator's very first message would be flagged as a student's forever.
- **The platform's observed administrators are candidates, never a grant.** The source plan's §12
  bootstrapping note: there is no source of truth to import, so the bot's observed membership history
  proposes candidates and the operator confirms. An administrator on the platform is not automatically a
  moderator in this domain, and the two lists are allowed to differ.
- **Only three kinds of captured event are interpreted here** — a message, an edited message, and a
  change in the bot's own standing. Membership changes and reactions are captured already and are
  interpreted at TG-M4, where the actions they represent have somewhere to attach. Requesting them from
  the start was the previous milestone's decision; interpreting them is not this one's.
- **Group presence is discovered, measurement is chosen, and this milestone ships the screen for it.**
  The previous milestone left the flag defaulting to off with no screen. Providing the screen is this
  milestone's control-panel work, and it is the last piece needed before the operator can run the first
  vertical slice without touching the database.
- **The course reference is a plain operator-entered value.** The source plan's §24 establishes that the
  organisation's main application holds invite links rather than numeric group identifiers, that a bot
  cannot resolve a link to an identifier, and that no change inside that application is required for any
  milestone in this track. So the reference is manual, has no relational link, and is not validated
  against a system on another host.
- **The panel introduces the first navigation group in its history.** It currently defines none, so the
  existing model-roster screen is given a group of its own in the same change to avoid leaving it
  orphaned at the root. That one-line edit is the only modification to existing panel code, and it is
  additive.
- **The panel reads the same store directly, with its restricted role, and tests wrap each case in a
  transaction.** This is the established pattern and is not revisited: no schema change from the panel,
  and no test that resets or re-migrates a database.
- **Names are personal data, numeric identifiers are pseudonyms, and the shape is built now.** The
  source plan's §19.2 sets the retention rules and the exception for moderator-linked names. Only the
  shape belongs here; the job that acts on it is TG-M10. Building the shape later would mean a second
  migration over tables that by then hold real data.
- **The normaliser and redactor from TG-M0 are reused unchanged.** The normalised form is populated here
  because later matching needs it; the redactor stays unused until a model is called at TG-M5. Neither
  is modified, and the normaliser's output is a separate value that never replaces the verbatim text.
- **Tests are written where the risk is.** Following Principle I: derivation idempotency, the moderator
  snapshot surviving a later promotion, the responsibility boundaries, the refusal of a second current
  primary, the atomicity of reassignment, unmeasured groups producing nothing, and assignments following
  a group promotion. No test is written for screen listing and editing behaviour, for framework wiring,
  or for migration column types.
- **No real platform access is needed to develop or verify this milestone.** All behaviour is exercised
  against scripted stand-ins, as the previous milestone established. Real platform access is needed only
  for the operator's manual smoke test.
- **Operator prerequisites are the runbook's §C row for TG-M2**: the operator's own numeric identifier
  and those of the two test accounts in the development group. The §B setup from the previous milestone —
  both bots created with privacy disabled before the first group add, the development group with its
  extra accounts, the bot promoted to administrator, the development credential in the local environment
  — must still hold. Without these the milestone is fully developable and fully testable, but not
  smoke-testable.
- **Migration numbering is linear and first-come.** This domain reserves a block of revision identifiers
  and consumes the second of them here. If an assessment milestone lands first it takes the next free
  number and whichever ships second rebases its predecessor link.
- **Nothing here decides where the live capture process runs.** That decision belongs to the pilot at
  TG-M3 and is deliberately not pre-empted. The development group carries no real students, so an
  unobserved window remains acceptable at this milestone.

## Dependencies

- **TG-M1 must be complete and merged**, as it is: the append-only captured-event record and its
  idempotency key, the durable capture position, the group records with the bot's standing and the
  measurement flag defaulting to off, the unobserved-window records, the identifier-migration linking,
  the ingestion health section, and the diagnostic command. This milestone is the first consumer of the
  captured events as *content* rather than as rows.
- **TG-M0 must remain in place**: the domain package boundary and its automated enforcement, the
  moderation settings block, the Arabic normaliser and the redactor, the correlation-identifier
  whitelist on log records, the no-message-text rule, and the credential shape in the repository secret
  scan.
- **M0 and M1 must remain in place**: the running environment, migrations as the sole owner of schema
  change, the queue and background worker, the control panel shell with its restricted database role and
  its transaction-per-test pattern, the health report and its component model, and the quality gate with
  its enforced test-store isolation.
- **The source plan** `docs/plan/telegram/telegram-moderation-intelligence.md` — §9 for which captured
  events carry what, §10.3–10.6 for the records, §11 for the deliberate absence of a conversation model,
  §12 for the ownership and attribution rules, §13.4 for edit handling, §15.4 for the normaliser, §17
  for the screens and the navigation group, §19.2 for retention, §20.2 for the identifier migration and
  the demotion failure mode, §22 for which tests are earned, §23 for the integration touchpoints, §24
  for why the course reference is manual, and §25 for this milestone's own definition.
- **The operator runbook** `docs/runbooks/tg-operator-prerequisites.md` — §C's TG-M2 row for the
  prerequisites and the smoke test, and §B from the previous milestone still holding.
- **Operator-supplied**: the numeric platform identifiers for the operator and the two test accounts in
  the development group, and a development group in which those accounts can post. Without them the
  milestone can be fully developed and fully tested, but not smoke-tested.
- **No model runtime, no network access and no credential** are required by anything in this milestone's
  automated verification, including its tests.
