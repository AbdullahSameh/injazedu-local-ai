# Feature Specification: TG-M1 — Telegram Event Ingestion

**Feature Branch**: `tg-m1/telegram-ingestion` *(operator-created; see Principle IV)*
**Spec Directory**: `specs/004-tg-m1-telegram-ingestion`
**Created**: 2026-09-09
**Status**: Draft
**Milestone**: TG-M1 (second milestone of `docs/plan/telegram/telegram-moderation-intelligence.md` §25)
**Input**: User description: "read docs/plan/telegram/telegram-moderation-intelligence.md and check the docs/runbooks/tg-operator-prerequisites.md, the start specify Milestone number 1 Telegram event ingestion"

## Overview

TG-M1 makes the Moderation Intelligence domain start listening. A silent bot, already an
administrator in a group, has everything it observes captured — **durably, exactly once, in order,
and honestly about what it missed**.

Everything the domain will ever compute is a function of what this milestone captures. Telegram
keeps an undelivered event for **at most 24 hours** and offers **no history API**: there is no
backfill, no replay from the source, no second chance. An hour of capture that silently dropped
events is not a small bug — it is a permanently missing hour that, in every later report, is
indistinguishable from an hour in which every student was answered instantly. That asymmetry is the
whole reason this milestone exists on its own, before anything interprets a single message.

Five things ship:

1. **A single, outbound-only capture process.** It asks Telegram for new events on a long-lived
   request, stores them, and confirms consumption. It opens no inbound port, needs no public
   hostname, no certificate and no tunnel. It is a *separate process from the one that interprets
   events*, so a bug in interpretation can never cost a captured fact.
2. **An append-only event record that is written once and never rewritten.** Each event carries the
   identifier Telegram assigns it; storing the same event twice is a no-op, and downstream work is
   scheduled only when a genuinely new record was written. This record is the domain's spine: every
   later milestone can be rebuilt from it, and a taxonomy change or a rule fix never needs the events
   re-fetched, because they cannot be re-fetched.
3. **Durable position, so a restart resumes rather than restarts.** The position of the last
   confirmed event survives a process restart, a machine reboot and a database outage. Stopped for
   five minutes, the process wakes and drains the backlog. It never confirms consumption of an event
   it has not stored.
4. **Explicit markers for windows it could not observe.** Downtime, an identifier jump, a second
   consumer rejected by Telegram, and — the one that cannot be undone — a silence longer than
   Telegram's retention. Each is recorded as a first-class window with a reason, so any later report
   overlapping it is rendered *"incomplete"* rather than quietly under-counting. **This is the single
   feature that makes every future number trustworthy.**
5. **Groups that appear by themselves, and an operator who can tell at a glance whether capture is
   working.** Adding the bot to a group creates its record and records the bot's standing there;
   losing administrator rights is visible rather than silent; a group promoted to a supergroup keeps
   its history instead of splitting into two. Alongside, the existing health report gains an
   ingestion section, and one diagnostic command answers "is this set up correctly" without a
   database query.

TG-M1 deliberately **interprets nothing**. No message is parsed into a typed record, no sender is
resolved, no question is recognised, no item is opened, no screen is added, no model is called. The
handoff to the interpreting worker exists and is exercised, but it only marks an event as seen. That
restraint is the point: capture correctness is provable on its own, and every interpretation bug
after it is replayable.

Two properties are non-negotiable throughout, and both are testable: **the bot never sends a message
to a student group**, and **no inbound network port is opened on the operator's machine**.

## Clarifications

### Session 2026-09-09

- Q: When the platform rejects this consumer because another consumer holds the same credential, should it retry indefinitely or eventually stand down? → A: Stand down after a bounded number of consecutive conflicts — back off with increasing delay, then stop polling entirely, record an unobserved window, surface it in the health report, and require an explicit restart. Rationale: indefinite retry makes the two consumers alternate, which loses events on *both* sides while each looks healthy; a bounded stand-down converts silent mutual loss into one loud, visible failure.
- Q: What is the minimum silence that records an unobserved window? → A: 5 minutes (configurable). It matches the interval the operator runbook's own TG-M1 smoke test uses to stop and restart the capture process, so a deliberate interruption registers while ordinary poll cycles and quick redeploys do not.
- Q: What happens when the bot's own identity cannot be resolved from the platform at startup? → A: Stay running and retry with increasing delay, indefinitely. Capture does not start and nothing is stored (identity is half the idempotency key), the health report names the state and its reason — distinguishing an unreachable platform from a rejected credential and both from no credential configured — readiness is unaffected, and capture begins unattended once resolution succeeds. Never fall back to a cached identity while resolution is failing.
- Q: What event volume should the design assume, and how many events may one poll claim? → A: A single development group at this milestone; a few dozen groups and around five moderators at full rollout, in the low hundreds of events per day. One poll claims at most 100 events by default, configurable — a quiet weekend's backlog drains in a handful of polls, while a mid-batch failure re-does little work.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Every event the bot receives is captured exactly once (Priority: P1)

The bot sits silently in a group as an administrator. A student posts, a moderator replies, someone
reacts, someone is removed. Each of those becomes one stored record — complete, verbatim, with the
time the platform assigned it — and stays stored. If the platform delivers the same event twice,
there is still exactly one record and exactly one unit of downstream work. If two events arrive out
of order, both are stored and their true order is recoverable from what the platform stamped on
them, not from the order they happened to arrive.

**Why this priority**: This is the milestone. Everything the domain will ever report is a function
of this record, and Telegram will not hand these events over a second time. Duplicates would inflate
every count; a dropped event silently deflates one. On its own this story delivers a permanent,
replayable record of what happened in the monitored groups — which is already more than exists
today.

