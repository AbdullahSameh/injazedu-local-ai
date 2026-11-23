# Feature Specification: TG-M6 — Alerts

**Feature Branch**: not created. Git is operator-owned (constitution IV); suggested name `m6/alerts`.
**Created**: 2026-11-12
**Status**: Draft, clarified 2026-11-12 (quiet hours, student text, language)
**Input**: "read the `docs/plan/telegram/telegram-moderation-intelligence.md` and start specifying TG-M6 — Alerts"
(operator, 2026-11-12). The sources are the master plan's:
- §16, the alerting architecture;
- §10.12, alert rules and alerts;
- §25 TG-M6, with its operator decision of 2026-10-21 (one shared alert group);
- §28, open questions 6 (quiet hours) and 7 (alert language).

## Overview

Today the system watches and never speaks. A moderator learns that a question is waiting or an advert was
flagged only by opening the panel. TG-M6 makes the system tell them. The bot posts one alert into a private
Telegram group of moderators in four situations:
- a question has waited too long;
- an incident is flagged;
- an incident stays unhandled;
- a group goes quiet or the bot loses its admin rights there.

An incident alert carries buttons that resolve or close the incident with the same guarantees as a panel
act. A question alert carries a button that takes the question. The bot still never posts, reacts, deletes
or bans in a student group.

## Provenance: what this milestone changes, and what it keeps

- **The first milestone that sends anything.** TG-M1 forbade every outbound method (FR-038). Its provider
  contract (§8 item 1) already says: "TG-M6 adds sending, to the private moderators' group only".
- **Amended, each with a dated "Amended by TG-M6" note beside the superseded clause:**
  - TG-M1's provider contract §8: sending, editing the bot's own alert messages and answering button
    presses, all addressed only to the alert group;
  - TG-M2's message derivation: `callback_query` becomes interpreted (today: "stored, marked handled, not
    interpreted, TG-M6 — alert buttons");
  - TG-M4's incident lifecycle:
    - one more `confirmation` kind, ✅ Handled, as TG-M4 research §4 anticipated;
    - one more false-positive closure kind, 🚫 Not a violation;
  - TG-M3's attention rules and TG-M2.1's assignment rules: one more taking act on a question, "I'm on it".
    It takes a question and never closes it.
- **Kept unchanged:**
  - seeing is not acting;
  - a question closes only when a moderator writes in the group (D-TG-06);
  - an incident resolves only by enforcement or a confirmation;
  - the 👀 path (TG-M4.1);
  - the team and first-action rules (TG-M2.1);
  - every figure definition, the rule set, the bursts, the models and their switches;
  - every screen, except for the additions below.

## Clarifications

### Recorded before this specification (operator decision, 2026-10-21, master plan §25)

- **One shared alert group.** Every alert goes to one private Telegram group that holds every moderator and
  the bot. No alert is ever a private message to one moderator.
- **The alert group is never measured.** It is never a monitored group, and alerts from every source group
  go to it.
- **Membership of the alert group is the access control.** Everyone in it sees every group's alerts. The
  operator manages membership. Ending a team membership or deactivating a moderator in the panel does not
  remove them from the Telegram group; that is an offboarding step.
- **Content defaults to links and labels, not student text.** The final call was this milestone's.
  *Superseded 2026-11-12 (session below): alerts carry a short excerpt with contact details removed.*
- **Buttons:**
  - ✅ Handled, through the same guard and lock as a panel act;
  - 🚫 Not a violation;
  - for questions, "I'm on it", which takes a question without closing it.
- **Who may press.** A press counts only when its sender is a declared, active moderator. Anyone else's press
  is answered and records nothing.
- **Updates.** An alert message is edited when its incident ends by **any** route: enforcement, 👀, the panel
  or a button.
- **Attribution follows TG-M2.1.** The presser is the act's actor. A member of the source group's team at
  that instant takes it. Someone outside the team acts without being assigned (A4), exactly as with 👀.

### Session 2026-11-12 (operator)

- Q: Are there hours when no alert is sent, and what happens to an alert inside them? (§28 item 6) → A:
  **Quiet hours per rule.** An alert that falls inside them is recorded as suppressed and never sent, which
  is the master plan's design. The morning backlog is the Live Attention Queue and the Incidents list, not a
  burst of alerts. → FR-543.
