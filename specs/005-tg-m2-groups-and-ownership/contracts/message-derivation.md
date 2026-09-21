# Contract: Message Derivation

**Status**: the contract between TG-M1's captured events and everything that reads
`telegram_messages`. Together with `moderator-ownership.md` it is what TG-M3 onwards codes against.

**Consumers**: TG-M3 (the rule set, burst grouping, response matching), TG-M4 (incidents),
TG-M5 (classification input), TG-M7 (every metric), TG-M10 (retention, and the replay-convergence
proof).

---

## §1 — Which captured events are interpreted here

| Captured kind | TG-M2 | Where it is interpreted |
|---|---|---|
| `message` | ✅ one message row | here |
| `edited_message` | ✅ a targeted update of an existing row | here |
| `my_chat_member` | ✅ chat standing (already handled by TG-M1's discovery; the re-point is added here) | here |
| `chat_member` | ⛔ stored, marked handled, not interpreted | TG-M4 — enforcement actions |
| `message_reaction` | ⛔ stored, marked handled, not interpreted | TG-M4 — acknowledgement actions |
| `callback_query` | ⛔ stored, marked handled, not interpreted | TG-M6 — alert buttons |
| `unknown` | ⛔ stored, marked handled, not interpreted | never |

**Normative.** An event of a kind not interpreted here MUST still be marked handled, with no error and
no derived state. Declining to interpret is not a failure to process.

TG-M1 already *requests* all six kinds, which was the decision that could not be deferred: two of them
are not delivered unless explicitly named and require the bot to be an administrator, and discovering
at TG-M4 that months of them were never requested would be unrecoverable. Interpreting them is not
this milestone's job.

---

## §2 — The two write modes

There are exactly two ways `telegram_messages` is written, and conflating them breaks a guarantee.

### (a) Derivation — INSERT-ONLY

```sql
INSERT INTO telegram_messages (…) VALUES (…)
ON CONFLICT (telegram_chat_id, message_id) DO NOTHING
RETURNING id;
```

**Normative.** Derivation MUST use `DO NOTHING`. It MUST NOT use `DO UPDATE`, for any field, ever.

This single choice makes three requirements one mechanism:

- **idempotency** — the same captured event derived twice yields one row;
- **the moderator flag is never recomputed** — an existing row is not touched at all, so the flag
  written at insert is the flag forever;
- **re-derivation is safe** over a range that overlaps already-derived messages.

If derivation were an upsert, every re-derivation would silently rewrite `is_from_moderator` on
historical messages using *today's* moderator mapping — the exact retroactive rewrite the milestone
exists to prevent, in the flattering direction, with no error and no failing test.

`RETURNING id` distinguishing "inserted" from "already present" is the same idiom TG-M1 uses for its
capture insert.

### (b) An edit — a targeted UPDATE of text only

```sql
UPDATE telegram_messages
   SET original_text = :text, normalized_text = :normalized, edited_at = :edit_date
 WHERE telegram_chat_id = :chat AND message_id = :message_id;
```

**Normative.** The edit path MUST write only those three columns. It MUST NOT touch `sent_at`,
`is_from_moderator`, `telegram_user_id`, `source_update_id` or any flag.

Consequences, each intended:

- `sent_at` keeps the original send time, so the response clock measures what the student actually
  waited (source plan §13.4).
- The flag stays as written at insert, so §2(a)'s guarantee survives edits too.
- An edit for a message that was never derived (it predates measurement) matches zero rows and is a
  no-op — correct, not an error.

**Where the pre-edit text lives.** Not in this table. It is in the immutable captured event that
carried it, verbatim, for as long as `telegram_updates.payload` survives retention. The source plan's
§9 phrase *"stored as a new version of the text, never overwriting the original"* is satisfied by the
append-only capture record, not by a version table — and `original_text` means *raw as opposed to
normalised*, not *pre-edit as opposed to post-edit*. **Accepted limitation:** once a captured event's
payload is purged, the pre-edit text of a message edited within that window is gone. That is the
same cost the domain already accepted for message text generally.

---

## §3 — Per-field derivation rules

| Field | Rule |
|---|---|
| `sent_at` | **The platform's `date`.** Never `received_at`, never `now()`. Authoritative for ordering and for every measurement (G-D2 below) |
| `telegram_user_id` | The upsert of `message.from` — see §4. NULL when there is no personal sender |
| `sender_chat_id` | `message.sender_chat.id` — an anonymous administrator or a channel post. At most one of this and `telegram_user_id` is set; **both** may be NULL, and such a message is still stored |
| `reply_to_message_id` | `message.reply_to_message.message_id`, stored as the platform's identifier with **no** foreign key — the target may predate measurement or predate the bot joining |
| `message_thread_id` | Stored as a fact. Scopes nothing until TG-M3 |
| `is_service` | True for a service announcement. Stored and flagged, never discarded, never counted as a person speaking |
| `original_text` | `text` or `caption`, verbatim, unmodified. NULL when there is none — **never `''`** |
| `normalized_text` | `normalize(original_text)` from TG-M0, unchanged. NULL when `original_text` is NULL. May legitimately be `''` for punctuation-only text, and later matching must not read that as a missing record |
| `media_kind` | Coarse, with `'other'` for anything unmodelled. **No CHECK constraint** — the platform adds media kinds, and rejecting an insert would lose a message |
| `entity_flags` | `has_url`, `has_phone`, `has_mention`, `forwarded`. Recorded; **no conclusion drawn from them here** |
| `source_update_id` | The captured event's row id — the audit link back to the verbatim event |
| `is_from_moderator` | §5 |

**Normative.** Derivation MUST NOT fail on an unmodelled shape. A message whose content this domain
does not model is stored with what is understood and defaults elsewhere. The capture layer already
refused to validate business shape; the derivation layer refuses to reject on it.

---

## §4 — Sender identity

**Normative.** Observing a sender MUST go through the single upsert in `data-model.md` §1, which is
replay-safe in all three directions:

- `first_seen_at` is `LEAST(stored, incoming)` — never moves forward; a genuinely older replayed
  observation may correctly move it back;
- `last_seen_at` is `GREATEST(stored, incoming)` — **never moves backwards**, so an out-of-order replay
  cannot make a group read as having gone quiet;
- the name fields are written **only** when the incoming observation is not older than the stored
  `last_seen_at`.

The guard on the names exists because re-derivation replays weeks-old events, and the obvious
`username = EXCLUDED.username` replaces a current display name with a stale one — silently, and until
that person next posts.

A **placeholder** identity (`first_seen_at IS NULL`, names NULL) is created by mapping a moderator who
has never been observed. The first real observation fills it through the same upsert, creating no
second identity.

---

## §5 — `is_from_moderator`: the snapshot, and its honest limits

**Normative.**

1. It is resolved **at insert**, from whether the sender is a declared, mapped moderator at that moment.
2. It is **never** recomputed. Mapping, unmapping or deactivating a moderator later changes no row
   already written. §2(a) is the mechanism.
3. It does **not** depend on whether that moderator owns the chat. Anyone's answer ends a student's
   wait (`moderator-ownership.md` §4).
4. It is **false** for a bot sender and **false** for a message with no personal sender, always — the
   database enforces the second through `ck_telegram_messages_moderator_needs_user`. The platform
   withholds who acted behind an anonymous administrator, and the flattering guess is the one this
   domain must not make.

**Two limits, both accepted and both documented rather than smoothed over:**

- **A transcript spanning a promotion shows the same person flagged both ways.** That looks like a bug
  and is the correct record. The alternative — a live lookup — would silently convert last month's
  student questions into last month's moderator answers, improving every historical number in the
  direction nobody would question.
- **Re-derivation resolves the flag as of the moment it runs, not as of the message.** `moderators`
  carries no interval, so "was X a moderator on 3 August" is not answerable — the flag *is* the record.
  For a range spanning a mapping change, a re-derive therefore writes flags that live derivation would
  not have written. This is bounded by §2(a): already-derived messages are untouched, so a re-derive can
  only affect rows that had no flag at all. Re-deriving a range that spans a mapping change should be
  done deliberately, and `quickstart.md` says so.

---

## §6 — Measurement gates derivation

**Normative.** A captured event whose chat is not marked measured MUST produce no message row, no
sender identity and no other derived state — and MUST still be marked handled.

Capture is unconditional and derivation is opt-in, which is what makes opting a group in later work
retroactively (§7) and what keeps the bot's presence in a group from being mistaken for consent to
measure the people in it.

Switching measurement **off** stops new derivation and leaves already-derived rows intact. It is not a
retraction.

---

## §7 — Re-derivation

**Shape.** One operator command, `python -m app.scripts.rederive_chat --chat <id> [--since …]
[--until …]`.

**Normative.**

| # | Rule |
|---|---|
| **R1** | It MUST refuse a chat that is not measured. It is not a back door around the measurement decision |
| **R2** | It MUST NOT be reachable from a screen, and switching measurement on MUST NOT start it |
| **R3** | It MUST call the **same** derivation function the actor calls. A second code path is a second set of bugs, and the replay-convergence proof at TG-M10 depends on there being one |
| **R4** | It MUST walk captured events in the platform's assigned order, in bounded batches |
| **R5** | It MUST report three counts: examined, derived, skipped |
| **R6** | A captured event whose payload has already been purged MUST be counted as skipped-because-purged. It MUST NOT produce a hollow row and MUST NOT abort the run |
| **R7** | Running it twice over the same range MUST derive nothing the second time — §2(a) guarantees it |

R3 and R7 together are what make it safe to run without thinking. R5 is what lets an operator tell a
long run from a stalled one, which matters because this is the only action in the milestone with real
data-volume consequences.

It targets events that are **already marked handled**, which is precisely why it is a separate,
operator-invoked path rather than a flag on TG-M1's `drain_pending_updates` — that reconciles the
unhandled backlog and is reused here unchanged.

---

## §8 — Guarantees

| # | Guarantee |
|---|---|
| **G-D1** | Deriving the same captured event any number of times, in any order, yields exactly one message row with identical field values |
| **G-D2** | `sent_at` is always the platform's own send time. The machine's clock never orders messages, so clock skew cannot reorder them |
| **G-D3** | `is_from_moderator` is written exactly once per row and is never rewritten by any later mapping change, edit, or re-derivation |
| **G-D4** | An edit changes text, normalised text and edit time, and nothing else |
| **G-D5** | No event is ever rejected for having a shape this domain does not model; it is stored with what is understood |
| **G-D6** | Events from unmeasured chats produce no derived state, and are still marked handled |
| **G-D7** | Every message row names the captured event it came from, so any derived value can be checked against the verbatim original while that event survives retention |

**Explicit non-promises:**

- No claim that a message is still visible. The platform reports no deletion, and nothing here infers
  one.
- No claim about anything before the bot joined, or during a capture gap longer than the platform's
  retention. Those windows are recorded by TG-M1 and remain unrecoverable.
- No claim that `normalized_text` is a faithful rendering for display. It exists for matching;
  `original_text` is what a human is shown.
- No claim that `entity_flags` means anything. They are observations awaiting a rule set.