**Independent Test**: Drive the capture process against a scripted stand-in for the platform that
returns a known batch, then returns the same batch again, then returns a batch whose members are
shuffled. Confirm one record per distinct event, one unit of downstream work per newly stored record,
the stored content identical to what was delivered, and the true order recoverable. No real platform
credential and no real network access are involved.

**Acceptance Scenarios**:

1. **Given** the capture process is running and the platform delivers a batch of new events, **When**
   the batch is processed, **Then** one record is stored per event, each holding the complete event
   exactly as delivered, and one unit of downstream work is scheduled per stored record.
2. **Given** an event that has already been stored, **When** the platform delivers it again, **Then**
   no second record is created, no second unit of downstream work is scheduled, and the process
   continues without error.
3. **Given** a batch whose events arrive in an order different from their assigned identifiers,
   **When** the batch is processed, **Then** all are stored and their assigned identifiers still
   place them in their true order.
4. **Given** an event of a kind this domain does not act on, **When** it is delivered, **Then** it is
   still stored verbatim and classified as an unrecognised kind rather than discarded.
5. **Given** an event that is not associated with any group, **When** it is delivered, **Then** it is
   stored with no group association rather than rejected.
6. **Given** a stored event record, **When** anything in the system later touches it, **Then** the
   only part that may change is the marker recording that it has been handled — the captured content,
   its identifier and its timestamps are never rewritten.

---

### User Story 2 - A restart resumes; it does not restart, and it does not lose (Priority: P2)

The operator stops the capture process for five minutes to change a setting, or closes the laptop
lid overnight, or the database briefly goes away. On resume, capture continues from exactly where it
left off: the backlog the platform held drains, nothing is re-processed as new, and nothing that the
platform still held is missed. If the store is unavailable at the moment events arrive, the process
does not confirm consumption of them — it retries, and the platform delivers them again.

**Why this priority**: Downtime is the normal case, not the exception, on a laptop. The property
that makes downtime survivable is that consumption is confirmed *only after* durable storage — get
that backwards and a five-minute restart quietly costs five minutes of events. It is second only to
capture itself, and is independently demonstrable in a smoke test the operator can run in five
minutes.

**Independent Test**: Run capture against the stand-in platform, stop it mid-stream, restart it, and
confirm the position resumed is the one after the last stored event. Separately, make storage fail
for one batch and confirm the position does not advance, that the batch is retried, and that when the
same events are delivered again they are stored exactly once.

**Acceptance Scenarios**:

1. **Given** events have been stored up to a known position, **When** the process restarts, **Then**
   it asks the platform only for events after that position, and previously stored events are neither
   re-delivered as new nor duplicated.
2. **Given** the process has been stopped for a period shorter than the platform's retention window,
   **When** it restarts, **Then** the events the platform held are delivered and stored, and the
   backlog drains without operator action.
3. **Given** the store is unavailable when a batch arrives, **When** the process attempts to store it,
   **Then** the confirmed position does not advance, the failure is retried, and no event is lost.
4. **Given** a batch in which some events store successfully and one fails, **When** the batch is
   processed, **Then** the confirmed position advances no further than the last event stored
   successfully.
5. **Given** the process that interprets events is stopped while capture keeps running, **When** it
   is later started, **Then** the accumulated unhandled records are handed to it in their true order
   and none is skipped.
6. **Given** the process restarts, **When** it resumes, **Then** it subscribes to exactly the same
   set of event kinds as before, including the kinds the platform does not deliver unless explicitly
   requested.

---

### User Story 3 - A window that was not observed is marked as not observed (Priority: P3)

Capture stopped over a weekend. In the reports that come later, that weekend must not read as "every
student was answered immediately" — it must read as "this window is incomplete". Every cause of an
unobserved window is recorded with its reason: the process was down, the platform's identifiers
jumped past what was received, a second consumer was rejected, or — the one that can never be
repaired — the silence exceeded the platform's retention and those events are gone forever.

**Why this priority**: This is what separates an honest measurement system from a misleading one.
The plan is explicit that a gap looks identical to good performance, and that the difference is
permanently unrecoverable. Recording the window costs almost nothing here and is impossible to
reconstruct later. It ranks below capture and resumption only because it describes their failures.

**Independent Test**: Simulate each cause against the stand-in platform — a stop-and-restart, a jump
in assigned identifiers, a rejection of a second consumer, and a silence longer than the retention
window — and confirm each produces exactly one window record with the correct reason, correct start
and end, and that a silence beyond retention is marked permanently unrecoverable.

**Acceptance Scenarios**:

1. **Given** capture was stopped for longer than a configured minimum, **When** it resumes, **Then**
   one unobserved-window record is created covering the silence, with the reason recorded as downtime.
2. **Given** the identifier of the next delivered event is higher than the one expected to follow the
   last stored event, **When** it is stored, **Then** an unobserved-window record is created with the
   reason recorded as an identifier jump, and capture continues from the delivered event rather than
   stalling.
3. **Given** the platform rejects this consumer because another consumer holds the same credential,
   **When** the rejection is received, **Then** it is recorded, this consumer backs off rather than
   competing, and the event is visible to the operator without reading raw output.
3a. **Given** the rejection repeats for the configured number of consecutive attempts, **When** that
   count is reached, **Then** this consumer stops polling altogether, records an unobserved window
   for the period, reports itself as stood down in the health report, and does not resume until it is
   explicitly restarted.
3b. **Given** a single rejection followed by a successful poll, **When** the poll succeeds, **Then**
   the consecutive-rejection count resets and the consumer keeps running.
4. **Given** the silence exceeded the platform's retention window, **When** capture resumes, **Then**
   the window record is marked permanently unrecoverable, and this is distinguishable from an
   ordinary drained backlog.
5. **Given** a brief pause shorter than the configured minimum, **When** capture resumes, **Then** no
   window record is created — ordinary poll cycles do not generate noise.
