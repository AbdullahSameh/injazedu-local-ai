# Contract: Attention Judgement Figures

**Feature**: `specs/011-tg-m5-3-attention-judgement` · **Status**: durable from TG-M5.3 onwards. It amends TG-M5's
`classification-metrics.md` §8a (C9) and adds C10. Every rule of `classification-metrics.md` §1 still applies:
- selection by posting time (K1) and the half-open period;
- one row per model and instruction, never pooled (K3);
- no average, no composite score and no percentage;
- "no data" is not zero (M21–M22).

The panel runs this SQL verbatim and computes nothing else (spec FR-337).

`:gap_s` is `MODERATION_BURST_GAP_S`. The panel reads it through `config('moderation.burst_gap_s')`, default 90.

## §1 — C9′: questions the model opened, both eras

```sql
SELECT 'classification' AS era, c.model_profile_id, c.prompt_version, c.taxonomy_version,
       count(*)                                                AS model_opened,
       count(*) FILTER (WHERE ai.status = 'dismissed')         AS model_dismissed,
       count(*) FILTER (WHERE ai.status <> 'dismissed')        AS model_kept,
       count(*) FILTER (WHERE ai.status = 'answered')          AS model_answered,
       count(*) FILTER (WHERE ai.status IN ('open','expired')) AS model_unanswered
       -- + the four breakdown columns of dismissal-reasons.md §3, on ai.status / ai.close_reason
FROM attention_items ai
JOIN message_classifications c ON c.id = ai.message_classification_id
WHERE ai.source = 'ai'
  AND ai.opened_at >= :period_from AND ai.opened_at < :period_to
  AND (:chat_id IS NULL OR ai.telegram_chat_id = :chat_id)
GROUP BY 1, 2, 3, 4
UNION ALL
SELECT 'attention', j.model_profile_id, j.prompt_version, NULL::smallint,
       count(*),
       count(*) FILTER (WHERE ai.status = 'dismissed'),
       count(*) FILTER (WHERE ai.status <> 'dismissed'),
       count(*) FILTER (WHERE ai.status = 'answered'),
       count(*) FILTER (WHERE ai.status IN ('open','expired'))
       -- + the same four breakdown columns
FROM attention_items ai
JOIN message_attention_judgements j ON j.id = ai.attention_judgement_id
WHERE ai.source = 'ai'
  AND ai.opened_at >= :period_from AND ai.opened_at < :period_to
  AND (:chat_id IS NULL OR ai.telegram_chat_id = :chat_id)
GROUP BY 1, 2, 3, 4;
```

- **M23′.** Each item is grouped by the record that opened it:
  - a TG-M5.1 item by its prediction's model, instruction and vocabulary;
  - a TG-M5.3 item by its judgement's model and attention instruction.

  The two eras are never pooled.
- **M24 is unchanged:** `model_dismissed ÷ model_opened` per row is the pilot's gate. The TG-M5.3 pilot reads the
  `attention` rows.
- **M19 is unchanged:** "Model-opened and kept" beside the rule baseline is the count of `model_kept` across all
  rows. It is a count, not a ratio, so summing rows pools no rate.

## §2 — C10: the attention judgement's coverage, intents, timeliness and misses

### C10a — What happened to every message (never grouped by model, like C5)

```sql
SELECT count(*) AS messages,
       count(*) FILTER (WHERE j.id IS NOT NULL)                                   AS judged,
       count(*) FILTER (WHERE j.id IS NULL AND x.id IS NOT NULL)                  AS excluded,
       count(*) FILTER (WHERE j.id IS NULL AND x.id IS NULL AND f.id IS NOT NULL) AS failed,
       count(*) FILTER (WHERE j.id IS NULL AND x.id IS NULL AND f.id IS NULL)     AS not_judged_yet
FROM telegram_messages m
LEFT JOIN message_attention_judgements j ON j.telegram_chat_id = m.telegram_chat_id
                                        AND j.telegram_message_id = m.message_id AND j.is_current
LEFT JOIN message_attention_attempts x ON x.telegram_chat_id = m.telegram_chat_id
                                      AND x.telegram_message_id = m.message_id AND x.outcome = 'excluded'
LEFT JOIN LATERAL (SELECT a.id FROM message_attention_attempts a
                   WHERE a.telegram_chat_id = m.telegram_chat_id AND a.telegram_message_id = m.message_id
                     AND a.outcome = 'failed'
                   ORDER BY a.created_at DESC, a.id DESC LIMIT 1) f ON true
WHERE m.sent_at >= :period_from AND m.sent_at < :period_to
  AND (:chat_id IS NULL OR m.telegram_chat_id = :chat_id);
```

- **M26.** The four outcomes partition the messages. The breakdowns are by `reason`: exclusions, including
  `rule_opens`, and the **latest** failure, as 008 M15.
- **M27.** Messages sent before the attention instruction was configured stay "not judged yet". There is no
  catch-up (FR-317), so the period chosen decides what this means. The page says so.

### C10b — Judgements by intent, and timeliness (per model and attention instruction)