- Q: Is any student text copied into an alert? → A: **A short excerpt, on question and incident alerts,
  with links, phones and handles removed.** This supersedes the 2026-10-21 default of links and labels only.
  → FR-531, FR-535, FR-536.
- Q: What language are alert messages in? (§28 item 7) → A: **Arabic only.** The panel link opens the
  bilingual panel. → FR-533.

## User Scenarios & Testing *(mandatory)*

### User Story 1: a question that waits too long reaches the team (P1)

The operator creates a rule, "a question waiting longer than 10 minutes", for all groups. A student asks a
question in group G at 10:00 and nobody answers. At 10:10, within one evaluation cycle, the alert group
receives **one** alert. It says:
- that a question is waiting;
- in which group, by its title;
- a short excerpt of the question, with links, phones and handles replaced by placeholders;
- when it was asked and how long it has waited;
- who it belongs to: "Team: A, B", or the assigned moderator once someone has taken it;
- two links: to the message and to the panel page.

The rule repeats every 10 minutes, at most twice. If nobody answers, it posts again at 10:20 and at 10:30,
then stops. When A answers in G at 10:14, every alert message for this question is edited to read
"Answered by A at 10:14" and no further repeat is posted.

**Why this priority**: reaching people is the point of the milestone, and it is the master plan's smoke test.
The two guarantees that matter most are proven here: one alert, never two, and nothing sent to a student
group.

**Independent test**: build US1 alone, with a rule, an unanswered item and a scripted alert group. Exactly one
alert arrives. A second cycle, a restart and a replay each add none. Nothing is sent anywhere else. The alert
is edited when the question is answered.

**Acceptance**:
1. **Given** a rule with a 2-minute threshold, **when** an item has been open for 2 minutes, **then**
   exactly one alert is posted to the alert group. This holds however many cycles, restarts or processes
   run.
2. **Given** repeats every R minutes up to N, **then** at most N further alerts are posted, each at least R
   apart, while the item stays open. None is posted after it ends.
3. **Given** the item is answered, dismissed or expires, **then** every alert for it is edited to show how it
   ended, by whom and when. No further repeat is posted.
4. **Given** the item ended before its alert could be posted, **then** nothing is posted. The alert is
   recorded as not sent because its subject had already ended.
5. **Given** G has its own rule for this trigger, **then** G's items follow that rule and not the all-groups
   rule. A disabled group rule mutes the trigger for G.
6. Nothing is ever sent to G or to any other monitored group.

---

### User Story 2: an incident alert is resolved from Telegram (P1)

The operator creates a rule, "incident flagged, severity medium or higher". An advert is flagged in G. The
alert group receives one alert. It gives:
- that an incident was flagged, with its category and severity;
- a short excerpt of the flagged message, with links, phones and handles replaced by placeholders;
- who opened it: the link rule, the model or an operator;
- when the message was posted and when it was flagged;
- the team or the assigned moderator;
- links to the message and to the panel.

It has three buttons: **✅ Handled**, **🚫 Not a violation** and **Open in the panel**.

Moderator A is active and on G's team. A removes the advert in Telegram, then taps ✅ Handled. Three things
happen:
- the incident resolves, assigned to A;
- Telegram shows A a short confirmation;
- the alert now reads "Handled by A at 10:12" and has no buttons.

A second rule, "incident unhandled for 15 minutes", alerts on any matching incident that is still open or
only acknowledged 15 minutes after it was flagged.

**Why this priority**: incidents are what the team works today. A tap in the alert group resolves an incident
without opening the panel. Telegram does not tell bots about deletions, so without the tap an incident
handled by deleting the message stays open.

**Independent test**: one flagged incident and one scripted press per case. Each case records exactly the
expected act, or none, and the incident's derived state matches.

**Acceptance**:
1. ✅ Handled pressed by a declared, active moderator resolves the incident. It goes through the same guard
   and lock as a panel resolve. The resolution's instant is the press's.
2. 🚫 Not a violation closes the incident as a false positive. It is recorded as coming from the alert.
3. The presser is the act's actor. If they are on the source group's team at that instant and the incident
   is unassigned, it becomes theirs. Someone outside the team resolves it without being assigned (TG-M2.1
   A4).