6. **Given** any unobserved window exists, **When** the health report is read, **Then** the count of
   open windows is present in it.
7. **Given** an unobserved-window record, **When** it is inspected, **Then** its start, its end, its
   reason and when it was detected are all present, and it is never silently deleted or merged.

---

### User Story 4 - Groups appear by themselves, and losing coverage is visible (Priority: P4)

The operator adds the bot to a group. The group appears in the system on its own, with its title and
the bot's standing in it — no identifier copied by hand, no configuration file edited. If the bot is
later demoted, removed, or the group is promoted to a supergroup and changes identity, the system
follows that rather than quietly capturing less. A group is *not* measured until it is deliberately
opted in; until then its events are still captured, so opting in later works retroactively within the
retention window.

**Why this priority**: The runbook's TG-M1 step is "add the bot, post a message, see the row", and
the plan's most dangerous silent failure is a bot that lost its administrator rights — after which
several event kinds simply stop arriving with no error anywhere. Making that visible costs one field.
Opt-in defaulting to off is what keeps the bot's presence in a group from being mistaken for consent
to measure it.

**Independent Test**: Feed the stand-in platform the events that fire when a bot is added, promoted,
demoted and removed, and confirm the group record is created and its standing updated each time. Feed
a supergroup promotion and confirm the old and new identities are linked in both directions with the
history preserved and not duplicated.

**Acceptance Scenarios**:

1. **Given** the bot is added to a group, **When** that event is captured, **Then** a group record
   exists with the group's identifier, kind and title, the bot's standing, and the time that standing
   was observed.
2. **Given** a group record exists, **When** the bot's standing in it changes, **Then** the record is
   updated with the new standing and the time of the change, and the previous standing is not
   presented as current.
3. **Given** a group the bot is already in but was never explicitly added to during capture, **When**
   any event from that group is captured, **Then** a group record exists for it, with its standing
   recorded as unknown rather than guessed.
4. **Given** a group is promoted and its identifier changes, **When** that is captured, **Then** the
   old and new records are linked in both directions, and no event is lost or double-counted across
   the change.
5. **Given** a newly discovered group, **When** its record is created, **Then** it is **not** marked
   as measured, and it can only become measured by a deliberate act.
6. **Given** a group that is not marked as measured, **When** its events arrive, **Then** they are
   still captured and stored, and no interpreted state is produced for them.
7. **Given** the bot's ability to remove messages in a group, **When** its standing is recorded,
   **Then** whether it holds that ability is recorded too — as an observation, never as an action
   this milestone takes.

---

### User Story 5 - The operator can tell whether capture is healthy without a database query (Priority: P5)

The operator opens the health report and sees, in one place: when the last event arrived, whether
polling is succeeding, how much work is waiting to be interpreted, how many groups are measured,
which have gone quiet, how many unobserved windows are open, and in which groups the bot is not an
administrator. Separately, one diagnostic command answers the setup questions before anything is
running: is a credential present, does the platform recognise it, is the alternative delivery
mechanism definitely not configured, are the right event kinds subscribed to, and is the bot an
administrator where it needs to be.

**Why this priority**: The failures this milestone must survive — a lost administrator right, a
stalled poll, a growing backlog — are all silent by nature. This is the cheapest possible way to make
them loud, and it reuses the report that already exists rather than adding a monitoring stack. It is
below the capture stories because it observes them rather than producing anything.

**Independent Test**: Assemble the health section from known stored state and confirm every field is
present and correct, including when nothing has ever been captured. Run the diagnostic command
against the stand-in platform in each of its failure shapes — no credential, unrecognised credential,
alternative delivery configured, wrong subscription set, bot not an administrator — and confirm each
is reported distinctly.

**Acceptance Scenarios**:

1. **Given** capture is running normally, **When** the health report is requested, **Then** it
   contains an ingestion section reporting at least: the time of the most recent captured event, the
   time since the last poll, the amount of uninterpreted work waiting, the count of consecutive
   failures, the number of measured groups, the number that have been silent beyond a threshold, the
   number of open unobserved windows, and the measured groups in which the bot is not an
   administrator.
2. **Given** no credential is configured, **When** the health report is requested, **Then** the
   ingestion section is present, reports that capture is not running, and **readiness is unaffected**
   — this component is informational, exactly like the model runtime component.
2a. **Given** a credential is configured but the bot's identity cannot be resolved, **When** the
   health report is requested, **Then** it reports the identity as unresolved with the reason,
   distinguishes an unreachable platform from a rejected credential, distinguishes both from having no
   credential configured, and readiness is still unaffected.
3. **Given** capture has been failing repeatedly, **When** the health report is requested, **Then**
   the failure count and the time since the last success reflect it.
4. **Given** the diagnostic command is run with no credential configured, **When** it completes,
   **Then** it says so plainly and does not fail as though something were broken.
5. **Given** the diagnostic command is run with a credential configured, **When** it completes,
   **Then** it reports whether the platform recognises the credential, whether the alternative
   delivery mechanism is configured (which must be *not* configured), whether the subscribed event
   kinds match what is intended, and the bot's standing in each known group.
6. **Given** any log line written by capture, **When** it is inspected, **Then** it carries the
   identifiers needed to follow a single event through the system and **contains no message text**.

---

### User Story 6 - The bot stays silent, and the machine stays closed (Priority: P6)

Throughout this milestone the bot is an observer. It never posts in a student group, never reacts,
never removes anything, never restricts anyone. Nothing on the operator's machine begins listening
for connections from the internet: capture works by the machine asking outward, never by the world
reaching in.

**Why this priority**: These are guarantees the whole design rests on — the plan's outbound-only
architecture and the promise that students never see the tool that measures their moderators.
Breaking either is not a bug to be found in testing; it is a visible incident in a real group or an
exposure of a home machine. It is last only because it is a constraint on the five stories above
rather than a capability of its own, and every one of them must satisfy it.

