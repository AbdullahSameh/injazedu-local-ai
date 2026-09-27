# Contract: The Incident Lifecycle

**Feature**: `specs/007-tg-m4-policy-incidents` · **Status**: durable from TG-M4 onwards — TG-M5 opens
incidents through §1 with `source = 'ai'`, TG-M6 adds one confirmation kind through §5, and neither
changes anything else here.

This is **the** TG-M4 contract: what an incident is, what counts as evidence, which evidence belongs to
which incident, how the state follows from it, and what no code path may ever do. Its SQL half lives in
`data-model.md` §3; its arithmetic half in `incident-metrics.md`.

**The rule that carries all of it: seeing is not acting.** Acknowledgement proves a moderator saw the
message. Only enforcement or a human confirmation resolves it.

---

## §1 — Opening

- **I1.** An incident is opened against exactly one stored, non-service message in a measured group.
  In TG-M4 only the panel opens incidents, with `source = 'operator'`; `source = 'ai'` is reserved.
- **I2.** The anchor is `(telegram_chat_id, telegram_message_id)` — the platform numbers messages per
  chat. One message anchors at most one incident, **ever**, in any state (`uq_incident_anchor`). The
  form excludes anchored messages; the constraint is the backstop.
- **I3.** `opened_at` = the anchor's `sent_at`. `detected_at` = the database's `now()` at insert.
  Neither is ever derived from the other, and neither is ever updated.
- **I4.** `category ∈ {SPAM_OR_AD, ABUSE, OTHER}` and `severity ∈ {low, medium, high}` are required and
  written once. `opened_by_user_id` is the panel account.
- **I5.** `responsible_moderator_id` = `responsible_at(chat, detected_at)` — the primary owner at the
  **flagging** moment, via TG-M2's single definition (Python `assignments.responsible_at`, PHP
  `ModeratorGroupAssignment::responsibleAt`). NULL when nobody owned the group then.
- **I6.** Opening evaluates nothing and writes nothing else. The incident's state is correct the instant
  its row is visible, because the state is a view over evidence (§4) that already includes anything
  recorded before the flag.
- **I7.** Opening an incident never reads or writes an attention item.

---

## §2 — Recognising evidence

Evidence is recognised inside `process_update`, from the captured event, for measured groups only
(`telegram_chats.is_monitored`). The captured event is still marked handled in every case.

### §2.1 Membership changes (`chat_member`)

- **V1.** The classifier is a pure function in `app/domain/moderation/incident.py` over
  `(old status, old is_member, new status, new is_member, performer is subject)`. It returns a kind and
  a strength, or nothing.
- **V2.** A change **performed by the member themselves** is never evidence.
- **V3.** The table, for changes performed by someone else:

  | Old | New | Kind | Strength |
  |---|---|---|---|
  | any | `kicked` | `ban` | enforcement |
  | any | `restricted` | `restriction` | enforcement |
  | `member`, `administrator`, `restricted` (`is_member` true) | `left` | `expulsion` | enforcement |
  | `kicked` | `left`, `member` | `reversal` | — |
  | `restricted` | `member` | `reversal` | — |
  | `restricted` (`is_member` false) | `left` | `reversal` | — |
  | any other pair — joins, promotions, demotions, `creator` changes | | *nothing* | |

  Rows are evaluated top to bottom; the first match wins.
- **V4.** The row records the performer (`from`) and the subject (`new_chat_member.user`), each
  resolved through TG-M2's `upsert_identity`; `occurred_at` is the event's `date`; `detail` carries both
  statuses and any `until_date`.
- **V5.** `actor_moderator_id` is set when the performer is a declared moderator at recording time, by
  TG-M2's `_is_declared_moderator`, and never recomputed.
- **V6.** `actor_is_anonymous` is set when the performer is the platform's anonymous-administrator
  account (`GroupAnonymousBot`). Unverified live — see the quickstart's limitations.

### §2.2 Reactions (`message_reaction`)

- **V7.** `added = new_reaction − old_reaction`, comparing reaction identity (`emoji`,
  `custom_emoji_id`, or `paid`). An empty `added` records nothing.
- **V8.** An event with `actor_chat` and no `user` records nothing: an anonymous reaction names no person.
- **V9.** A reaction is recorded only when the reacting user is a declared moderator at recording time.
  Nobody else's reaction is evidence of anything, so nobody else's is kept.
