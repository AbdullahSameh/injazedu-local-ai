# Contract: Control Panel — the Live Attention Queue

**Feature**: `specs/006-tg-m3-response-tracking` · **Status**: durable from TG-M3 onwards

One new screen in the existing **Moderation Intelligence** navigation group, beside TG-M2's Telegram
Groups and Moderators. Filament v5.7.8, Laravel 12.69.1, Livewire 4.4.3.

---

## §1 — The screen

A **custom page with a table**, not a resource. An attention item is not operator-created CRUD: the only
writes are dismiss and hand-open, and both are actions.

| Column | Source | Notes |
|---|---|---|
| Group | `telegram_chats.title` | `dir="auto"` |
| Question | `telegram_messages.original_text`, truncated | `dir="auto"`. Renders "text removed" when purged |
| Responsible | `moderators.display_name` | **Unassigned** badge when NULL — never blank, never omitted |
| Status | `attention_items.status` | |
| Waiting | `now() - opened_at`, server-side | Human units |

**P1.** Ordered **longest-waiting first** (`opened_at ASC`), because that is the order the work should be
done in.
**P2.** `->poll('15s')` — `Filament\Tables\Table\Concerns\CanPollRecords::poll()`, measured present in
v5.7.8. No custom JavaScript.
**P3.** The waiting time is recomputed **server-side on each poll**. A browser ticker would disagree with
every other number by the viewer's clock skew.
**P4.** Arabic content carries `dir="auto"` **per field**; the panel's locale and chrome stay English and
LTR. Carried unchanged from TG-M2's D-TG-56 — per-navigation-group direction does not exist in this
framework, and this is the first milestone that actually displays message text.

---

## §2 — Actions

| Action | Kind | Writes |
|---|---|---|
| Dismiss (not a real question) | row | `status='dismissed'`, `close_reason='not_a_question'`, `closed_at`, `closed_by_user_id` |
| Dismiss (message removed) | row | as above, `close_reason='message_removed'` |
| Open item by hand | header | `source='operator'`, `rule_version=NULL`, `opened_at` = the chosen message's `sent_at` |

**P5.** **No bulk action anywhere.** Dismissing twenty items with one click is how a false-positive count
stops meaning anything.
**P6.** Hand-opening against a message that already anchors an item is **prevented in the form**, not
resolved by the database throwing. `uq_attention_anchor` remains the backstop.
**P7.** "Message removed" is recorded as a human judgement. No screen text anywhere may suggest Telegram
reported a deletion — a standing footnote says it does not.
**P8.** Every write goes through the guarded update of `contracts/attention-rules.md` C8, so a
double-submitted dismissal is harmless.

---

## §3 — The figures

A second table on the same page, scoped by a period filter, per group and per moderator: asked,
answered, median, p90 with its sample count, max, unanswered count and share, oldest waiting.

**P9.** Every number is the SQL of `contracts/attention-metrics.md`, quoted. The panel defines no
arithmetic of its own.
**P10.** p90 below the sample floor renders a stated reason, not a number (M6). NULL renders "no data",
not "0s" (M8).
**P11.** Not a second navigation entry. TG-M7 owns Team Performance; shipping half of it now would have
to be removed later.

---

## §4 — What the panel may not do

- **No migration.** Alembic owns the schema; the panel owns none of it.
- **No model call, no Telegram call, no outbound message.** The bot stays silent.
- **No bulk job behind a toggle**, and no control that triggers a backfill. Re-derivation is the
  operator's command line, deliberately (D-TG-89).
- **No average and no composite score** — enforced by a test, because "add an average, it is one line"
  is this milestone's most likely well-meaning regression.
- **No write to `is_from_moderator`**, to any TG-M2 column, or to an item's `opened_at`.
- **No `RefreshDatabase`, `DatabaseMigrations` or `migrate:fresh`** in any test. `DatabaseTransactions`
  against `injaz_ai_test`, as established.

---

## §5 — Access

**P12.** The panel reads and writes through `ai_control`, which already holds DML on tables created by
`ai_migrator` in both databases (`infra/postgres/initdb/01-roles.sql:20`). Revision `0005` needs **no
`GRANT`**.
