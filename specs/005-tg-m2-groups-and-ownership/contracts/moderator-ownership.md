# Contract: Moderator Ownership

**Status**: the durable contract of TG-M2. Every later milestone that attributes anything to a person
codes against **this** document, the way TG-M1's `telegram-provider.md` is the contract for capture and
M1's `gateway-interface.md` is the contract for model calls.

**Consumers**: TG-M3 (an attention item's responsible owner), TG-M4 (an incident's responsible owner),
TG-M6 (who an alert names), TG-M7 (every per-moderator figure), TG-M8, TG-M10.

---

## §0 — The promise, and the one thing it is not

> **Asked who was responsible for group *C* at instant *T*, the platform answers with the person who
> was responsible *then* — and no change made afterwards moves that answer.**

That is the whole contract. It is worth stating what it is *not*:

- It is **not** "who owns the group now". A current-owner value cannot answer a question about the
  past, and once overwritten it has destroyed the only record of who to ask.
- It is **not** a claim that the responsible owner is the person who acted. Anyone's reply ends a
  student's wait (§4); responsibility and action are separate facts, recorded separately, and
  conflating them is what produces a metric a moderator can rightly dispute.
- It is **not** a claim about whether someone was a moderator at *T*. `moderators` carries no interval
  (D-TG-59). The only record of that is the flag written onto each message — see
  `message-derivation.md` §5.

---

## §1 — The interval algebra

An assignment is a moderator bound to a chat in a role over a **half-open interval**:

```
[ valid_from , valid_to )          valid_to IS NULL ⇒ [ valid_from , ∞ )
  inclusive    exclusive
```

Half-open is not a stylistic choice. It is the only convention under which consecutive intervals
sharing a boundary instant cover that instant **exactly once** — which is what lets a handover be
written as a single timestamp with no gap and no overlap (§2). Closed-closed would double-count the
handover instant; open-open would lose it.

`ck_assignment_interval` requires `valid_to > valid_from` strictly, so a zero-width interval cannot
exist. A zero-width interval covers no instant, so `responsible_at` could never return it: it would be
an ownership record that exists and is invisible. The accepted consequence is that assigning and then
reassigning at the same instant is refused.

---

## §2 — The handover protocol

**Normative.** A change of primary owner MUST be performed as:

1. **one** transaction;
2. **close before open** — set the incumbent's `valid_to`, *then* insert the successor;
3. **one timestamp value**, bound to both the incumbent's `valid_to` and the successor's `valid_from`.

All three are forced by measurement, and each has a distinct failure mode if dropped:

| Dropped clause | What happens | Detected by |
|---|---|---|
| One transaction | A partial failure leaves a chat with no current owner, or two | nothing — the screen shows a plausible list |
| Close before open | `ERROR: duplicate key value violates unique constraint "uq_assignment_one_current_primary"` | loudly, at once — and it **cannot** be worked around by deferring, because a partial unique index is not deferrable (probe 2) |
| One timestamp | **A hole in ownership history with zero owners.** Measured at ~10 ms with two clock readings | ⚠ **nothing.** No constraint fires. `responsible_at` silently returns nothing for any instant inside it, which a later milestone renders as an "Unassigned" coverage problem that never existed |

The third is the dangerous one and it is a PHP-side hazard, because the panel is the writer and
Laravel's `now()` is evaluated per call:

```php
// WRONG — two microsecond values, a hole between them
$incumbent->update(['valid_to' => now()]);
Assignment::create([..., 'valid_from' => now()]);

// RIGHT — one value, bound twice
$at = now();
DB::transaction(function () use ($at, ...) {
    $incumbent->update(['valid_to' => $at]);
    Assignment::create([..., 'valid_from' => $at]);
});
```

SQL `now()` is `transaction_timestamp()` and is identical across statements in one transaction, so the
Python path may use it directly on both sides.

**Where the protocol lives.** On the Eloquent model, not only in the Filament action (D-TG-58) —
mirroring `ModelProfile::save()`, which enforces its own invariant at the model layer *"so they hold
regardless of entry point (panel, tinker, a future artisan command)"*. The Filament reassign action
calls it. A future command calls it. There is one implementation.

**Opening a first owner** (a chat that has never had one) is the same protocol with the close affecting
zero rows. **Closing without a successor** — a chat losing its owner deliberately — is the close alone;
the chat then reads as unassigned (§5), which is a coverage problem to be surfaced, not an error.

---

## §3 — `responsible_at(chat, t)`

**Normative.**

```
responsible_at(chat, t) =
  the moderator of the assignment where
      telegram_chat_id = chat
  AND assignment_role  = 'primary'
  AND valid_from <= t
  AND (valid_to IS NULL OR valid_to > t)
```

Guarantees:

| # | Guarantee |
|---|---|
| **O1** | Returns **at most one** moderator, for every `chat` and every `t`. Guaranteed at `t = now()` by `uq_assignment_one_current_primary`, and for every historical `t` by the handover protocol of §2 |
| **O2** | Returns **nothing** when no interval covers `t`. The current owner is **never** substituted — a question about an unowned instant has the answer "nobody", and answering it with today's owner would attribute a past miss to someone who was not there |
| **O3** | `valid_from` is **included**, `valid_to` is **excluded**. At a handover instant the answer is the **successor** |
| **O4** | Never returns a backup. Backups are recorded and visible, and are not responsible |
| **O5** | **Stable.** For a fixed `chat` and a fixed `t`, the answer changes only if the history covering `t` is itself corrected. No assignment made after `t` can change it |

O5 is what the whole contract is for, and it is the one a reviewer should test adversarially: assign,
query a past instant, reassign twice, query the same instant again, and require the identical answer.

**One definition, two languages.** `app/application/moderation/assignments.py` holds the Python
definition; the Eloquent scope the panel uses mirrors it. Both are tested at the four boundary
positions — before `valid_from`, **at** `valid_from`, **at** `valid_to`, after `valid_to` — not near
them. A boundary tested "around" is a boundary not tested.

---

## §4 — Attribution rules for later milestones

Normative, so TG-M3 and TG-M4 do not each invent their own:

| Question | Answer |
|---|---|
| Who is responsible for an attention item? | `responsible_at(chat, item.opened_at)` |
| Who is responsible for an incident? | `responsible_at(chat, incident.detected_at)` — **not** `opened_at`, so our own detection latency is never charged to a person |
| Whose reply closes an item? | **Any** moderator's. The student's wait ends whoever answers |
| Who gets recorded as having answered? | The actual sender, separately from the responsible owner, so "covered by a colleague" is visible without being a penalty |
| Who is responsible when nobody was assigned? | Nobody. The item or incident carries no owner and the chat is surfaced as unassigned (§5) |

Each consumer **snapshots** the answer onto its own row at creation time rather than joining through
`responsible_at` at read time. The join is the definition; the snapshot is what makes a report
reproducible after an ownership correction.

---

## §5 — Unassigned is a fact, not a gap

A measured chat with no current primary is recorded and **surfaced** (FR-039, FR-049). It is never
given an implied owner, and the absence is never filled by the most recent past owner.

This matters because two very different situations look alike in a report — a group nobody owns, and a
group whose events fell in a history hole (§2) — and only one of them is real. Getting the handover
protocol right is what keeps "unassigned" meaning what it says.

---

## §6 — Chat migration is not a handover

When a group is promoted and its platform identifier changes, ownership follows the group:

**Normative.** The re-point MUST move the assignment rows to the surviving chat row **without closing
any interval and without opening any**, and MUST carry the surviving row's `is_monitored` and
`injaz_course_id` forward from the superseded row, in one transaction.

- No interval changes because the same person owned the same group before and after. Closing and
  reopening would record an ownership change that never happened, and every later report would show a
  handover on the day of a technical migration.
- The carry-forward is not tidiness. TG-M1 creates the surviving row at the table's defaults, so
  `is_monitored` is **false**: without the carry-forward a group silently stops being measured at the
  moment it is promoted, while capture and every health signal stay green.
- If the surviving row **already** has a current primary, the re-point **MUST refuse** and surface the
  conflict, rather than choosing a winner. Picking one would discard an ownership fact silently.

Messages are not re-pointed. "One group's continuous history" is a read that follows
`migrated_from_chat_id` / `migrated_to_chat_id`.

---

## §7 — What this contract does not promise

Stated here so it is not rediscovered later, in the same spirit as the runbook's §F:

- **It cannot say whether someone was a moderator at an arbitrary past instant.** `moderators` has no
  interval. The message flag is the only record, at message granularity. A report needing
  "moderators as of last March" cannot be produced from this schema.
- **It cannot reconstruct ownership before the first assignment was opened.** There is no source of
  truth to import; the platform's administrator history proposes candidates, and everything before the
  operator's first assignment is genuinely unowned rather than retroactively attributed.
- **It cannot detect a historical overlap.** Only the *current* primary is constrained (the stricter
  range-exclusion form needs `btree_gist` enabled at database creation on an already-shipped database —
  source plan §10.5). A backdated correction that overlaps a closed interval is caught by a test, not
  by the database. O1 therefore holds for every `t` **given** that every write went through §2.
- **It says nothing about whether the responsible owner deserved the number.** A moderator who removes
  spam instantly and silently is invisible to the platform, because the platform reports no deletion.
  That asymmetry is the source plan's §18.6 reason for refusing a composite score, and it is not
  something this contract can repair.