4. A press by anyone who is not a declared, active moderator records nothing and changes nothing. Telegram
   tells the presser they cannot act on alerts, and the alert is unchanged.
5. A press on an incident that has already ended, by any route, records nothing. The presser is told how it
   ended and by whom, and the alert shows that outcome.
6. When an incident resolves or closes by any route, every alert message for it is edited to show the
   outcome, the actor and the time, and its buttons are removed. The routes are a ban, expulsion or
   restriction; 👀; the panel; a button.
7. When two presses arrive almost together, exactly one act is recorded. The other presser is told it was
   already handled.
8. An "incident unhandled" rule never alerts on an ended incident, and its repeats stop when the incident
   ends.

---

### User Story 3: "I'm on it" takes a question from its alert (P2)

A question alert has one action button, **I'm on it**, next to the panel link. Moderator B is on G's team
and taps it. The item becomes B's, as taken through the alert, and stays open. The alert now reads "B is on
it". Later repeats name B instead of the team. The question still closes only when a moderator writes in G.

**Why this priority**: in a shared group, everyone sees every alert. Without a way to say "mine", two
moderators may both go to answer the same question, or both may assume the other has it. It is P2 because
US1 already delivers the alert.

**Independent test**: one open item and one scripted press each. Check the assignment, that the item stays
open, the edited alert, and the next repeat's wording.

**Acceptance**:
1. The press takes the item and never closes it. Its waiting time keeps running until a moderator answers
   in the group.
2. The press is recorded for any declared, active moderator while the item is open. TG-M2.1's rule decides
   the assignment: the earliest act by a member of the group's team at that instant wins. A press by someone
   outside the team is recorded and assigns nobody, like that person's reaction.
3. A press after the item has ended records nothing. The presser is told how it ended.
4. A press by anyone who is not a declared, active moderator records nothing.
5. In "My work", the taking counts under its own "how it was taken" value, "via alert". No other figure
   changes.

---

### User Story 4: the operator sets the rules and reads the alert history (P2)

The panel gains three things:
- **Alert Rules**, for creating, editing and disabling rules;
- **the alert destination**, a single setting that names the alert group;
- **Alerts**, a history of every alert.

The history shows each alert's rule, subject, repeat number, delivery status, times and any error. Each
incident's page lists its alerts and the button presses on them.

**Why this priority**: thresholds are data and the operator owns them. Without the screens, rules need a
database session. The history is how the operator learns that delivery is failing.

**Independent test**: create, edit and disable a rule, and confirm that firing follows each change. Make
delivery fail and confirm the failure is listed with its reason.

**Acceptance**:
1. No rule exists until the operator creates one. With no enabled rule, nothing fires. No threshold value
   exists in the code or in any seed.
2. The panel refuses:
   - a second all-groups rule for the same trigger;
   - a second rule for the same trigger and group;
   - a missing or non-positive threshold on a trigger that needs one;
   - a repeat interval without a maximum, or a maximum without an interval;
   - a quiet-hours window whose start equals its end;
   - naming a monitored group as the destination;
   - switching on monitoring for the destination.
3. An edit affects only evaluations after it. Each alert keeps the rule values that were in force when it
   fired.
4. A rule that has fired can be disabled but not deleted.
5. Every new string is bilingual: English is the key, with Arabic in `lang/ar.json`.

---

### User Story 5: group health alerts (P3)

Two triggers watch coverage:
- **group silent**: a monitored group has had no captured event for longer than the threshold;
- **bot not administrator**: the bot is no longer an administrator in a monitored group.

Each fires once, plus any repeats, and is edited when the group recovers: an event arrives, or the bot is an
administrator again. These alerts have the panel link and no action buttons.

**Why this priority**: the master plan names a lost admin right as the most likely way the system silently
stops working (§27). It is P3 because `make tg-doctor` already detects both conditions on demand.

**Acceptance**:
1. A monitored group that stays silent past the threshold produces one alert. A captured event edits it to
   show when the group resumed.
2. A change of the bot's status away from administrator produces one alert. Regaining administrator edits
   it.
3. A group that is not monitored never produces a health alert.

---

### Edge Cases

- **Two evaluators, a restart or a replay.** The store allows one alert per (rule, subject, repeat number),
  so none of these duplicates an alert.
