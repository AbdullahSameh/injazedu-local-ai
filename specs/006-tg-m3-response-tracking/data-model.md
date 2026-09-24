# Data Model: TG-M3 — Deterministic Response Tracking

**Feature**: `specs/006-tg-m3-response-tracking`
**Revision**: `0005_moderation_attention` — down-revision `0004`, confirmed head (research probe 9).
`0006`–`0009` stay reserved for TG-M4…TG-M6.

One table created, one table altered, nothing else touched. Alembic owns all of it; the panel owns
none of it.

---

## §1 — `attention_items`

The derived unit of work: one question waiting for an answer. Source plan §10.7, corrected by
research Finding 2.

| Column | Type | Null | Notes |
|---|---|---|---|
| `id` | bigserial | no | PK |
| `telegram_chat_id` | bigint | no | FK → `telegram_chats.id` |
| `telegram_message_id` | bigint | no | **the burst's earliest message**, not any later one |
| `opened_at` | timestamptz | no | = that message's `sent_at` (FR-005). Never the judgement time |
| `source` | varchar(20) | no | `rule` \| `operator`. `ai` is reserved for TG-M5 and never written here |
| `rule_version` | smallint | yes | which rule set opened it; NULL for `source='operator'` (FR-049) |
| `message_classification_id` | bigint | yes | shaped for TG-M5, always NULL here. No FK until `0007` creates the table |
| `responsible_moderator_id` | bigint | yes | FK → `moderators.id`. Snapshotted from `responsible_at(chat, opened_at)`; NULL is a real answer (FR-042) |
| `status` | varchar(20) | no | `open` \| `answered` \| `dismissed` \| `expired`, default `open` |
| `first_response_message_id` | bigint | yes | the closing message's Telegram id |
| `first_response_at` | timestamptz | yes | the closing message's `sent_at` (FR-031) |
| `first_response_moderator_id` | bigint | yes | FK → `moderators.id`. Separate from responsible (FR-032) |
| `first_response_kind` | varchar(20) | yes | `direct_reply` \| `group_message` (FR-023, FR-024) |
| `closed_at` | timestamptz | yes | when a person dismissed it, or when expiry ran |
| `closed_by_user_id` | bigint | yes | the panel account that dismissed or hand-opened it |
| `close_reason` | varchar(40) | yes | `not_a_question` \| `message_removed` \| `expired` \| operator text (FR-046) |
| `created_at` | timestamptz | no | `server_default now()`. Never used for period selection (FR-064) |

### Constraints

| Name | Shape | Protects |
|---|---|---|
| `uq_attention_anchor` | `UNIQUE (telegram_chat_id, telegram_message_id)` | FR-007, FR-009, FR-050. **Finding 2**: the chat id is load-bearing, not decoration |
| `fk_attention_message` | FK `(telegram_chat_id, telegram_message_id)` → `telegram_messages (telegram_chat_id, message_id)` | an item can never anchor on a message that was never stored |
| `ck_attention_source` | `source IN ('rule','operator','ai')` | D-TG-73 |
| `ck_attention_status` | `status IN ('open','answered','dismissed','expired')` | D-TG-73 |
| `ck_attention_response_kind` | `first_response_kind IS NULL OR first_response_kind IN ('direct_reply','group_message')` | D-TG-73 |
| `ck_attention_answered_complete` | `status <> 'answered' OR (first_response_at IS NOT NULL AND first_response_message_id IS NOT NULL AND first_response_kind IS NOT NULL)` | an answered item with no recorded response is a metric that cannot be defended |
| `ck_attention_response_order` | `first_response_at IS NULL OR first_response_at > opened_at` | FR-028 at the storage layer, not only in code |
| `ck_attention_rule_version` | `(source = 'rule') = (rule_version IS NOT NULL)` | FR-012 and FR-049 in one clause |

### Indexes

| Name | Shape | Serves |
|---|---|---|
| `ix_attention_open` | `(opened_at) WHERE status = 'open'` | the queue's ordering, the oldest-waiting figure, and the expiry scan. Partial, so it shrinks to the live backlog |
| `ix_attention_chat_thread_open` | `(telegram_chat_id, message_thread_id, opened_at) WHERE status = 'open'` | rule (b)'s "oldest open item in this chat and thread" (D-TG-83) |
| `ix_attention_chat` | `(telegram_chat_id, opened_at DESC)` | per-group figures |
| `ix_attention_moderator` | `(responsible_moderator_id, opened_at DESC)` | per-moderator figures |

