# Phase 0 Research: TG-M4 — Policy Incidents

**Feature**: `specs/007-tg-m4-policy-incidents`
**Date**: 2026-09-24
**Inputs**: `spec.md` (FR-001…FR-087, SC-001…SC-025, 3 clarifications) ·
`docs/plan/telegram/telegram-moderation-intelligence.md` (§5.1–5.2, §9, §10.8–10.9, §12, §14, §17,
§18.4–18.6, §20, §22, §25 TG-M4, §27) · `docs/runbooks/tg-operator-prerequisites.md` (§B.2, §C TG-M4,
§F) · `.specify/memory/constitution.md` · the merged TG-M0…TG-M3 code · the Telegram Bot API reference
(Bot API 10.3, 2026-08-24)

Decision ids continue the domain's log at **D-TG-98** (TG-M3 ended at D-TG-97).

---

## §0 — Four findings

Each was produced by a probe against the running stack, the test database, the merged code or the
platform's own reference. Two are defects in merged milestones that this milestone's requirements
depend on; one is a limitation of the evidence itself; one decided the shape of the whole design.

### ⚠ Finding 1 — The platform attaches a fake `from` to every message sent on behalf of a chat, and TG-M2's own constraint rejects that row. Channel and anonymous-admin messages never reach `telegram_messages`.

The Bot API reference, `Message.sender_chat`: *"Sender of the message when sent on behalf of a chat.
For example, the supergroup itself for messages sent by its anonymous administrators or a linked
channel … **For backward compatibility, if the message was sent on behalf of a chat, the field `from`
contains a fake sender user in non-channel chats.**"*

`messages.derive_message` resolves `from` into `telegram_user_id` whenever it is a dict
(`app/application/moderation/messages.py:204-222`) and independently copies `sender_chat.id` into
`sender_chat_id` (`:224-225`). A real channel or anonymous-admin post therefore carries **both**, and
TG-M2's `ck_telegram_messages_sender` forbids exactly that. Probe 3, inside `BEGIN … ROLLBACK` in
`injaz_ai_test`:

```
INSERT INTO telegram_messages (… telegram_user_id, sender_chat_id …)   -- both set, as the real payload does
ERROR:  new row for relation "telegram_messages" violates check constraint "ck_telegram_messages_sender"
```

TG-M2's test for this case (`tests/moderation/actors/test_derivation.py:106`) builds the payload with
`from_user=None` — a shape the platform never sends — so the suite is green. In production the
`IntegrityError` fails `process_update`; `processed_at` is never set, the actor retries three times, and
`drain_pending_updates` re-enqueues the same row on every restart.

This matters here because spam **sent as a channel** is one of the commonest violations a moderator
faces, and FR-007 and FR-033 require that an incident can be opened on it and that the screen explain
why no enforcement evidence can arrive for it. As merged, those messages do not exist.

**Resolution (D-TG-99).** When `sender_chat` is present, `from` is treated as the platform's
compatibility placeholder and ignored: `telegram_user_id` stays NULL, no identity is upserted for the
placeholder, and `is_from_moderator` stays false. A test with the payload shape the platform actually
sends replaces reliance on the unrealistic one. **This edits a TG-M2 module and is escalated to the
operator** (plan, ⚠ Item 2).

### ⚠ Finding 2 — The running control panel's percentile floor is zero. The same environment trap would make the incident age ceiling zero, and every incident would be "missed" the instant it opened.

Probe 5, against the running `ai-control` container:

```
printenv MODERATION_PERCENTILE_MIN_SAMPLES | od -c   →  \n          (set, and empty)
config('moderation.percentile_min_samples')          →  int(0)
```