**Independent Test**: Inspect the change set for any outbound send, reaction, removal or restriction
call, and confirm none exists. Confirm the capture process declares no inbound port and that the
alternative inbound delivery mechanism is neither configured nor configurable from this milestone.
Run the full quality gate offline with no credential set and confirm it passes.

**Acceptance Scenarios**:

1. **Given** the entire milestone's change set, **When** it is inspected for calls that would send a
   message, set a reaction, delete a message, remove a member or restrict a member, **Then** none
   exists.
2. **Given** the capture process is running, **When** the machine's listening ports are inspected,
   **Then** it has opened none.
3. **Given** the system is started, **When** the platform's inbound delivery mechanism is queried,
   **Then** it is not configured, and this milestone provides no way to configure it.
4. **Given** no credential is configured, **When** the system starts, **Then** it starts normally,
   capture does not run, readiness is unaffected, and the full quality gate passes with no model
   runtime running and no network access.
5. **Given** a second capture process is started against the same credential on the same machine,
   **When** both attempt to run, **Then** at most one is permitted to poll and the other stands down
   rather than competing.

---

### Edge Cases

- **Two consumers, one credential.** The platform permits exactly one. A second consumer causes both
  to lose events, and the symptom is intermittent rather than obvious. Local mutual exclusion must
  prevent it within one machine; across machines the platform's rejection must be handled without a
  crash loop, and — because retrying indefinitely means the two alternate and *both* keep losing
  events while each looks healthy — the rejected consumer must eventually stand down rather than
  compete forever.
- **The platform asks the caller to slow down.** A rate-limit response carries the wait it expects;
  it must be honoured rather than retried immediately, and honoured in one place rather than at each
  call site.
- **The store fails halfway through a batch.** The confirmed position must not run ahead of what is
  actually stored, in any interleaving — this is the one failure mode that silently loses events
  while appearing healthy.
- **An event whose identifier is lower than one already stored.** Late or replayed delivery must be a
  no-op, never a rewrite and never a backwards move of the confirmed position.
- **A very long silence, then a jump.** After days of quiet, the next identifier can be far higher
  than expected. That is normal platform behaviour, not corruption, and must produce a window record
  without stalling capture.
- **Never captured anything at all.** On a brand-new installation the health section and the
  diagnostic command must render sensibly with no stored events, no groups and no position.
- **A credential that is present but malformed or revoked.** Capture must report a clear, repeated
  failure and back off; it must not crash the process that serves the health report, and it must not
  be mistaken for "no credential configured".
- **The machine boots before its network is available.** Identity cannot be resolved, so nothing can
  be stored — but the process must stay up and recover on its own when connectivity returns, without
  an operator restart. This is the ordinary case on a laptop, not an exception.
- **The credential is swapped for a different bot's.** The identity resolved from the platform, not
  any previously stored one, decides what new events are scoped to; capture must not proceed on a
  stale cached identity while resolution is failing.
- **A group promoted to a supergroup mid-conversation.** Events arrive under the old identity, then
  under the new one. Both must be captured, linked, and countable as one group's history.
- **The bot is demoted without being removed.** Several event kinds stop arriving with no error
  anywhere. The standing change is the only signal, and it must be recorded and surfaced.
- **An event far larger than expected, or containing content this domain does not model.** It is
  stored verbatim regardless; the capture layer does not validate business shape.
- **Timekeeping.** The platform's own timestamp on an event is authoritative for ordering and
  measurement; the machine's clock is used only to record when capture happened. A clock skew must not
  reorder events.
- **An event from a group that is not measured.** It is captured and stored — capture is cheap and
  opting a group in later must work retroactively — but produces nothing interpreted.
- **The interpreting process is far behind.** A growing backlog must be visible as a number in the
  health report, and draining it must not re-capture or duplicate anything.
- **A backlog large enough that draining it races the retention window.** Bounded batches must not
  drain so slowly that events still held by the platform expire mid-drain — that would convert a
  recoverable outage into permanent loss, which is the one outcome this milestone exists to prevent.
- **Retention arrives before interpretation.** Captured content is subject to the domain's retention
  period. The record must be shaped so content can later be removed while the event's existence,
  kind and timing survive — even though the removal itself is a later milestone.

## Requirements *(mandatory)*

### Functional Requirements

**Capture: a single outbound consumer**

- **FR-001**: The system MUST capture platform events by asking the platform outward on a long-lived
  request. It MUST NOT open any inbound network port, require a public hostname, a certificate or a
  tunnel, and MUST NOT configure the platform's inbound delivery mechanism.
- **FR-002**: Capture MUST run as its own process, separate from the process that interprets events
  and separate from the process that serves requests, so that a failure in either cannot cost a
  captured event.
- **FR-003**: The system MUST ensure at most one capture consumer runs against one credential on one
  machine, by a local mutual-exclusion mechanism that holds a lock and never holds a fact.
- **FR-004**: When the platform rejects the consumer because another consumer holds the same
  credential, the system MUST record the rejection and back off with increasing delay rather than
  competing in a tight loop.
- **FR-004a**: After a bounded number of consecutive such rejections — configurable, with a documented
  default — the system MUST **stop polling entirely** rather than continue retrying. On standing down
  it MUST record an unobserved window for the period, report the stood-down state in the health
  report, and require an explicit restart to resume. Indefinite retry is prohibited: two consumers
  that alternate lose events on both sides while each appears healthy.
- **FR-004b**: A successful poll MUST reset the consecutive-rejection count, so that a single
  transient conflict during a deliberate handover does not accumulate toward standing down.
- **FR-005**: When the platform signals a rate limit and states how long to wait, the system MUST
  honour that wait. All retry, back-off and rate-limit handling for platform calls MUST live in the
  single area that owns platform communication, and MUST NOT be re-implemented elsewhere.