```sql
SELECT j.model_profile_id, j.prompt_version,
       count(*)                                          AS judged,
       count(*) FILTER (WHERE j.intent = 'asking')       AS asking,
       count(*) FILTER (WHERE j.intent = 'discussion')   AS discussion,
       count(*) FILTER (WHERE j.intent = 'informing')    AS informing,
       count(*) FILTER (WHERE j.intent = 'social')       AS social,
       count(*) FILTER (WHERE j.intent = 'offering')     AS offering,
       count(*) FILTER (WHERE j.intent = 'other')        AS other,
       count(*) FILTER (WHERE j.created_at <= m.sent_at + make_interval(secs => :gap_s)) AS on_time
FROM message_attention_judgements j
JOIN telegram_messages m ON m.telegram_chat_id = j.telegram_chat_id AND m.message_id = j.telegram_message_id
WHERE j.is_current AND j.path = 'live'
  AND m.sent_at >= :period_from AND m.sent_at < :period_to
  AND (:chat_id IS NULL OR m.telegram_chat_id = :chat_id)
GROUP BY 1, 2;
```

- **M28.** `on_time` is a judgement recorded no later than its message's own delayed judgement
  (`sent_at + gap`), which is Case A. It is shown as `on_time / judged`. SC-306 reads it.
- **M29.** The intent counts are counts. `asking` is not "questions": a rule-opened member is AE2-skipped, so most
  rule-signalled questions never appear here. The page says so.

### C10c — The misses a person noticed: operator-added items, by anchor status and burst size

```sql
SELECT CASE WHEN j.id IS NOT NULL AND j.needs_response THEN 'judged_asking'
            WHEN j.id IS NOT NULL                      THEN 'judged_' || j.intent
            WHEN x.id IS NOT NULL                      THEN 'excluded_' || x.reason
            WHEN f.id IS NOT NULL                      THEN 'failed'
            ELSE 'none' END                                                  AS anchor_status,
       EXISTS (SELECT 1 FROM telegram_messages n
               WHERE n.telegram_chat_id = m.telegram_chat_id
                 AND n.telegram_user_id = m.telegram_user_id
                 AND n.message_thread_id IS NOT DISTINCT FROM m.message_thread_id
                 AND n.message_id <> m.message_id
                 AND n.sent_at BETWEEN m.sent_at - make_interval(secs => :gap_s)
                                   AND m.sent_at + make_interval(secs => :gap_s)) AS multi_message,
       count(*)                                                              AS items
FROM attention_items ai
JOIN telegram_messages m ON m.telegram_chat_id = ai.telegram_chat_id AND m.message_id = ai.telegram_message_id
LEFT JOIN message_attention_judgements j ON j.telegram_chat_id = m.telegram_chat_id
                                        AND j.telegram_message_id = m.message_id AND j.is_current
LEFT JOIN message_attention_attempts x ON x.telegram_chat_id = m.telegram_chat_id
                                      AND x.telegram_message_id = m.message_id AND x.outcome = 'excluded'
LEFT JOIN LATERAL (SELECT a.id FROM message_attention_attempts a
                   WHERE a.telegram_chat_id = m.telegram_chat_id AND a.telegram_message_id = m.message_id
                     AND a.outcome = 'failed'
                   ORDER BY a.created_at DESC, a.id DESC LIMIT 1) f ON true
WHERE ai.source = 'operator'
  AND ai.opened_at >= :period_from AND ai.opened_at < :period_to
  AND (:chat_id IS NULL OR ai.telegram_chat_id = :chat_id)
GROUP BY 1, 2;
```

- **M30.** `multi_message` is exact. Under TG-M3 §1, every member of a burst of two or more has a same-sender,
  same-thread neighbour within the gap, and a message with such a neighbour shares its burst. A `sender_chat`
  message, which has no `telegram_user_id`, is never multi-message.
- **M31.** This is L-B1's pilot measure. The operator reviews the `multi_message` rows by hand and records which
  were distributed intent in the pilot notes. No automatic "every member non-asking" count is computed; that
  would need bursts rebuilt in SQL (plan §3a).
- **M32.** `judged_asking` on an operator-added item means the model said `asking` but no model item opened. The
  cause is a blank switch, V, the window (G5–G6), or a burst already covered. It is reported, not explained.

## §3 — Where it shows

On the Classification Accuracy page:
- **"Attention judgements: what happened to every message":** C10a, and C10c beneath it.
- **One "Attention judgement" block per `(model, attention instruction)`:**
  - C9′'s `attention` row, with its breakdown;
  - C10b.
- **The classification blocks** keep C9′'s `classification` rows.

Every ratio is `n / N`. A zero denominator reads "no labelled examples" (M21). A model with no judgements has no
block (M22).

## §4 — Verified by

- **Python:** `tests/moderation/attention_judgement/test_metrics_attention.py` loads one hand-computed scenario
  and asserts every figure above, including the sum-of-parts of the breakdown.
- **PHP:** `AttentionJudgementFiguresTest.php` and the amended `ModelOpenedQuestionsTest.php` assert the same
  numbers through the page.