- **An outage of the evaluator.** On recovery, at most one alert per subject is posted per cycle. Repeats
  missed during the outage are not back-filled, so the alert group is not flooded.
- **A new or re-enabled rule.** It considers only subjects that cross its threshold, or are flagged, at or
  after it was enabled. A backlog of old open items does not produce a flood of alerts; the queue and the
  Incidents list already show the backlog. A group rule that replaces the all-groups rule follows the same
  clause, so nothing already alerted is alerted again from the start.
- **A subject that ends between firing and delivery** is not sent (Acceptance US1-4).
- **The bot removed from the alert group, or no destination set.**
  - Deliveries fail, or are recorded as not sent because there is no destination.
  - Each one shows in the history with its reason.
  - `make tg-doctor` reports the destination as unreachable.
  - No item, incident or figure changes.
- **Telegram rate limiting.** Delivery waits as long as Telegram asks and retries. An alert is never dropped
  silently.
- **A press arrives late**, for example after the poller was down. Telegram does not date button presses, so
  the act's instant is when the press was received. It is judged against the subject's state and the team
  at that instant.
- **A team change between the alert and the press.** Attribution is judged at the press's instant.
- **A moderator deactivated after the alert.** Their later press records nothing.
- **The destination changed while alerts are outstanding.** New alerts go to the new group. Alerts already
  posted are still edited where they were posted, and presses on them are still accepted from declared,
  active moderators.
- **A message link that cannot exist.** Telegram links to a message only in a supergroup. For a basic group
  the alert carries no message link and says so; the panel link remains.
- **A chat migration.** Alerts follow their subject. Links use the surviving chat.
- **Re-derivation.** `rederive_chat` and every replay re-derive button acts from their stored updates and
  converge. They never send, edit or answer anything.
- **A mistaken press cannot be undone**, as with 👀 and the panel's acts. The edited alert and the incident's
  timeline both name who pressed.
- **Quiet hours.** A question that crosses its threshold at 02:00 inside a 00:00–07:00 window is recorded as
  suppressed and never sent. A repeat due at 07:10, if the rule has repeats left, is sent normally, and so is
  every later alert outside the window. A rule without repeats sends nothing for that question; the queue
  shows it.
- **The excerpt and later changes.** The excerpt is quoted when the alert is posted. A student's later edit
  does not change it. Reaching the retention age removes it (FR-535). If the text is no longer held when the
  alert is posted, the alert says "Text removed" in place of an excerpt.
- **The excerpt and redaction.** The redactor replaces links that start with a scheme or `www.`, email
  addresses, @handles and runs of seven or more digits. A scheme-less link such as `t.me/…`, or a phone number
  written in words or split by letters, passes through. The moderators reading the excerpt are the same
  people who read the group.

## Requirements *(mandatory)*

### Functional Requirements