- **FR-005a**: A single poll MUST claim at most a configured number of events — default **100** — so
  that each store-and-confirm cycle stays small and a failure mid-batch re-does a bounded amount of
  work. The ceiling MUST be configurable with a documented default.
- **FR-005b**: A backlog accumulated during a silence MUST drain by repeated bounded polls, and MUST
  do so fast enough that the drain itself cannot push events past the platform's retention window and
  turn a recoverable backlog into permanent loss.
- **FR-006**: The system MUST subscribe explicitly to the event kinds this domain needs, including the
  kinds the platform does not deliver unless explicitly requested. The subscribed set MUST be
  configuration, MUST be recorded alongside the capture position, and MUST be re-asserted on every
  restart.
- **FR-007**: Capture MUST NOT start when no credential is configured. In that state the system MUST
  start normally, readiness MUST be unaffected, and the full quality gate MUST pass with no model
  runtime running and no network access.
- **FR-007a**: The bot's own identity MUST be resolved from the platform before any event is stored,
  because it is part of the key that makes storage idempotent. Until it is resolved, no event may be
  stored and the confirmed position MUST NOT advance.
- **FR-007b**: When identity cannot be resolved — the platform is unreachable, or the credential is
  rejected — the system MUST stay running, MUST NOT start capture, MUST retry with increasing delay
  indefinitely, and MUST recover unattended once resolution succeeds. It MUST NOT fail startup, exit,
  or affect readiness, so that a machine booting before its network is available needs no
  intervention.
- **FR-007c**: An unresolved identity MUST be reported in the health report as its own state, with the
  reason, and MUST be distinguishable from the supported state of having no credential configured. A
  rejected credential MUST be distinguishable from an unreachable platform.
- **FR-007d**: The system MUST NOT proceed on a previously cached identity while resolution is
  failing, so that events can never be stored under an identity that no longer belongs to the
  configured credential.

**The event record**

- **FR-008**: The system MUST store every delivered event as a record holding the complete event
  exactly as delivered, the identifier the platform assigned it, the identity of the bot that received
  it, its kind, the associated group where one exists, and the time it was stored.
- **FR-009**: Event records MUST be append-only. After creation, the only fields that may change are
  the marker recording that the record has been handled, the reason a handling attempt failed, and the
  marker recording that its content has been removed by retention. Captured content, identifiers and
  timestamps MUST never be rewritten.
- **FR-010**: Storing an event the system already holds MUST be a no-op: no second record, no error,
  no interruption to capture. The pair of bot identity and platform-assigned identifier MUST be the
  key that guarantees this.
- **FR-011**: Downstream interpretation MUST be scheduled only when a record was genuinely newly
  stored, so that a redelivered event never produces a second unit of work.
- **FR-012**: An event of a kind this domain does not act on MUST still be stored, classified as an
  unrecognised kind. An event with no associated group MUST still be stored, with no group
  association.
- **FR-013**: The platform's own timestamp on an event MUST be the authoritative time for ordering and
  for any later measurement. The time the system stored an event MUST be recorded separately and MUST
  NOT be used in its place.
- **FR-014**: The event record MUST be shaped so that its captured content can later be removed
  independently, leaving the event's existence, identifier, kind and timestamps intact. The removal
  job itself is out of scope here.

**Position, ordering and recovery**

- **FR-015**: The system MUST keep a durable record, per bot, of the position of the last confirmed
  event, together with the time of the last poll, the time of the last success, and the count of
  consecutive failures.
- **FR-016**: The system MUST confirm consumption of an event to the platform **only after** that
  event is durably stored. The confirmed position MUST never advance past the last successfully stored
  event, under any interleaving or partial failure.
- **FR-017**: On restart the system MUST resume from the stored position, MUST request only events
  after it, and MUST NOT re-process previously stored events as new.
- **FR-018**: When the store is unavailable, the system MUST NOT advance the confirmed position; it
  MUST retry so that the platform redelivers.
- **FR-019**: The confirmed position MUST never move backwards.
- **FR-020**: The system MUST provide a way to hand every not-yet-interpreted stored record to the
  interpreting process in the order the platform assigned, so that a backlog accumulated while that
  process was stopped is drained without loss or duplication.

**Unobserved windows**

- **FR-021**: The system MUST record an unobserved window whenever it could not have received events,
  with its start, its end, the reason, and when it was detected. Each MUST be durable and MUST NOT be
  silently removed or merged.
- **FR-022**: The recorded reasons MUST distinguish at least: the capture process was not running; the
  platform's assigned identifiers jumped past what was received; a competing consumer was rejected;
  and the silence exceeded the platform's retention window.
- **FR-023**: A silence longer than the platform's retention window MUST be marked as permanently
  unrecoverable, distinguishably from a backlog that drained successfully.
- **FR-024**: An identifier jump MUST NOT stall capture: the system MUST record the window and
  continue from the event it actually received.
- **FR-025**: A silence shorter than a configured minimum MUST NOT create a window record, so ordinary
  poll cycles produce no noise. That minimum MUST be configurable, with a documented default of
  **5 minutes** — the interval at which the operator's own smoke test stops and restarts the capture
  process, and therefore the boundary between routine operation and a deliberate interruption.

**Group discovery and coverage**

- **FR-026**: The system MUST create a group record on first observation of a group, holding its
  identifier, kind, title, the bot's standing in it, and when that standing was observed.
- **FR-027**: The system MUST update a group's recorded standing when the bot is added, promoted,
  demoted or removed, and MUST record whether the bot holds the ability to remove messages there — as
  an observation only.
- **FR-028**: A group observed only through ordinary events, without an explicit standing change, MUST
  still get a record, with its standing recorded as unknown rather than assumed.
- **FR-029**: When a group's identifier changes because it was promoted, the system MUST link the old
  and new records in both directions and MUST preserve the continuity of that group's captured
  history, without duplicating or losing events across the change.