`message_thread_id` is denormalised onto the item for `ix_attention_chat_thread_open` — rule (b) is
evaluated per chat *and thread*, and joining back to `telegram_messages` for it on every moderator
message would make the hot path a join.

---

## §2 — `telegram_messages`, altered

Two columns. Nothing existing is modified, and TG-M2's write-once guarantee for `is_from_moderator`
is untouched.

| Column | Type | Null | Notes |
|---|---|---|---|
| `attention_item_id` | bigint | yes | FK → `attention_items.id`. **Burst membership**: set on every message of the burst an item was opened from, which is what lets a direct reply to *any* of them resolve to the item (FR-006, FR-023) |
| `attention_evaluated_at` | timestamptz | yes | set for every message a judgement considered, **whether or not an item resulted** |

| Name | Shape | Serves |
|---|---|---|
| `ix_messages_unjudged` | `(sent_at) WHERE attention_evaluated_at IS NULL` | the sweep's authoritative work list (D-TG-72, Finding 3). Partial, so it is empty in steady state |
| `ix_messages_attention_item` | `(attention_item_id) WHERE attention_item_id IS NOT NULL` | resolving a direct reply to its item |

**Why two columns and not one.** A NULL `attention_item_id` cannot distinguish *not yet judged* from
*judged, and correctly declined* — and most messages are the second. Without `attention_evaluated_at`
the sweep would re-judge every ordinary message in the database on every run, forever.

---

## §3 — The state machine

```
                  ┌────────── moderator answers (FR-022) ──────────▶  answered   (terminal)
                  │
   (rule|operator)│
        ───▶  open ├────────── operator dismisses (FR-046) ─────────▶  dismissed  (terminal)
                  │
                  └────────── opened_at + max_age < now() ──────────▶  expired    (terminal)
```

All three transitions are the same guarded write: `UPDATE … WHERE id = :id AND status = 'open'`
(D-TG-85). The guard is simultaneously the concurrency control, the write-once rule, and the reason
re-running any step is harmless. **There is no transition out of a terminal state** — not on a later
moderator message (FR-035), not on an edit (FR-024), not on a second dismissal.

### How each status counts

| Status | First-response time | Unanswered count | Oldest-waiting |
|---|---|---|---|
| `open` | — | **yes** | **yes** |
| `answered` | **yes** | — | — |
| `dismissed` | — | — | — |
| `expired` | — | **yes**, permanently | — |

The asymmetry on `expired` is deliberate and is the honest treatment (§13.5, §18.3): it was never
answered, so the count keeps it; it has no response, so a response time would have to be invented; and
it would otherwise pin the oldest-waiting figure at three days forever.

---

## §4 — Retention

`attention_items` stores **no message text**. It stores timestamps, identifiers and attribution, all of
which survive the text's removal — which is what makes FR-061 (an item still readable after its words
are purged) a property of the schema rather than of a screen.

The queue's "beginning of the question" is read through `attention_item_id` from
`telegram_messages.original_text`, so when TG-M10's purge nulls that column the item keeps every number
and loses only the words. No column added here is in scope for the purge.

---

## §5 — What revision `0005` deliberately does not do

- **No `GRANT`.** `ALTER DEFAULT PRIVILEGES FOR ROLE ai_migrator` already reaches `ai_control` in both
  databases (`infra/postgres/initdb/01-roles.sql:20`, TG-M2 probe 9, research probe 10).
- **No `moderation_incidents`, no `moderation_actions`** — `0006`, TG-M4.
- **No `message_classifications`** — `0007`, TG-M5. The FK column exists and stays NULL; the FK
  constraint itself is added by `0007`, because the target table does not exist yet.
- **No enum types** — D-TG-73.
- **No change to any TG-M2 column**, in particular none to `is_from_moderator`, whose write-once
  property this milestone depends on for FR-029.
- **No view and no materialised view.** Every figure is a query defined in
  `contracts/attention-metrics.md`; a view would become a second place to change a definition.
- **No trigger.** Every transition is an explicit statement from named code, so a re-derivation runs
  the same path as live traffic.