`infra/docker-compose.yml:130` passes `${MODERATION_PERCENTILE_MIN_SAMPLES}` with no default; the
operator's `.env` predates the key (it is in `.env.example:77`), so Compose substitutes an empty string
(and says so: *"The "MODERATION_PERCENTILE_MIN_SAMPLES" variable is not set. Defaulting to a blank
string."*). Laravel's `env('…', 10)` returns the empty string rather than the default when the variable
is *set*, and `(int) ''` is `0` (`apps/ai-control/config/moderation.php:9`). The Python side is
unaffected — the key is not passed to it.

So TG-M3's p90 suppression (its FR-071) is **off** in the running panel: every p90 prints, however few
samples it was built from. TG-M4's figures reuse that floor (FR-063), and TG-M4 adds a second panel
setting — the incident age ceiling — through the same path. Under the same trap it would read `0`, and
FR-059's "missed" would fire the instant any incident was flagged.

**Resolution (D-TG-122).** Every moderation key the panel reads is passed as `${KEY:-default}` in
Compose, and `config/moderation.php` treats a blank value as unset. A feature test pins the blank case.
**This touches a TG-M3 line and is escalated** (plan, ⚠ Item 3), together with the operator step of
adding both keys to `.env`.

### ⚠ Finding 3 — The panel cannot run the Python matcher, and TG-M3 already shows what happens when a rule has two entry points in two languages.

FR-043 and FR-044 require that opening an incident evaluates the evidence already recorded, through the
**same** implementation that evaluates evidence arriving later. In this milestone every incident is
opened in the panel (FR-001, FR-009), and the panel makes no call to the Python side by design.

TG-M3 faced the same shape and did not close it. Its clarification required that opening an item runs
the response matcher over already-stored answers; its Python `open_item` does, but the panel's
hand-open (`apps/ai-control/app/Filament/Pages/LiveAttentionQueue.php:193-216`) inserts the row and
stamps `attention_evaluated_at` so the sweep never revisits it. A hand-opened item whose answer was
already stored stays open until expiry. Two implementations of one rule, and they disagree.

A second, independent pressure points the same way. FR-045 requires the same final state **and
timings** whatever order evidence is processed in, and FR-022 requires the *earliest* acknowledgement
by platform timestamp. The source plan's §10.8 stores `acknowledged_at` / `resolved_at` as columns set
by the transition. A column written once by whichever evidence is processed first is wrong whenever an
earlier piece of evidence is processed later — and a column that can be moved earlier is no longer
written once.

**Resolution (D-TG-104, D-TG-105).** An incident's state, its moments and its timings are **not
stored**; they are a pure function of its evidence, defined once as two SQL views in revision `0006`
and read identically by Python and PHP. Neither language "evaluates" anything, so there is no second
entry point to disagree with the first; order-independence holds by construction; and replay
convergence at TG-M10 is automatic. Only human acts are written, and each is a guarded insert. **This
departs from §10.8's column list and is escalated** (plan, ⚠ Item 1). The TG-M3 hand-open gap is
recorded as an observation for a TG-M3 follow-up and is not fixed here (Principle V).

### ⚠ Finding 4 — No membership change and no reaction has ever been captured. Every payload shape this milestone interprets is known only from the reference.

Probe 1, read-only against the development database:

```
update_type     | count
message         | 5
my_chat_member  | 4
                              -- chat_member: 0   message_reaction: 0
ingestion_state.allowed_updates = [message, edited_message, my_chat_member, chat_member,
                                   message_reaction, callback_query]
telegram_chats: 1 row, supergroup, is_monitored = t, bot_status = administrator
```

The subscription is correct and the bot is an administrator, so the events *should* arrive — but none
ever has, because nobody has reacted, banned or restricted anyone in the dev group since capture began.
The first real `ChatMemberUpdated` and `MessageReactionUpdated` this code sees will be during the smoke
test.

Probe 2 read the reference for the shapes (Bot API 10.3): `ChatMemberUpdated` carries `from`
(*"Performer of the action"*), `date`, `old_chat_member`, `new_chat_member`; member statuses are
`creator`, `administrator`, `member`, `restricted` (with `is_member`), `left`, `kicked`.
`MessageReactionUpdated` carries `user` (*"if the user isn't anonymous"*) or `actor_chat` (*"if the user
is anonymous"*), `date`, `old_reaction`, `new_reaction`; the update *"isn't received for reactions set by
bots"*. `unbanChatMember` on a current member *"will also [remove them] from the chat"*.
`banChatSenderChat` exists and the reference documents no membership update for it. **The reference is
silent on what `ChatMemberUpdated.from` holds when an anonymous administrator acts.**

**Resolution (D-TG-108, D-TG-109).** The membership classifier is a pure function over
`(old status, new status, performer is subject)` tested exhaustively against the documented statuses,
so the shapes are pinned by tests rather than by a live event nobody has seen. The smoke test gains an
explicit step: confirm a `chat_member` row and a `message_reaction` row landed before judging anything
downstream. Anonymous-administrator recognition keys off the platform's anonymous-administrator account
and is written into the known limitations as **unverified live** rather than asserted.

---

## §1 — Probes

Nine probes. Postgres 16.15, Filament v5.7.8, Laravel 12.69.1, Bot API 10.3. Development-database
probes were **read-only** and selected payload *shape* only — keys and status strings, never names or
text. Every schema probe ran inside `BEGIN … ROLLBACK` in `injaz_ai_test` (Principle II).

| # | Question | Result |
|---|---|---|
| 1 | Has any membership change or reaction ever been captured? | **No.** 5 `message`, 4 `my_chat_member`, 0 `chat_member`, 0 `message_reaction` — with the subscription correct and the bot an administrator → **Finding 4** |
| 2 | What do the platform's membership and reaction events contain? | As quoted in Finding 4. Anonymous performer on a membership change: **undocumented** |
| 3 | Does TG-M2 store a message sent on behalf of a chat? | **No.** Real payloads carry a fake `from` *and* `sender_chat`; `ck_telegram_messages_sender` rejects the row → **Finding 1** |
| 4 | Is revision `0006` free? | **Yes.** `alembic_version` = `0005` in both `injaz_ai` and `injaz_ai_test`; `0006`–`0009` reserved by TG-M3's data model |
| 5 | Does the running panel honour its percentile floor? | **No.** Env var set-but-empty → `config()` returns `0` → **Finding 2** |
| 6 | Will the panel's role reach a **view** created by the migrator without a `GRANT`? | **Yes.** `pg_default_acl` for `ai_migrator`, objtype `r` → `ai_control=arwd`; a probe view created as `ai_migrator` gave `has_table_privilege('ai_control', view, 'SELECT') = true`. Views are relations; the default ACL covers them |
| 7 | May the panel's role take a transaction-scoped advisory lock? | **Yes.** `pg_advisory_xact_lock(hashtext('moderation:incidents'))` as `ai_control` succeeds, released on rollback — the cross-language guard D-TG-114 needs |
| 8 | Do `data-model.md` §3's two views, exactly as written, derive the lifecycle correctly? | **Yes**, created as `ai_migrator` over scratch copies of the two tables inside `BEGIN … ROLLBACK`. A moderator reply → incident 1 *acknowledged*, incident 2 *open*. A moderator reaction dated **before** incident 2 was flagged → incident 2 *acknowledged* at the reaction's moment (the first clarification). **One** ban of the sender recorded in the **successor** chat → **both** incidents *resolved*, credited, `resolution_kind = ban` (D-TG-107, FR-030). A later unban → listed in the trail, strength empty, status unchanged (FR-014). A closure row inserted over resolved incident 1 **without** the guard → status becomes *closed_false_positive* — proving rule 1's precedence, and that D-TG-115's guard, not the view, is what keeps *resolved* terminal |
| 9 | Does `contracts/incident-metrics.md`'s SQL, exactly as written, produce the hand-computed figures? | **Yes**, over probe 8's scenario with a 600 s ceiling. Outcomes: flagged 2 = handled 1 + missed 0 + within 0 + false positive 1 (M7's identity holds). Timings over the one non-false-positive incident: the 10:04 reaction against a 10:10 flag → `ack_before_flagging = 1`, `ack_samples = 0`, median NULL — no negative duration anywhere (M12); enforcement 10:12 − 10:10 → **120 s**. Detection latency (300 s, 540 s) → median **420**, p90 **516**, max **540** — `percentile_cont` interpolation as hand-computed. `percentile_cont … FILTER (…)` and `make_interval(secs => …)` both accepted by Postgres 16.15 |

**Not probed, deliberately**: Filament resource, infolist and action wiring; Eloquent casting; Dramatiq
delivery semantics; Livewire polling. All are framework behaviour, exempt under Principle I.

---

## §2 — Decisions

### Schema

**D-TG-98 — Revision `0006_moderation_incidents` creates two tables and two views, and alters
nothing.** `moderation_incidents` (the anchor and the facts of flagging) and `moderation_actions` (the
append-only evidence), plus the views `moderation_incident_evidence` and `moderation_incident_state`.
Down-revision `0005` (probe 4). No `GRANT` (probe 6). *Alternative rejected:* altering
`telegram_messages` to point at an incident, as TG-M3 did for items — an incident anchors on exactly one
message and the composite anchor already expresses it.

**D-TG-99 — A message carrying `sender_chat` is stored with no personal sender.** Finding 1. `from` is
ignored when `sender_chat` is present; no placeholder identity is created. *Alternative rejected:*
loosening `ck_telegram_messages_sender` — it would store the placeholder as if it were a person, and
the channel's post would then appear to come from a user who could be banned.

**D-TG-100 — The incident anchor is `UNIQUE (telegram_chat_id, telegram_message_id)` with a composite
FK onto `telegram_messages`.** FR-002. TG-M3's Finding 2 applies unchanged — §10.8 prints
`UNIQUE (telegram_message_id)` and would silently collide on the second group's early messages under any
idempotent insert. The FK makes an incident on a message that was never stored impossible.

**D-TG-101 — Labels are `category IN ('SPAM_OR_AD','ABUSE','OTHER')` and
`severity IN ('low','medium','high')`, both `NOT NULL`, spelled exactly as D-TG-08's taxonomy.** The
second clarification. Spelling them as the taxonomy does means TG-M5's predictions and today's operator
labels compare without a mapping. Provenance is `source`: an operator-opened incident carries operator
labels and a NULL `message_classification_id`, enforced by a CHECK. Labels are never updated
(FR-006); no code path issues an `UPDATE` on them.

**D-TG-102 — `source IN ('operator','ai')`; `ai` is reserved and never written.** FR-005, FR-009.
`opened_by_user_id` is required exactly when `source = 'operator'` — one CHECK. No FK to `users`,
matching TG-M3's `closed_by_user_id`.

**D-TG-103 — `String` columns with `CHECK` constraints, not enum types.** D-TG-73 carried forward.

### State as a function of evidence

**D-TG-104 — An incident stores no status and no transition moments; both are derived.** Finding 3.
`moderation_incident_state` computes, per incident: the status, the earliest acknowledgement, the
earliest enforcement, the earliest confirmation, the resolution (the earliest of the last two), and the
false-positive closure — each with its actor. Precedence, stated once in the view:
**closed_false_positive** if a false-positive closure exists; else **resolved** if any enforcement or
confirmation exists; else **acknowledged** if any acknowledgement exists; else **open**. Resolved and
closed are terminal *by construction*: evidence is never deleted, so a resolution can never be undone,
and false-positive precedence means nothing recorded after a closure can move it. *Alternatives
rejected:* §10.8's stored `status` with write-once transition columns — cannot satisfy FR-045 (Finding
3); stored columns moved with `LEAST()` — no longer write-once, and still two definitions once the panel
opens incidents; a Python sweep that evaluates panel-opened incidents — reintroduces the second entry
point and depends on the tick, which does not run without a credential.

**D-TG-105 — `moderation_incident_evidence` is the one definition of which evidence belongs to which
incident.** FR-044. A `UNION ALL` of four sources, each with the same predicate spine — same group
lineage, platform timestamp strictly after the posting moment, and never the offending message's own
sender (FR-016, FR-025):

| Source | Links to the incident when |
|---|---|
| a moderator's reaction (`moderation_actions`, `reaction`) | same chat, `target_message_id` = the anchor |
| a moderator's direct reply (`telegram_messages`, read in place — FR-012) | same chat, `reply_to_message_id` = the anchor, `is_from_moderator` |
| a membership change (`moderation_actions`, `ban`/`expulsion`/`restriction`/`reversal`) | `subject_telegram_user_id` = the anchor's sender, chat in the anchor's lineage |
| a panel act (`moderation_actions`, `panel_*`) | `moderation_incident_id` = the incident |

Pre-flagging evidence is included (the first clarification) because the predicate is "after posting",
not "after detection".

**D-TG-106 — The earliest evidence of a kind is chosen by `(occurred_at, source order, row id)`.** FR-022,
FR-045. Two moderators reacting in the same second produce one deterministic "first", identical on
every read — the same reasoning as D-TG-84.

**D-TG-107 — Group lineage in the view is one hop forward: the anchor's chat, or the chat it was promoted
to.** FR-082. A basic group is promoted to a supergroup at most once and a supergroup cannot be
promoted again, so one hop is complete. Only membership evidence crosses it: reactions and replies to a
message in the superseded group cannot happen after promotion. Incidents themselves are **not
re-pointed** at promotion, for exactly TG-M3's reason (the composite FK onto a per-chat message
number) — `repoint_for_migration` is unchanged and its docstring gains one sentence.

### Evidence

**D-TG-108 — Membership changes are classified by a pure function over
`(old status, new status, performer is subject)`.** Finding 4, FR-010, FR-013, FR-014. Lives in
`app/domain/moderation/incident.py`. The table it implements:

| Old → new, performed by someone else | Kind | Strength |
|---|---|---|
| anything → `kicked` | `ban` | enforcement |
| anything except `restricted` → `restricted`; or `restricted` → `restricted` | `restriction` | enforcement |
| `member` / `restricted` (member) / `administrator` → `left` | `expulsion` | enforcement |
| `kicked` → `left` / `member` | `reversal` | — |
| `restricted` → `member`; `restricted` (not a member) → `left` | `reversal` | — |
| any change **performed by the member themselves**; any change to or from `administrator`/`creator` other than the expulsion above; `left` → `member` | *not evidence* | — |

`member → left` performed by someone else is an expulsion whether it came from a basic group's
remove-member, or from `unbanChatMember` on a current member (probe 2). The kind is deliberately **not**
named `removal`: every label on the incident screens is tested for the substring `remov` (D-TG-126), and a
member's expulsion must never read like a message's deletion. A client's "remove" in a supergroup arrives as
`→ kicked` then `kicked → left`: a ban, then an inert reversal — the spec's edge case exactly.

**D-TG-109 — The performer is recorded as the platform names it; an anonymous administrator is
recognised by the platform's anonymous-administrator account.** FR-032. `actor_is_anonymous` is set
when the performer is the bot account the platform substitutes for anonymous administrators
(`GroupAnonymousBot`). The reference does not document this for membership changes (probe 2), so the
behaviour is listed as unverified live in the quickstart. A performer who is a bot but not that account
is shown as a bot; a mapped moderator is credited through `actor_moderator_id`.

**D-TG-110 — Only reactions *added* by a person who is a declared moderator when the event is recorded
are kept.** FR-011, FR-013, FR-015. `added = new_reaction − old_reaction`; an update that only removes
records nothing; an update with `actor_chat` and no `user` records nothing; the moderator test is TG-M2's
`_is_declared_moderator`, reused rather than restated, and its result is written onto the row as
`actor_moderator_id` and never recomputed. The emoji added are kept in `detail`, so a later milestone
could narrow "any reaction" without re-deriving.

**D-TG-111 — A moderator's direct reply is never copied into `moderation_actions`.** FR-012. It already
exists as a message with `is_from_moderator` written once at insert; the evidence view reads it in place.
A second copy would be a second record of one fact.

**D-TG-112 — Evidence derivation runs inside `process_update`, gated on `is_monitored`, idempotent by
`UNIQUE (source_update_id)`.** FR-010, FR-019, FR-083. Mirrors `derive_message` exactly: an unmeasured
chat produces nothing, and `processed_at` is still set. Because derivation happens inside the actor that
marks the captured event handled, TG-M1's pending-updates work list is what makes it durable — no new
sweep, no new actor, no Redis-only state. Identities for performer and subject go through TG-M2's
`upsert_identity`, so their names follow the existing retention rules.

**D-TG-113 — `moderation_actions` is append-only, and the panel's model refuses updates and deletes.**
FR-018. No code path issues `UPDATE` or `DELETE` on it; the Eloquent model throws from its `updating`
and `deleting` events, so the invariant holds from `tinker`, as TG-M2's and TG-M3's models established.

### Human acts

**D-TG-114 — Every write that can change an incident's state takes one transaction-scoped advisory lock,
`pg_advisory_xact_lock(hashtext('moderation:incidents'))`, in both languages.** FR-040, probe 7. The race
that matters is a false-positive closure against a concurrent enforcement: without a shared lock, an
observer could see *resolved* and then *closed as a false positive* — a transition out of a terminal
state. Panel acts and membership-evidence recording take the lock; reaction recording does not, because
two acknowledgements racing produce two harmless rows. One global key rather than per-chat, because
membership evidence can affect incidents in a predecessor chat (D-TG-107) and incident writes are rare
enough that a global serialisation costs nothing measurable. *Alternative rejected:* per-chat keys — a
promotion makes the right key set depend on lineage, and two-key ordering is a deadlock waiting for a
code change.

**D-TG-115 — A panel act is a guarded insert: under the lock, read the derived state, insert only if the
state permits.** FR-034…FR-036, FR-040, FR-041. Acknowledge requires `open`; resolve and close require
`open` or `acknowledged`. A double submission sees the state its first submission produced and inserts
nothing. The guard lives on the `ModerationIncident` model, not in a Filament action.

**D-TG-116 — Opening an incident is a plain insert: identity, both moments, labels, opener, and the
responsible moderator at detection.** FR-001…FR-006, FR-043, FR-046. `detected_at` is the database's
`now()`; `responsible_moderator_id` comes from TG-M2's `responsibleAt` scope at `detected_at`. Nothing is
evaluated at open, because nothing needs to be: the incident's state is correct the moment the row is
visible (D-TG-104). The form excludes service messages and messages that already anchor an incident;
the unique constraint remains the backstop.

**D-TG-117 — A resolve note and a false-positive reason are required text on the action, and neither is
parsed.** FR-035, FR-036. They are the operator's words; the screen presents them as the operator's
confirmation, never as a platform observation.

### Figures

**D-TG-118 — `contracts/incident-metrics.md` is the single definition of every incident figure, quoted by
Python and PHP.** FR-066. Same arrangement as D-TG-90.

**D-TG-119 — Outcome is computed at query time from the resolution moment, the detection moment, the
ceiling and `now()`.** The third clarification, FR-059…FR-062. *Handled*: resolution ≤ detection +
ceiling. *Missed*: not handled, and `now()` past the ceiling. *Within window*: otherwise. False positives
are in none. Stored nowhere, so nothing can drift from the definition; stable once the window closes
except for evidence dated inside it and processed after it, which the spec records.

**D-TG-120 — Each timing is a `percentile_cont` over non-false-positive incidents whose earliest evidence
of that kind is at or after detection; earlier evidence feeds a separate "acted before flagging"
count.** The first clarification, FR-051…FR-056, FR-063. Evidence exactly at detection is a zero-second
sample, not "before". The p90 floor is `MODERATION_PERCENTILE_MIN_SAMPLES`, reused.

**D-TG-121 — Detection latency is reported per group only, over every incident including false
positives.** FR-054. It is a statement about the system — here, the operator — and a false flag took
exactly as long to raise as a true one. No per-moderator query selects it.

**D-TG-122 — The incident age ceiling is `MODERATION_INCIDENT_MAX_AGE_S`, default 86400, validated
positive, readable by both sides; every panel key is passed with a Compose default and read blank-safe.**
Finding 2, FR-058. *Alternative rejected:* reusing `MODERATION_ITEM_MAX_AGE_S` — the spec names a
separate ceiling, and the two will diverge the first time management discusses either.

### The control panel

**D-TG-123 — Incidents are a Filament resource with a list and a view page, no create, edit or delete
page.** FR-067…FR-077. Opening is a header action with a message picker and the two labels; the panel
acts are actions on the view page. Unlike TG-M3's queue, an incident has a detail page with six
questions to answer, which is what a resource's view page is.

**D-TG-124 — The figures ship as a table on the incidents list page, per group and per moderator, scoped
by a period filter.** FR-063. D-TG-97's reasoning: TG-M7 owns the dashboard.

**D-TG-125 — The Live Attention Queue gains one row action, "Open incident", and nothing else.** FR-072.
It opens the same form against the item's anchoring message and never touches the item.

**D-TG-126 — Wording is enforced by a test.** FR-020, FR-070, SC-013. A feature test renders the list
and the detail pages and asserts the standing statement is present, then removes that statement and the
retention marker ("Text removed") and asserts no `delet` or `remov` substring remains. Same shape as
D-TG-92's no-average test, and for the same reason: it is the most likely well-meaning regression.

**D-TG-127 — The bot's standing and the channel-sender limitation are shown on the detail page from
stored facts.** FR-033, FR-071. `telegram_chats.bot_status <> 'administrator'` renders the "evidence
cannot arrive" notice; an anchor with `sender_chat_id` and no `telegram_user_id` renders the
"confirmation only" notice. Both read columns that already exist.

### Re-derivation

**D-TG-128 — `rederive_chat.py` gains `--with-evidence`, default off.** FR-084, FR-085. It walks the
chat's captured `chat_member` and `message_reaction` events in `update_id` order through the **same**
derivation functions `process_update` calls, reports evidence recorded and incidents whose derived
status changed (read from the view before and after), and is idempotent by D-TG-112's unique key. It
cannot touch a human act: it only ever inserts platform evidence. Probe 1 says there is currently
nothing for it to find in development; it exists for the first backfill after the pilot.

---

## §3 — Settings

| Key | Default | Status |
|---|---|---|
| `MODERATION_INCIDENT_MAX_AGE_S` | 86400 | **New.** Python `Settings` (validated positive), `.env.example`, Compose `${…:-86400}` to `ai-control`, `config/moderation.php` blank-safe |
| `MODERATION_PERCENTILE_MIN_SAMPLES` | 10 | **Exists** (TG-M3). Compose line gains `:-10`; `config/moderation.php` becomes blank-safe (Finding 2) |

---

## §4 — What this milestone deliberately does not build

- No automatic opening, no classifier, no confidence routing — TG-M5. `source = 'ai'` is reserved.
- No alert, no button, no outbound message — TG-M6. A button's confirmation will be one more
  `moderation_actions` row with strength `confirmation`; nothing in the view changes.
- No overview, no team-performance screen, no incompleteness banner — TG-M7.
- No label correction — TG-M8.
- No bot action of any kind, no deletion probe, no deletion inference.
- No fix to TG-M3's hand-open lookback gap (Finding 3) — recorded for a TG-M3 follow-up.
- No new actor, no new sweep, no tick change: evidence rides `process_update`, and state needs no
  evaluation step.

---

## §5 — Traceability

| Requirement group | Decisions |
|---|---|
| Opening (FR-001…FR-009) | D-TG-100, D-TG-101, D-TG-102, D-TG-116, D-TG-125, D-TG-99 |
| Recording evidence (FR-010…FR-020) | D-TG-108…D-TG-113, D-TG-99 |
| Acknowledgement (FR-021…FR-025) | D-TG-104, D-TG-105, D-TG-106, D-TG-110, D-TG-111 |
| Resolution (FR-026…FR-033) | D-TG-104, D-TG-105, D-TG-107, D-TG-108, D-TG-109, D-TG-127 |
| Confirmation and false positives (FR-034…FR-038) | D-TG-114, D-TG-115, D-TG-117 |
| Lifecycle integrity (FR-039…FR-045) | D-TG-104, D-TG-105, D-TG-106, D-TG-114, D-TG-115 |
| Attribution (FR-046…FR-050) | D-TG-116 (TG-M2's `responsibleAt`, D-TG-48) |
| Timings and outcomes (FR-051…FR-066) | D-TG-118…D-TG-122 |
| Screens (FR-067…FR-077) | D-TG-123…D-TG-127 |
| Boundaries and re-derivation (FR-078…FR-087) | D-TG-107, D-TG-112, D-TG-128, D-TG-122 |