- **FR-030**: A newly discovered group MUST NOT be marked as measured. Being measured MUST require a
  deliberate act, and this milestone provides no screen for it.
- **FR-031**: Events from groups that are not marked as measured MUST still be captured and stored,
  and MUST produce no interpreted state.

**Handoff to interpretation**

- **FR-032**: The interpreting step introduced here MUST do nothing but mark a record as handled, and
  record a reason when handling fails. It MUST NOT derive messages, senders, items, incidents or any
  other interpreted state.
- **FR-033**: Handling MUST be safe to repeat: handling the same record twice MUST leave the same
  result.

**Observability**

- **FR-034**: The health report MUST gain an ingestion section reporting at least: the time of the
  most recent captured event, the time since the last poll, the amount of uninterpreted work waiting,
  the count of consecutive failures, the number of measured groups, the number silent beyond a
  threshold, the number of open unobserved windows, and the measured groups in which the bot is not an
  administrator.
- **FR-035**: The ingestion section MUST be informational and MUST NOT affect readiness, so that a
  deliberately stopped bot never makes the system look unready.
- **FR-036**: The system MUST provide one diagnostic command reporting: whether a credential is
  present; whether the platform recognises it; that the platform's inbound delivery mechanism is
  **not** configured; the subscribed event kinds against those intended; and the bot's standing in
  each known group. With no credential it MUST say so plainly rather than fail.
- **FR-037**: Log records written by capture MUST carry the correlation identifiers established by the
  previous milestone, and MUST contain no message text. This MUST remain enforced by the quality gate.

**Safety, and what this milestone must not do**

- **FR-038**: The system MUST NOT send a message, set a reaction, delete a message, remove a member or
  restrict a member on the platform. No such capability may exist in this milestone's change set.
- **FR-039**: The credential MUST be supplied through the environment only, MUST NOT be stored in the
  database, written to a log, or committed, and MUST remain covered by the repository secret scan.
- **FR-040**: All platform communication MUST remain confined to the domain's platform-provider area,
  and the domain boundary established by the previous milestone MUST continue to hold and to be
  enforced by the quality gate.
- **FR-041**: Every new setting MUST have a documented default, MUST appear in the environment example
  file, and MUST be rejected at startup when given a value outside its permitted range.
- **FR-042**: The full quality gate MUST pass offline, with no credential configured and no model
  runtime running, and MUST require no real platform access. Tests MUST exercise capture against a
  scripted stand-in for the platform.
- **FR-043**: This milestone MUST make no change inside the read-only reference application and MUST
  add no user-facing screen.

**Schema ownership**

- **FR-044**: Every new table MUST be created by a migration, which remains the sole owner of schema
  change, and MUST consume the first of the revision identifiers reserved for this domain. The reverse
  of that migration MUST be exercised.
- **FR-045**: Idempotency MUST be a property the database enforces — through a uniqueness constraint
  on the pair of bot identity and platform-assigned identifier — rather than a rule the application
  is trusted to follow.

### Out of Scope (deferred to named later milestones)

- Turning captured events into typed message, sender and group-member records; resolving who is a
  moderator; populating normalised text — **TG-M2**. This milestone's interpreting step only marks a
  record as handled.
- The screens for marking a group as measured, mapping moderators, and viewing groups — **TG-M2**. In
  this milestone the measured flag exists and defaults to off; changing it is a direct database act.
- Time-versioned moderator ownership of groups — **TG-M2**.
- Recognising a question, opening an attention item, the burst window, and first-response measurement
  — **TG-M3**. The burst window remains configured-but-unconsumed.
- Policy incidents, moderator actions and the enforcement signals derived from membership changes —
  **TG-M4**. Those events are *captured* here and *interpreted* there.
- Any model call, the taxonomy, redaction in a live path — **TG-M5**. Redaction already exists from
  TG-M0 and remains unused until then.
- Alert rules, thresholds, quiet hours, the private moderators' group, and any outbound message —
  **TG-M6**. Nothing in this milestone may send anything.
- Dashboards, metric queries and the incomplete-window marker's appearance in reports — **TG-M7**. The
  windows are recorded here so that they can be shown there.
- Classification review and reprocessing — **TG-M8**.
- Scheduled digests and any automation-tool workflow — **TG-M9**.
- The job that removes captured content at the end of its retention period, and the proof that
  replaying every captured event reproduces identical interpreted state — **TG-M10**. The record is
  shaped for both here.
- An inbound-delivery adapter for the platform. The architecture permits one behind the same
  interface, but no tunnel exists and none is built.
- Support for more than one bot credential at a time. The record is keyed by bot identity so a second
  bot is possible later; running two is not in scope.
- Linking groups to course records, and any change inside the read-only reference application —
  post-v1, and operator-manual when it comes.

### Key Entities

- **Captured event**: One thing the platform reported, stored verbatim with the identifier the
  platform assigned it, the bot that received it, its kind, its group where it has one, and when it
  was stored. Append-only. Everything this domain will ever report is a function of these records, and
  the platform will not supply them a second time.
- **Capture position**: Per bot, the last event whose consumption has been confirmed to the platform,
  with the health of recent polling and the set of event kinds subscribed to. Durable, and never ahead
  of what is actually stored.
- **Unobserved window**: A period during which events could have occurred but could not have been
  received, with its reason and whether it is permanently unrecoverable. The reason reports can be
  honest instead of confidently wrong.
- **Group record**: A conversation the bot has observed — its identity, its title, the bot's standing
  in it, whether it is deliberately measured, and its link to a prior or successor identity after a
  promotion. Presence is discovered automatically; being measured is always a deliberate act.
- **Bot identity**: The platform's own numeric identity for the credential in use. Every captured
  event and every position is scoped to it, so a second bot could be added later without
  reinterpreting anything already stored.
