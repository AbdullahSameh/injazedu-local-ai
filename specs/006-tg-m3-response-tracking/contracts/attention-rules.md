# Contract: Attention Rules — the burst, the rule set, and what closes an item

**Feature**: `specs/006-tg-m3-response-tracking` · **Status**: durable from TG-M3 onwards

This is **the** TG-M3 contract, the one the source plan's §30 names. TG-M4 attaches incidents to these
items, TG-M5 replaces the rule set and must beat it on *these* definitions, and TG-M7 renders figures
computed from what this document decides. Everything here is deterministic: given the same stored
messages, the same clock ceiling and the same rule version, the same items result, in any order, any
number of times.

---

## §1 — The burst

> **Burst.** Messages sharing `(telegram_chat_id, telegram_user_id, message_thread_id)` where each is
> separated from the previous, by `sent_at`, by no more than `MODERATION_BURST_GAP_S`.

- `message_thread_id` is compared with `IS NOT DISTINCT FROM`, never `=`: **no thread** is itself a
  distinct thread value that matches only other messages with no thread (FR-002).
- Ordering and gaps use Telegram's `sent_at` only — never `created_at`, never arrival order (FR-003).
- A message sent by a `sender_chat` rather than a person has no `telegram_user_id` and cannot form or
  join a burst (FR-013).
- A burst is **anchored** on its earliest member by `sent_at`. The anchor is what the item points at and
  where `opened_at` comes from (FR-005).

**B1.** A burst opens **at most one** item.
**B2.** `opened_at` is the anchor's `sent_at`. It is never the judgement time, never `now()`, and never
moves.
**B3.** Every member of the burst gets `attention_item_id` set to the resulting item, which is what lets
a direct reply to any of them resolve to it (FR-006).

### Why judgement may run more than once

A burst is only definitively settled a full gap after its **last** message, and that instant is not
knowable in advance. So judgement is scheduled per message and each run recomputes the burst from the
database. Every run finds the same anchor, so `uq_attention_anchor` collapses them to one item
(FR-009). A run that sees a partial burst and declines is not a mistake: a later run sees the whole of
it and opens the item, still dated from the anchor.

**B4.** The delayed message is an **optimisation**. `telegram_messages.attention_evaluated_at IS NULL`
is the authoritative work list, and a sweep claims anything due and unjudged. This is TG-M1's pattern
for `drain_pending_updates`, adopted for the same reason: the queue is not durable and the database is
(research Finding 3).

---

## §2 — Rule set v1

`rule_version = 1`. A pure function of the burst's `normalized_text` and its senders' stored
properties. No I/O, no clock, no model, no network.

### §2.1 The literals are stored normalised

Every literal below is written **as `normalize()` leaves it**, and a unit test asserts
`normalize(literal) == literal` for every entry of both lists.

This is not tidiness. Seven of the thirty-one entries the source plan §13.1 prints do not survive the
normaliser — `متى`, `أين`, `كيفية`, `إيش`, `أبغى`, `مشكلة`, `متأخر` — and FR-019 compares against
normalised text, so each would have matched **nothing, ever, with no error** (research Finding 1). The
self-check test is what keeps that fixed for the entry somebody adds next year.

```
ACK_STOPLIST (9)
  شكرا · تمام · تسلم · جزاك الله خير · ok · okay · 👍 · ❤️ · 🌹
  plus: bare emoji (any run), and normalised length ≤ 2

QUESTION_PATTERNS (30)
  متي · اين · وين · كيف · ازاي · كيفيه · ليش · ليه · لماذا · هل · ايش · ايه · مين · من · كم ·
  ممكن · محتاج · عايز · ابغي · ابي · مشكله · ما ظهر · مش ظاهر · لم تظهر · ما يفتح · مش شغال ·
  دفعت · ما وصل · لم يصل · متاخر
  plus English: how · when · where · why · can i · not working
```

