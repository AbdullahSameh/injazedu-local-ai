# Contract: Attention Metrics — the exact arithmetic behind every number

**Feature**: `specs/006-tg-m3-response-tracking` · **Status**: durable from TG-M3 onwards

Every figure this milestone displays is defined here, once. The panel's SQL is quoted from this file;
so is any later milestone's. The milestone's acceptance is that a number computed by hand from
`attention_items` matches the screen **exactly**, so a second definition anywhere is a defect.

Source: plan §18.1–18.3 and §18.7. All timestamps are stored UTC and rendered `Asia/Riyadh`. All
durations are seconds in the database and human units on screen.

---

## §1 — The window rule

> **In window** always means `opened_at >= :from AND opened_at < :to`.

**M1.** Never `created_at`. A row written today about a question asked yesterday belongs to yesterday.
**M2.** Inclusive at the start, exclusive at the end — so adjacent periods partition without overlap and
moving a boundary by one second moves exactly the items whose questions fall across it.

---

## §2 — First Response Time

```
FRT(item) = first_response_at - opened_at        -- answered items only
```

**M3.** Only `status = 'answered'` contributes. `open`, `expired` and `dismissed` contribute **no
value** — not zero, not infinity, nothing. Counting unanswered items as infinitely slow corrupts the
median; dropping them silently flatters the team. They are reported separately and always alongside
(§3).

```sql
SELECT
  count(*)                                          AS answered,
  percentile_cont(0.5) WITHIN GROUP (ORDER BY frt)  AS median_frt,
  percentile_cont(0.9) WITHIN GROUP (ORDER BY frt)  AS p90_frt,
  max(frt)                                          AS max_frt
FROM (
  SELECT extract(epoch FROM (first_response_at - opened_at)) AS frt
  FROM attention_items
  WHERE status = 'answered'
    AND opened_at >= :from AND opened_at < :to
    AND (:moderator::bigint IS NULL OR responsible_moderator_id = :moderator)
    AND (:chat::bigint      IS NULL OR telegram_chat_id        = :chat)
) s;
```

**M4.** `percentile_cont` — interpolating, not nearest-rank.
**M5.** `answered` is displayed **beside every percentile**, always.
**M6.** `p90_frt` is **suppressed** below `MODERATION_PERCENTILE_MIN_SAMPLES` (default 10), with a
stated reason rather than a number. Measured: four samples `[60, 120, 180, 900]` yield a p90 of `684`,
which looks authoritative and is built from four points.
**M7.** **No average is displayed anywhere.** Source plan §18.1.
**M8.** On zero rows `percentile_cont` returns **NULL, not 0**. The panel renders "no data", never
"0s" — a group nobody asked a question in is not a group answering instantly.

---

## §3 — Unanswered

```sql
SELECT count(*) FILTER (WHERE status IN ('open','expired'))      AS unanswered,
       count(*) FILTER (WHERE status = 'expired')                AS expired,
       count(*) FILTER (WHERE status <> 'dismissed')             AS opened
FROM attention_items
WHERE opened_at >= :from AND opened_at < :to
  AND (:moderator::bigint IS NULL OR responsible_moderator_id = :moderator)
  AND (:chat::bigint      IS NULL OR telegram_chat_id        = :chat);
```

**M9.** Reported as a count **and** as a share of `opened`, never as a bare number. Twelve unanswered
means nothing without whether twelve or twelve hundred were asked.
**M10.** `dismissed` items leave the calculation entirely — out of the numerator and out of the
denominator. They were never real questions.
**M11.** `expired` items stay in the unanswered count **permanently**, and their own count is shown
beside it.

---

## §4 — Oldest still waiting

```sql
SELECT max(now() - opened_at) AS oldest_waiting
FROM attention_items
WHERE status = 'open'
  AND (:chat::bigint IS NULL OR telegram_chat_id = :chat);
```

**M12.** `status = 'open'` **only**. Expired items are excluded so one abandoned question from last week
cannot pin the figure at three days forever; the expired count from §3 is shown beside it.
**M13.** This figure ignores the period window — it is a live statement about now, not a historical one.
**M14.** Computed **server-side on each poll**, never by a browser clock. Client clock skew would make
this number disagree with every other number in the product, and the milestone's whole claim is that it
does not.

---

## §5 — Rule-set accuracy

Source plan §18.7. These are the figures that decide, at TG-M5, whether a model is actually better than
the rules rather than merely newer.

```sql
SELECT
  count(*) FILTER (WHERE source = 'rule')                                 AS rule_opened,
  count(*) FILTER (WHERE source = 'rule' AND status = 'dismissed')        AS rule_dismissed,
  count(*) FILTER (WHERE source = 'operator')                             AS operator_added,
  rule_version
FROM attention_items
WHERE opened_at >= :from AND opened_at < :to
GROUP BY rule_version;
```

```
precision = 1 − rule_dismissed ÷ rule_opened
recall    ≈ rule_opened ÷ (rule_opened + operator_added)
```

**M15.** Grouped by `rule_version`, always. Pooling versions produces a number that describes no rule
set that ever ran.
**M16.** `recall` is an approximation and is labelled as one: it can only see the misses an operator
happened to notice and add. It is a floor, not a measurement.

---

## §6 — What is not computed

**M17.** **No composite score**, for any moderator or any group — source plan §18.6, and excluded from
the whole of v1 rather than deferred. It would be built from roughly five people, a rule set whose
precision §5 has not yet measured, and an attribution gap Telegram makes unresolvable.
**M18.** **No average**, anywhere (M7).
**M19.** **No detection latency** — there is nothing to detect yet; it arrives with incidents at TG-M4.
**M20.** **No incompleteness marker** where a period overlaps an unobserved window. The windows are
recorded already; rendering a report as incomplete over them is TG-M7's. Until then it is a written
limitation, and the smoke test runs in a window the operator knows was observed.