- **Event kind**: Which of the subscribed categories an event belongs to, including an explicit
  category for kinds this domain does not act on — recorded so that nothing is discarded for being
  unrecognised.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of events delivered while capture is running are stored, and each is stored exactly
  once — verified by driving a scripted stand-in through a run that includes redelivery, shuffled
  arrival order and repeated batches.
- **SC-002**: Delivering an already-stored event produces 0 additional records and 0 additional units
  of downstream work, on 100% of attempts.
- **SC-003**: After a restart, 0 previously stored events are re-processed as new and 0 events held by
  the platform are missed, across 3 restart shapes: a clean stop, an abrupt stop mid-batch, and a stop
  with the store unavailable.
- **SC-004**: In every simulated partial-failure interleaving, the confirmed position is at or behind
  the last successfully stored event on 100% of runs, and never ahead of it.
- **SC-005**: A stop of at least 5 minutes followed by a restart drains the platform's backlog with 0
  operator actions beyond restarting, and records exactly 1 unobserved window for the silence.
- **SC-006**: Each of the 4 unobserved-window reasons produces exactly 1 window record with the
  correct reason, start and end, on 100% of simulated runs; a silence beyond the platform's retention
  is additionally marked permanently unrecoverable on 100% of runs.
- **SC-007**: A pause shorter than the configured minimum produces 0 window records, so a normal hour
  of polling produces 0 of them.
- **SC-008**: An identifier jump produces 1 window record and 0 stalled or skipped subsequent events.
- **SC-009**: Adding the bot to a group produces its record within 1 poll cycle, and the operator can
  see the raw stored event for a message posted in that group within seconds of posting it, with 0
  identifiers copied by hand.
- **SC-010**: Across the 4 standing changes — added, promoted, demoted, removed — the recorded standing
  matches the observed one on 100% of cases.
- **SC-011**: A group promotion links the old and new records in both directions on 100% of runs, with
  0 events lost and 0 double-counted across the change.
- **SC-012**: 100% of newly discovered groups are recorded as not measured, and events from
  not-measured groups are stored on 100% of occasions while producing 0 interpreted records.
- **SC-013**: The health report's ingestion section contains 100% of its 8 required fields, in both a
  populated system and a system that has never captured anything, and readiness is identical with and
  without a credential configured on 100% of runs.
- **SC-014**: The diagnostic command distinguishes 5 setup states — no credential, unrecognised
  credential, inbound delivery configured, subscription set mismatched, bot not an administrator —
  reporting each distinctly on 100% of runs, and reports the inbound delivery mechanism as not
  configured on 100% of correctly configured runs.
- **SC-015**: 0 outbound sends, reactions, deletions, removals or restrictions exist anywhere in the
  change set, and 0 inbound ports are opened by the capture process — both verified by inspection and
  by a runtime check.
- **SC-016**: The full quality gate passes with 0 credentials configured, 0 model runtimes running and
  0 external network calls, on 2 out of 2 consecutive runs producing identical results.
- **SC-017**: 0 log lines written by capture contain message text, and 100% of capture log lines
  carry at least one correlation identifier — the first enforced by the quality gate.
- **SC-018**: 0 credentials appear in version-controlled files, 0 credentials are written to the
  database, and 0 files inside the read-only reference application are created, modified or deleted —
  all verified by a repository scan.
- **SC-019**: This milestone adds exactly 1 migration revision, consuming the first identifier reserved
  for this domain, and its reverse runs cleanly on 100% of attempts. It adds 0 screens and 0 model
  calls.
- **SC-020**: 100% of new settings have a documented default, appear in the environment example file,
  and cause startup to fail with a message naming the setting when given an out-of-range value.
- **SC-021**: Handing a backlog of at least 100 uninterpreted stored records to the interpreting
  process results in 100% marked handled, in the platform's assigned order, with 0 duplicates.
- **SC-022**: A consumer rejected for the configured number of consecutive attempts stops polling on
  100% of runs, records exactly 1 unobserved window, and reports itself stood down in the health
  report; a single rejection followed by a success leaves it running on 100% of runs.
- **SC-023**: With the platform unreachable at startup, the system stays running on 100% of runs, 0
  events are stored, the confirmed position advances 0 times, readiness is unchanged, and capture
  begins unattended within 1 retry interval of connectivity returning. The 3 states — no credential,
  unreachable platform, rejected credential — are reported distinctly on 100% of runs.
- **SC-024**: No single poll claims more than the configured ceiling of 100 events on 100% of runs,
  and a simulated backlog of at least 1,000 events drains completely, in the platform's assigned
  order, with 0 duplicates and 0 events lost.

## Assumptions

These are reasonable defaults taken where the milestone description did not specify details. Each is
drawn from the source plan, the operator runbook, the constitution, or the previous milestone.

- **Definition of done.** A milestone is done only when implementation exists, tests exist and pass,
  documentation and configuration are updated, a manual smoke test succeeds, no unrelated scope was
  added, and known limitations are written down. Taken from the source plan's §25 preamble.
- **One credential has exactly one consumer, and this is a correctness constraint.** The platform
  enforces it: two consumers on one credential cause both to lose events. Therefore development and
  live use two separate bots, and the two credentials never coexist on one machine. Taken from the
  runbook's opening facts and §26.1.
- **Expected scale, and the batch ceiling that follows from it.** Confirmed in this session: this
  milestone runs against a single development group, and full rollout is a few dozen groups with
  around five moderators, in the low hundreds of events per day. Nothing here is a high-throughput
  problem. A single poll therefore claims at most **100** events by default — large enough that a
  whole quiet weekend's backlog drains in a handful of polls, small enough that a mid-batch failure
  re-does little work and no store-and-confirm cycle holds much open at once. Both the ceiling and the
  volume expectation are recorded so a later milestone measuring something very different knows the
  assumption it is departing from.