**The destination and the silence guarantee (amends TG-M1's provider contract §8)**
- **FR-501**: There MUST be at most one alert destination, which the operator designates. While none is
  designated, nothing is sent and every alert is recorded as not sent, for lack of a destination.
- **FR-502**: The destination MUST never be a monitored group. Designating a monitored chat MUST be refused,
  and so MUST switching on monitoring for the designated chat.
- **FR-503**: The bot MUST send only three things:
  - new messages, into the destination;
  - edits of its own alert messages;
  - answers to presses on its own alert messages.

  It MUST still have no method to ban, restrict, delete, react or pin. A test and the architecture check
  both assert that nothing is ever addressed to a monitored chat.
- **FR-504**: Nothing in the destination may be measured: no attention item, incident, classification,
  response or figure ever comes from it.

**Rules**
- **FR-510**: Rules MUST be data the operator creates. None is built in, and no threshold value appears in
  code, configuration defaults or a seed.
- **FR-511**: The triggers MUST be:
  - question waiting;
  - incident flagged;
  - incident unhandled;
  - group silent;
  - bot not administrator.
- **FR-512**: A rule MUST carry:
  - its trigger and its scope: all groups, or one group;
  - a threshold, required for question waiting, incident unhandled and group silent, and absent otherwise;
  - for the two incident triggers, optional filters: lowest severity, categories, and opened by (link
    rule, model, operator);
  - an optional repeat interval with a maximum number of repeats, both or neither;
  - optional quiet hours (FR-543);
  - an enabled switch.
- **FR-513**: For each group and trigger, the group's own rule MUST apply if one exists, and otherwise the
  all-groups rule. A disabled group rule MUST mute that trigger for that group. There MUST be at most one
  all-groups rule per trigger and one rule per trigger per group.
- **FR-514**: A rule that has fired MUST NOT be deletable; it can be disabled. Every alert MUST record the
  rule's values in force when it fired.
- **FR-515**: A rule MUST consider only subjects whose qualifying moment came at or after the rule was last
  enabled. The qualifying moment is crossing the threshold, being flagged, or the bot losing its rights.

**Firing**
- **FR-520**: Rules MUST be evaluated on the existing regular cycle (`MODERATION_TICK_INTERVAL_S`). Exactly
  one process evaluates at a time.
- **FR-521**: A subject qualifies by reading the existing derived states, never a second definition of them:
  - **question waiting**: an open item whose waiting time, from its opening, has reached the threshold;
  - **incident flagged**: an incident that matches the filters;
  - **incident unhandled**: an incident that is open or acknowledged, matches the filters, and was flagged at
    least the threshold ago;
  - **group silent**: a monitored group whose last captured event is at least the threshold ago;
  - **bot not administrator**: a monitored group where the bot's recorded status is not administrator.
- **FR-522**: There MUST be exactly one alert per (rule, subject, repeat number). The store guarantees it under
  concurrency, restarts and replays.
- **FR-523**: Repeat k MUST fire only when three things hold:
  - the subject still qualifies;
  - k intervals have passed since the first alert;
  - k is at most the maximum.

  At most one alert per subject is posted per cycle, and missed repeats are never back-filled.
- **FR-524**: Firing, delivering and editing MUST never change an item, an incident, an act or a figure.

**Content**
- **FR-530**: An alert MUST state its kind and the source group's title. It MUST also state:
  - for a question: when it was asked, and how long it has waited;
  - for an incident: category, severity, opener, posting and flagging times, and age;
  - for group health: the last captured event, or the bot's status;
  - who it belongs to: the assigned moderator and how they took it; otherwise the source group's current
    team; otherwise "No team";
  - a link to the message where one can exist, and a link to the panel page.
- **FR-531**: A question alert and an incident alert MUST carry a short excerpt of their message's text. The
  message is the question's opening message, or the incident's flagged message. The excerpt:
  - is the text as the panel shows it;
  - is at most 100 characters, cut at a word boundary and marked with an ellipsis when cut;
  - has links, email addresses, @handles and phone-like digit runs replaced by TG-M0's placeholders, the
    same redactor the model's input goes through.

  When the text is no longer held, the alert says "Text removed" instead. A health alert carries no text.
  An alert MUST NOT carry a student's name, username or any other student identity.

  *Amended during planning (2026-11-12, research D-TG-221):* the excerpt is the message's **first-posted**
  text, re-read from its captured event. The panel's text may have been overwritten by a later edit, which
  would contradict the edge case "A student's later edit does not change it."
- **FR-532**: An alert MUST NOT show the model's self-reported confidence.
- **FR-533**: Alerts MUST be in Arabic only: the message, the button labels and the answers to presses.
  - Category, severity and opener MUST use the panel's Arabic wording, so that an alert and the panel say
    the same thing.
  - The wording MUST never claim a deletion (TG-M4's wording rule, tested in Arabic as the panel's is).
  - It says "flagged", never "violation confirmed".
- **FR-534**: Each moderator an alert names MUST be mentioned, so that Telegram notifies them. That is the
  assignee, or each member of the team.
- **FR-535**: An excerpt MUST NOT outlive the retention period (`MODERATION_TEXT_RETENTION_DAYS`, D-TG-11).
  When its message reaches the retention age, every alert quoting it is edited to replace the excerpt with
  "Text removed". This is judged by the message's age, so it does not wait for TG-M10's purge. An alert that
  can no longer be edited, for example because it was deleted in Telegram, is recorded as such.
- **FR-536**: The excerpt MUST NOT be stored in the alert's record or written to any log line (check 4). It
  is built from the message's held text when the alert is posted.

**Delivery**
- **FR-540**: Delivery MUST be separate from firing. A failure is recorded with its reason and attempt count
  and retried with backoff, up to a bound. Telegram's requested wait is honoured. *Amended during planning (2026-11-12, research D-TG-215):* only a failure in which nothing reached
  Telegram is retried. A send whose outcome is unknown, such as a timeout after the request was written, is
  recorded as failed and never retried, so the group never sees one alert twice.
- **FR-541**: A delivery failure MUST NOT change any state or figure.
- **FR-542**: An alert whose subject ended, or stopped qualifying, before delivery MUST NOT be sent. It is
  recorded as such.
- **FR-543**: A rule MAY carry one or more daily quiet-hours windows. Each window is a start and an end time
  in the panel's display timezone, and may cross midnight.
  - An alert whose firing moment falls inside one of its rule's windows MUST be recorded as **suppressed**.
    It is never sent, then or later.
  - It still takes its repeat number, so the rule's interval and maximum run on. A later repeat that falls
    outside the window is sent normally.
  - Quiet hours MUST NOT change any figure. A question asked overnight waits and counts exactly as it does
    today.
- **FR-544**: `make tg-doctor` MUST report the destination's health:
  - whether one is designated;
  - whether the bot is a member that can post there;
  - that the chat is not monitored.

**Buttons**
- **FR-550**: The buttons MUST be:
  - on incident alerts: ✅ Handled, 🚫 Not a violation, and the panel link;
  - on question alerts: I'm on it, and the panel link;
  - on health alerts: the panel link only.
- **FR-551**: A press MUST be accepted only when all three hold:
  - it is on an alert message the bot posted;
  - its subject is still live;
  - its sender's Telegram identity is a declared, active moderator.

  Otherwise nothing is recorded and the presser is told why.
- **FR-552**: ✅ Handled MUST record a `confirmation`, and 🚫 Not a violation a false-positive closure. Both MUST:
  - go through the incident guard and lock, as panel acts do;
  - be recorded as coming from the alert;
  - name the presser as the moderator;
  - carry the instant the press was received.
- **FR-553**: I'm on it MUST record a taking act on the question that never closes it.
- **FR-554**: Each press MUST produce at most one act. Replays and duplicates are idempotent. Of two
  concurrent presses, exactly one wins.
- **FR-555**: Every press MUST be answered with its result.
- **FR-556**: An act from a press MUST be derived from its stored update, so re-derivation converges.
  Re-derivation MUST NOT send, edit or answer anything.
- **FR-557**: Button acts MUST be qualifying acts under TG-M2.1's assignment rules (amends G-rules and FR-411,
  FR-412).