- **V10.** The row records `target_message_id` (the event's `message_id`), the actor, `occurred_at` =
  the event's `date`, and the added reactions in `detail`.

### §2.3 Replies and panel acts

- **V11.** A moderator's direct reply is **not** recorded as a row. The evidence view reads it from
  `telegram_messages` (`is_from_moderator`, written once at insert by TG-M2).
- **V12.** A panel act is recorded only through §5.

### §2.4 For every row

- **V13.** At most one row per captured event (`uq_moderation_actions_source_update`), inserted with
  `ON CONFLICT … DO NOTHING`. Re-interpreting an event is harmless.
- **V14.** No row is ever updated or deleted.
- **V15.** No row, column, kind or label names or implies a message deletion.

---

## §3 — Linking evidence to incidents

`moderation_incident_evidence` (`data-model.md` §3.1) is the **only** definition. No code path in either
language re-states it.

- **L1.** Every link requires the evidence's timestamp **strictly after** the incident's `opened_at` —
  never compared with `detected_at`, which is why evidence from before the flag links.
- **L2.** Evidence produced by the anchor's own sender never links.
- **L3.** A reaction links when its chat and `target_message_id` equal the anchor.
- **L4.** A reply links when its chat and `reply_to_message_id` equal the anchor and it was sent by a
  moderator.
- **L5.** A membership change links when its subject is the anchor's sender and its chat is the anchor's
  chat **or the chat that chat was promoted to** — one hop, which is complete because a promotion happens
  at most once. One membership change therefore links to every incident on that member's messages in
  that group (FR-030).
- **L6.** A panel act links to the incident it names, and to no other.
- **L7.** An anchor sent on behalf of a chat has no personal sender, so L5 can never match it; the panel
  says so (`control-panel-incidents.md` §1.4 P6).

---

## §4 — Derived state

`moderation_incident_state` (`data-model.md` §3.2) is the **only** definition.

- **S1.** Precedence: a false-positive closure → `closed_false_positive`; else any enforcement or
  confirmation → `resolved`; else any acknowledgement → `acknowledged`; else `open`.
- **S2.** "First" of any kind is the minimum of `(occurred_at, source_rank, evidence_id)`.
- **S3.** `resolved_at` is the earliest enforcement **or** confirmation, whichever came first; the
  resolution's kind and actor are that row's.
- **S4.** Acknowledgement never resolves: no acknowledgement kind carries a resolving strength
  (`ck_actions_strength`).
- **S5.** The state is an aggregate over a set, so it is identical whatever order evidence was processed
  in (FR-045). Evidence recorded after resolution still counts towards its own kind's timing.
- **S6.** Nothing reads the clock, an absence, or a deletion to decide a state (FR-042).

---

## §5 — Human acts and the guard

- **H1.** Three acts, each one row in `moderation_actions`:

  | Act | Kind | Allowed from | Required |
  |---|---|---|---|
  | Acknowledge | `panel_acknowledge` | `open` | — |
  | Resolve | `panel_resolve` | `open`, `acknowledged` | a note |
  | Not a violation | `panel_false_positive` | `open`, `acknowledged` | a reason |

- **H2.** Each act runs in one transaction: take the lock (H4), read the incident's status from
  `moderation_incident_state`, insert the row only if H1 allows it, commit. A disallowed state inserts
  nothing and is not an error — that is what a double submission looks like.
- **H3.** The guard lives on `App\Models\ModerationIncident`, not in a Filament action, so it holds from
  `tinker`. **It is load-bearing**: research probe 8 showed that a closure row inserted over a resolved
  incident without it would change the status.
- **H4.** The lock is `pg_advisory_xact_lock(hashtext('moderation:incidents'))` — this exact literal, in
  both languages. Taken by every panel act and by every **membership-change** insert. Reaction inserts do
  not take it: two acknowledgements racing are two harmless rows.
- **H5.** A human act is judged against the state visible when it is made. A ban captured *after* a
  closure committed does not reopen the question: the closure stands (S1) and the ban is listed in the
  trail.
- **H6.** The note and reason are the operator's words. Nothing parses them; the screen presents them as
  the operator's.
- **H7.** Panel accounts are not moderators. A panel act records `panel_user_id` and credits no
  moderator.

---

## §6 — Attribution

- **A1.** Every per-moderator figure attributes an incident to `responsible_moderator_id` (I5).
- **A2.** Reassigning a group never changes a recorded `responsible_moderator_id`.
- **A3.** The actor of an acknowledgement or resolution is recorded separately: a moderator through
  `actor_moderator_id`, an unmapped performer through `actor_telegram_user_id`, an anonymous one through
  `actor_is_anonymous`, a panel account through `panel_user_id`.
- **A4.** A moderator acting in a group they do not own is shown as the actor, and is never a penalty to
  anyone.
- **A5.** Enforcement by a non-moderator — an unmapped administrator, another bot, an anonymous
  administrator — resolves the incident and credits nobody.

---

## §7 — Idempotency and re-derivation

- **R1.** Interpreting a captured event any number of times yields at most one evidence row (V13).
- **R2.** Opening the same anchor twice yields one incident (I2).
- **R3.** `python -m app.scripts.rederive_chat --chat <id> [--since] [--until] --with-evidence` walks the
  chat's captured `chat_member` and `message_reaction` events in `update_id` order through the **same**
  functions `process_update` calls, then prints `evidence: recorded=<n> incidents_changed=<n>` —
  the latter read from `moderation_incident_state` before and after. Default off.
- **R4.** Re-derivation only ever inserts platform evidence. It never creates, alters or removes an
  incident, a label, or a panel act (FR-085).
- **R5.** Ordinary derivation never reaches back: events captured before this milestone stay as TG-M1
  left them unless R3 is run (FR-083).

---

## §8 — What may never happen

- **N1.** Resolution from acknowledgement alone — in any amount, any combination, any order.
- **N2.** A transition out of `resolved` or `closed_false_positive`.
- **N3.** Any state change from an inferred deletion, from the absence of evidence, or from time.
- **N4.** Any field, kind, label, figure or screen text implying a deletion or its author was observed.
- **N5.** Any bot action in a group: no ban, restriction, deletion, reaction, reply or post. The
  provider exposes no method for any of them.
- **N6.** A second definition of §3 or §4 anywhere — in Python, in PHP, or in a test helper that
  computes a state instead of reading the view.
- **N7.** An `UPDATE` or `DELETE` on `moderation_actions`, or an `UPDATE` of an incident's anchor,
  moments or labels.
- **N8.** Message text in any log line. Correlation is by `incident_id`, `message_id`, `update_id`,
  `chat_id` — never `message`, which stdlib logging rejects (D-TG-24).