- **The stand-down threshold defaults to 5 consecutive rejections.** Clarified in this session: a
  rejected consumer must eventually stop rather than retry forever. The count itself has no source
  value — 5 is long enough to ride out a deliberate handover in which the outgoing consumer takes a
  few poll cycles to exit, and short enough that a genuine two-consumer collision is caught in under a
  minute. It is a setting, so it can be changed without a code change.
- **The development bot is the only one used in this milestone.** The runbook creates both bots at
  TG-M1 but only adds the live one to real groups at TG-M3. Nothing here touches a real student group.
- **Capture and interpretation are separate processes, deliberately.** The capture process stores and
  advances its position; all interpretation happens in the existing background worker. This is what
  makes interpretation replayable, and it is the source plan's §7.3 division of responsibility.
- **The platform's retention window is 24 hours and there is no history interface.** A silence longer
  than that is permanently unrecoverable. This is not a limitation to work around; it is the fact that
  determines the whole design, and it is recorded as an inherited limitation rather than mitigated.
- **The minimum silence that creates an unobserved window is 5 minutes** — proposed during
  specification and confirmed by the operator in this session's clarification. The source plan
  requires the window to be recorded but names no threshold. Below one, ordinary poll cycles and quick
  redeploys would write windows constantly and the "incomplete data" marker would stop meaning
  anything; above one, a real outage hides. Five minutes is the interval the operator runbook itself
  uses for the TG-M1 smoke test ("stop the container 5 minutes, restart, watch the backlog drain"),
  which makes it the natural boundary between routine operation and a deliberate interruption. It is a
  setting, changeable without a code change.
- **The bot's numeric identity is resolved from the platform at startup, and recorded alongside the
  capture position.** It scopes every stored event, which is what allows a second bot later. It is not
  parsed from the credential. Clarified in this session: because it is half of the idempotency key,
  nothing can be stored until it resolves — so a failure to resolve blocks capture but never startup.
  The process stays up and retries indefinitely, recovering unattended when the network returns, which
  on a laptop that boots before its Wi-Fi connects is the ordinary case. It never falls back to a
  cached identity while resolution is failing, because a swapped credential would then write events
  under an identity that is no longer its own.
- **Group records are created from any event carrying a group, not only from standing changes.** A bot
  already present in a group before capture started never produces a standing-change event, so relying
  on those alone would leave that group invisible. Its standing is recorded as unknown until observed.
- **A group is not measured until deliberately marked.** The flag defaults to off and this milestone
  ships no screen for it; the operator sets it directly, once, and the screen arrives in TG-M2. Storing
  events for unmeasured groups is intentional — it is cheap, and it makes opting a group in work
  retroactively within the retention window.
- **The whole subscription set is requested from the start**, including the kinds that require the bot
  to be an administrator and that the platform will not deliver unless explicitly named. Requesting a
  kind the bot cannot yet receive is harmless; discovering at TG-M4 that months of them were never
  requested is not.
- **The captured content is subject to the domain's retention period.** The record is shaped now so
  content can later be removed while the event's existence and timing survive. The removal job is
  TG-M10; only the shape is this milestone's concern.
- **Migration numbering is linear and first-come.** This domain reserves a block of revision
  identifiers and consumes the first of them here. If an assessment milestone lands first it takes the
  next free number and whichever ships second rebases its predecessor link. Recorded because two
  tracks could otherwise both claim the same number.
- **Tests are written where the risk is.** Following Principle I: idempotency, position durability
  under partial failure, window detection, standing changes and promotion continuity, and the shape of
  the health section. No test is written for the poll loop's sleeping, for framework behaviour, or for
  migration column types.
- **No real platform access is needed to develop or verify this milestone.** All behaviour is exercised
  against a scripted stand-in, mirroring how the model gateway's tests already inject a transport. Real
  platform access is needed only for the operator's manual smoke test.
- **Operator prerequisites are the runbook's §B, in full.** Both bots created with privacy disabled
  *before* the first group add, a development group with two additional accounts in it, the bot
  promoted to administrator there, and the development credential in the local environment. The
  runbook's §A.2 decision on granting the message-removal right is answered here, and recording the
  right is an observation — this milestone never exercises it.
- **A sleeping laptop is an unobserved window, and that is acceptable at this milestone.** The
  development group carries no real students. The decision about where the live capture process runs
  belongs to TG-M3 and is deliberately not pre-empted here.

## Dependencies

- **TG-M0 must be complete and merged**, as it is: the domain package boundary and its automated
  enforcement, the moderation settings block including the optional credential and the subscription
  set, the correlation-identifier whitelist on log records, the no-message-text rule, and the
  credential shape in the repository secret scan. This milestone is the first consumer of all of them.
- **M0 and M1 must remain in place**: the running environment, migrations as the sole owner of schema
  change, the queue and background worker, the health report and its component model, and the quality
  gate with its enforced test-database isolation.
- **The source plan** `docs/plan/telegram/telegram-moderation-intelligence.md` — §5 for the verified
  platform capabilities and limitations that this milestone must not contradict, §7.1 for the capture
  flow, §9 for the subscription set and the fact-versus-derived split, §10.1–10.3 for the records, §20
  for the failure behaviours, §21 for the health section and the diagnostic command, and §25 for this
  milestone's own definition.
- **The operator runbook** `docs/runbooks/tg-operator-prerequisites.md` — §B in full, before
  implementation can be smoke-tested, and §C's TG-M1 row for the smoke test itself.
- **Operator-supplied**: both bots created, a development group with at least two other accounts, the
  bot promoted to administrator in it, and the development credential in the local environment. Without
  these the milestone can be fully developed and fully tested, but not smoke-tested.
- **No model runtime, no network access and no credential** are required by anything in this
  milestone's automated verification, including its tests.
