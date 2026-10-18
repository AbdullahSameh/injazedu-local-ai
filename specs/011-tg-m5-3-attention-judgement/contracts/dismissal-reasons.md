# Contract: Dismissal Reasons and Their Figures (Story 1)

**Feature**: `specs/011-tg-m5-3-attention-judgement` · **Status**: durable from TG-M5.3 onwards. It amends TG-M3's
`control-panel-attention.md` §2 and `attention-metrics.md` §3 and §5. It also amends TG-M5's
`classification-metrics.md` C7 and C9 and `control-panel-classification.md` §4, all as dated notes.

**Deployable alone** (D-TG-182): it reads and writes only `attention_items`, `message_classifications` and
`model_profiles`, which exist today. It needs no revision, no model and no switch.

## §1 — The action

| Action | Kind | Writes |
|---|---|---|
| Dismiss (not a real question) | row | `status='dismissed'`, `close_reason='not_a_question'`, `closed_at`, `closed_by_user_id` *(unchanged)* |
| **Dismiss (member discussion)** | row | as above, `close_reason='member_discussion'` *(new)* |
| Dismiss (message removed) | row | as above, `close_reason='message_removed'` *(unchanged)* |

- **K1.** The new action appears on every open item of the Live Attention Queue, whatever its `source`.
- **K2.** It requires confirmation, and the confirmation states the three meanings:
  - **Not a real question:** not a question or request at all; nothing to answer.
  - **Member discussion:** a real question or discussion between members; no moderator was needed.
  - **Message removed:** your own judgement that the message is gone. Telegram reports no deletion (P7).
- **K3.** It writes through `AttentionItem::closeIfOpen()`, TG-M3 C8's guarded update, so a second dismissal
  updates zero rows. There is no bulk action (P5).
- **K4.** The action is `dismiss_member_discussion`, labelled "Member discussion" in the panel's English chrome.

## §2 — Every existing count is unchanged

- **K5.** Every figure that counts `status = 'dismissed'` keeps counting every reason, with its SQL unchanged:
  - TG-M3 §3 (unanswered, opened; M9–M11);
  - TG-M3 §5 and C7 (precision);
  - C1 (`rule_dismissed` label);
  - C9 (`model_dismissed`, M24, the pilot gate).
- **K6.** M10's rationale is reworded and its SQL is unchanged: *"`dismissed` items leave the calculation
  entirely. None of them needed a moderator's answer: not a real question, a member discussion, or a removed
  message."*

## §3 — The breakdown (additive)

Beside each dismissal count, four columns, computed in the same statement:

```sql
count(*) FILTER (WHERE status = 'dismissed' AND close_reason = 'not_a_question')    AS dismissed_not_a_question,
count(*) FILTER (WHERE status = 'dismissed' AND close_reason = 'member_discussion') AS dismissed_member_discussion,
count(*) FILTER (WHERE status = 'dismissed' AND close_reason = 'message_removed')   AS dismissed_message_removed,
count(*) FILTER (WHERE status = 'dismissed'
                   AND (close_reason IS NULL
                        OR close_reason NOT IN ('not_a_question','member_discussion','message_removed'))) AS dismissed_other
```

- **K7.** On **C7** (TG-M3 §5's statement, which C7 quotes), these are added per `rule_version`, with `source =
  'rule'` added to each filter. The `rule_dismissed` column is unchanged.
- **K8.** On **C9** (`classification-metrics.md` §8a), these are added per opening record, with `ai.` prefixes.
  `model_dismissed` is unchanged. After revision `0008` the same four columns apply to both eras
  (`attention-metrics.md` C9′).
- **K9.** The parts sum to the count: `dismissed_not_a_question + dismissed_member_discussion +
  dismissed_message_removed + dismissed_other = rule_dismissed` (respectively `model_dismissed`). This is tested in
  Python and in PHP.
- **K10.** The breakdown is diagnostic. **M24 stays `model_dismissed ÷ model_opened`** over at least 30 items, at
  most 10%, and no gate reads a breakdown column.

## §4 — Wording

- **K11.** No screen or operator document describes all dismissed items as "not a real question":

| Where | Becomes |
|---|---|
| Classification Accuracy, "Questions the model opened" | "Model-opened, dismissed (any reason): n / N", then "not a real question a · member discussion b · message removed c · other d" |
| Classification Accuracy, rule baseline header | "Rule-dismissed (any reason)", with the same breakdown; the precision cell is unchanged |
| `specs/008-…/contracts/control-panel-classification.md` §4, the TG-M5.1 note | "dismissed (any reason), with its per-reason breakdown · answered · still unanswered" |
| `specs/009-…/quickstart.md` §5 | "the **dismissed (any reason)** ratio is the operational gate; its breakdown says why" |
| `specs/006-…/contracts/attention-metrics.md` M10 | K6 |

- **K12.** Each breakdown part is a count, never a ratio or a percentage (008 A2, M21). A zero-denominator ratio
  still reads "no labelled examples".

## §5 — Dated amendment notes written in 011

- **`specs/006-tg-m3-response-tracking/spec.md` FR-051:** the reasons offered are `not_a_question`,
  `member_discussion` and `message_removed`. FR-051's "at minimum" is met, not changed.
- **`specs/006-…/data-model.md`, the `close_reason` row:** the vocabulary of data-model §5.
- **`specs/006-…/contracts/control-panel-attention.md` §2:** the new row and K2.
- **`specs/006-…/contracts/attention-metrics.md`:** §3 M10 (K6) and §5 (K7).
- **`specs/008-…/contracts/classification-metrics.md`:** C7 (K7) and §8a C9 (K8, K10).
- **`specs/008-…/contracts/control-panel-classification.md` §4:** K11.
- **`specs/009-…/quickstart.md` §5:** K11.

## §5a — Amended 2026-10-18: a fourth reason

From `docs/plan/telegram/tg-day-one-investigation-and-link-rule-plan.md` Step 2, operator decision.

- **The action.** **Dismiss (answered by a member)** (`dismiss_member_answered`, "Answered by a member") writes
  `close_reason='member_answered'` through K3's guarded update, on an open item of any source.
- **K2's confirmation** states four meanings. The new one: *answered by a member*, a real question another
  member answered well enough, so no moderator answer was needed.
- **§3 gains `dismissed_member_answered`** beside `dismissed_member_discussion`, in C7 and in both eras of C9′.
  `dismissed_other` excludes it. K9 now has five parts. K5, K10 and N1–N4 are unchanged.
- **The page prints** "not a real question a · member discussion b · answered by a member c · message removed d
  · other e".
- **The row actions now sit in one dropdown** (006 `control-panel-attention.md` §2 amendment, same date).

## §6 — What may never happen

- **N1.** A changed value for any existing dismissal-based figure on the same rows.
- **N2.** A breakdown whose parts do not sum to its count.
- **N3.** A gate, threshold or verdict reading a breakdown column.
- **N4.** A bulk dismissal, or a dismissal that reopens or re-dates an item.