**Updating alerts**
- **FR-560**: When a subject ends by any route, every alert message for it MUST be edited to show the outcome,
  the actor where one is known, and the time. Its buttons are removed. A health alert is edited when its group
  recovers.
- **FR-561**: A pressed alert MUST be edited at once to show the result. A later repeat MUST name the current
  assignee.
- **FR-562**: An edit failure MUST be recorded and retried. It never changes state.

**Panel**
- **FR-570**: An **Alert Rules** screen MUST create, edit and disable rules under FR-512–FR-515.
- **FR-571**: An **alert destination** setting MUST offer only chats the bot is in that are not monitored.
- **FR-572**: An **Alerts** history MUST be filterable by rule, trigger, group, delivery status and period. It
  shows each alert's status, times, error and presses.
- **FR-573**: An incident's page MUST list its alerts, and its timeline MUST show button acts (for example "✅
  Handled from the alert by A"). The Assigned column MUST read "A · via alert" for an item or incident taken
  through a button.
- **FR-574**: Every new string MUST be bilingual: English is the key, with Arabic in `lang/ar.json`. The Arabic
  never contains a deletion word on incident screens.
- **FR-575**: There MUST be no average, no composite score, and no new per-moderator figure.

**Figures**
- **FR-580**: No figure definition changes. A button act counts as what it is:
  - ✅ Handled is a confirmation and counts in handling-confirmation time;
  - 🚫 Not a violation is a false positive;
  - I'm on it is a taking act ("My work", "via alert").

### Key Entities

- **Alert destination**: the one private Telegram group that receives alerts. It is never monitored, and the
  operator designates it.
- **Alert rule**: an operator-made threshold. It has a trigger, a scope (all groups or one), a threshold,
  filters, repeats, daily quiet-hours windows and an enabled switch. One applies per group and trigger.