Both lists deduplicate under normalisation: `إيش`/`ايش` collapse to one entry, as do `شكراً`/`شكرا`.

**Matching is on token boundaries, never bare substrings.** `من` ("who") is also the commonest
preposition in Arabic and `كم` is a substring of many words; substring matching would fire on nearly
every message in the corpus. `من` remains in v1 deliberately rather than being quietly dropped — its
cost belongs in the measured false-positive rate (§5), not in an unrecorded judgement call.

### §2.2 The rule

An item opens when **all** of:

1. the sender was **not** recorded as a moderator at send time, is not a bot, and is a person rather
   than a channel or the group (FR-013);
2. no message in the burst is a service announcement (FR-014);
3. the burst is **not** purely acknowledgement — i.e. not every message matches `ACK_STOPLIST` (FR-015);

and **at least one** of:

4. a message contains `؟` or `?`;
5. a message matches `QUESTION_PATTERNS` on a token boundary;
6. a message @-mentions a mapped moderator, or directly replies to a message whose
   `is_from_moderator` is true.

**R1.** Condition 3 is evaluated **before** conditions 4–6 and wins outright. A student replying `تمام`
to a moderator satisfies condition 6; without precedence, every thanks in every group opens an item.
**R2.** The rule set never requires a trailing question mark. Most real questions in these groups carry
none, which is why signals 5 and 6 exist.
**R3.** `rule_version` is stored on every item the rules open. Changing any literal, any pattern or any
condition **bumps the version**. A figure produced under version 1 is never re-explained by version 2.
**R4.** `؟` (U+061F) and `?` both survive NFKC unchanged — measured, not assumed.
**R5.** `normalize()` collapses runs of repeated *letters* but not of repeated **emoji**, so the bare-
emoji rule handles runs itself: `👍👍👍👍` is an acknowledgement.

---

## §3 — Edits

**E1.** An edit re-judges the burst from its **current** text. The pre-edit wording is never consulted:
it survives only inside the captured event, and only until that payload's retention window ends, so
deciding anything from it would make the same edit produce different items at different times.
**E2.** An edit opens an item only when **no item exists for any message of the burst** — waiting,
answered, dismissed or expired. "Previously unqualifying" is read as "no item exists".
**E3.** An item an edit opens anchors on the **edited message**, with `opened_at = edited_at`. The words
could not have been answered before they existed.
**E4.** An edit never reopens, retracts, re-dates or otherwise alters an existing item.
**E5.** Mechanically, an edit clears `attention_evaluated_at` on the edited message and the ordinary
sweep does the rest — one judgement path, not two.

---

## §4 — What closes an item

A message **R** closes an open item **I** when all hold:

- `R.telegram_chat_id = I.telegram_chat_id`;
- `R.is_from_moderator = true` — as recorded on R at insert, never recomputed (TG-M2's write-once rule);
- R's sender is not a bot;
- `R.sent_at > I.opened_at`, **strictly**;

and either

- **(a) direct reply** — `R.reply_to_message_id` is a message whose `attention_item_id = I.id`
  → `first_response_kind = 'direct_reply'`; or
- **(b) group message** — R is the first qualifying moderator message in the same chat **and thread**
  after `I.opened_at` → `first_response_kind = 'group_message'`.

**C1.** (a) is evaluated before (b). When one message satisfies both, the direct reply wins and only the
replied-to item closes.
**C2.** (a) may close an item **out of order** — a moderator answering the older of two waiting
questions closes the one they answered.
**C3.** (b) closes **only the oldest** open item in that chat and thread. One message is never credited
with clearing a backlog.
**C4.** A message whose `sent_at` is not strictly after `opened_at` closes nothing, **in every storage
order**. An answer that arrived before the question could not have answered it.
**C5.** **A reaction never closes an item.** A ✅ on a question is not an answer. Reactions are
acknowledgement evidence for incidents (TG-M4) and change no figure in this milestone.
**C6.** A bot message never closes an item, including this domain's own — which is moot, since the bot
posts nothing.
**C7.** **Any** moderator closes it; `first_response_moderator_id` is recorded separately from
`responsible_moderator_id`, so a colleague covering shows as help and never as a transfer of credit.
**C8.** Closing is `UPDATE … WHERE id = :id AND status = 'open'`. A second closer updates zero rows. A
dismissed or expired item is never closed. Re-running the matcher changes nothing.
**C9.** Ties are broken by `(sent_at, message_id)`, both from Telegram — so the answer is the same on
every re-derivation, rather than "whichever transaction committed first".

### §4.1 The lookback at open time

**C10.** A moderator can answer inside the settle window, before the item exists. So **opening an item
immediately evaluates the messages already stored** after `opened_at` through the *same* matcher. A
question asked at 10:03:10 and answered at 10:03:30 yields an answered item with a response time of 20
seconds — counted in the answered share and in the distribution.

One matcher, two entry points. Two implementations of the same rule would be two ways for the number to
disagree with itself.

### §4.2 Concurrency

**C11.** Judgement and matching hold `pg_advisory_xact_lock` on the chat for the duration of one
transaction. With eight concurrent consumers (`WORKER_PROCESSES × WORKER_THREADS`), rule (b) is a
read-then-write race: row locks alone stop two closers writing the same row but not each selecting a
*different* "oldest". The lock is per chat, so quiet groups pay nothing and busy ones serialise only
against themselves.

---

## §5 — Attribution

**A1.** `responsible_moderator_id = responsible_at(chat, opened_at)` — TG-M2's half-open predicate,
`[valid_from, valid_to)`, primary role only. Snapshotted onto the item at open, never looked up on read.
**A2.** NULL is a real answer, not a missing one. A group with no primary owner at that instant still
collects items, and they surface as **Unassigned** — a coverage problem the screen must show, not hide.
**A3.** Reassigning a group afterwards never moves an existing item's attribution or its number. This is
the runbook's own smoke-test check for this milestone.
**A4.** Every per-moderator figure attributes to `responsible_moderator_id`, never to whoever answered.
**A5.** The rule set's accuracy is arithmetic over stored rows and nothing else:
`precision = 1 − dismissed ÷ opened`, `recall ≈ opened ÷ (opened + operator_added)`. This is the
baseline TG-M5's model must beat, which is why `source` and `rule_version` are stored rather than
inferred.

---

## §6 — Ageing

**G1.** An item ages from `opened_at` until it is answered, dismissed or expired.
**G2.** `status = 'open' AND opened_at < now() - MODERATION_ITEM_MAX_AGE_S` → `expired`. One set-based
guarded UPDATE, idempotent by its own predicate.
**G3.** Expired items are counted unanswered **permanently**, contribute no response time, and are
excluded from the oldest-waiting figure — with their own count shown beside it.
**G4.** Nothing reopens an expired item. A moderator answering much later does not silently change a
historical number.

---

## §7 — What this contract does not promise

- **Nothing about deletion.** Telegram reports no deletion in groups and no deleter. An item whose
  question vanished ages normally; an operator may dismiss it with `close_reason='message_removed'`,
  which is recorded as a human judgement and is never presented as a platform fact.
- **Nothing about unobserved windows.** A question asked while capture was down was never captured and
  opens no item; an answer given then closes none. The windows are recorded (TG-M1) and rendered as
  report incompleteness by TG-M7. Until then this is a stated limitation, not a silent one.
- **No conversation model.** No cross-sender threading, no thread tree. `message_thread_id` scopes a
  burst and models nothing.
- **No judgement of behaviour.** No category, no severity, no confidence, no violation, no score. This
  contract decides what deserves an answer and whether one came. Nothing else.
- **No accuracy claim.** Rule set v1 will open items it should not and miss ones it should. That is why
  §5 exists.