- **Alert**: one firing of a rule for one subject at one repeat number. It holds no student text. It
  records:
  - the rule's values at firing;
  - its delivery status: pending, sent, failed, suppressed (quiet hours), or not sent (with the reason);
  - whether its excerpt has been removed under retention;
  - the attempts made and the last error;
  - the posted message, so that presses and edits find it.
- **Button act**: a moderator's press, recorded as an act on the alert's subject. The acts are ✅ Handled, 🚫
  Not a violation and I'm on it. Each is derived from the stored update, with the presser and the instant the
  press was received.

## Success Criteria *(mandatory)*

- **SC-501**: Zero messages are sent to any monitored group. A test asserts it, and the smoke check confirms it
  by reading the student group.
- **SC-502**: Across repeated cycles, restarts and replays, a qualifying subject produces exactly one alert per
  repeat number. No duplicates appear in a 24-hour soak with two evaluators running.
- **SC-503**: Under normal operation, an alert reaches the alert group within one minute of its subject
  qualifying.
- **SC-504**: A moderator resolves an incident from its alert in one tap. The incident shows as resolved in the
  panel on the next refresh. Every alert message for it shows the outcome within one minute.
- **SC-505**: With the destination unreachable for an hour, no item, incident or figure differs from a run
  without alerting. 100% of the failed deliveries appear in the history with their reasons.
- **SC-506**: Over the same captured data, every figure except "My work"'s new "via alert" value is identical
  with alerting on and off. A fixture checks it.
- **SC-507**: 100% of presses by people who are not declared, active moderators record nothing.
- **SC-508**: The operator creates or changes a rule in under two minutes, with no code change and no deploy.
- **SC-509**: No alert is sent during its rule's quiet hours. 100% of the alerts that fall inside them appear in
  the history as suppressed.
- **SC-510**: No student text remains in any alert message more than one day past its message's retention
  age. No excerpt appears in the alert records or in any log line.

## Assumptions

- The moderators are members of the alert group. Telegram membership is its only access control, and removing
  a member is the operator's offboarding step.
- The bot can post in the alert group. It needs no administrator right there.
- Telegram does not date button presses. A press's instant is when it was received.
- Alert times and quiet-hours windows use the panel's display timezone.
- An excerpt in Telegram can be copied or forwarded by anyone in the alert group. The retention edit
  (FR-535) removes it from the bot's own message only. This is the cost of choosing excerpts over links
  only (2026-11-12).
- The excerpt's redaction is TG-M0's pattern redactor. It misses scheme-less links and obfuscated numbers
  (Edge Cases).
- One schema revision is added, the next free number (`0013`). The schema stays Alembic's; the panel adds no
  migration.
- The 30-second cycle bounds how fast an alert can fire (master plan §16). The cycle's interval stays
  deployment configuration, not an alert threshold.
- The operator chooses which triggers to enable. In production the team works incidents and the attention
  queue is paused (2026-11-11). Question alerts fire only if a question-waiting rule is enabled.
- Model-opened incidents alert like any other. The opened-by filter lets the operator exclude them, as TG-M5's
  quickstart asks.

## Dependencies

- TG-M1: the poller already captures `callback_query` (`TELEGRAM_ALLOWED_UPDATES`) and the tick lease.
- TG-M2: groups, monitoring, the bot's status and moderators' Telegram identities.
- TG-M3: attention items and their states.
- TG-M4 / TG-M4.1: incidents, the guard and lock, the evidence views, and 👀.
- TG-M2.1: teams and first-action assignment.
- TG-M5: the incident opener (model) and the link rule.
- The bilingual panel (2026-10-13).

## Out of Scope

- Email, WhatsApp, private messages to moderators, and escalation chains: master plan §25 non-goals.
- Any bot message, reaction or action in a student group, and any auto-moderation.
- Dismissing a question or acknowledging an incident from Telegram. Both stay panel acts.
- Alerts on Possible Violations. These are uncertain predictions with no lifecycle and no button act, and the
  panel list remains their surface. They are reconsidered after TG-M8.
- Forum topics per source group in the alert group, which can be considered if volume grows.
- Digests and scheduled reports (TG-M9, n8n).
- Figures about alerts, such as time from alert to press (TG-M7).
- Reopening an incident or undoing a press.
