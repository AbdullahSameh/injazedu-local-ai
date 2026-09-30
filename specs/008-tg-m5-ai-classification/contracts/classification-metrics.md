# Contract: Classification Figures

**Feature**: `specs/008-tg-m5-ai-classification` · **Status**: durable from TG-M5 onwards — TG-M7 arranges
these figures on its dashboards and TG-M8 adds human verdicts beside them; neither redefines them.

The exact SQL behind every figure on the Classification Accuracy page, the possible-violations list and the
model's label on the queue — quoted verbatim by `app/application/moderation/metrics.py` and
`App\Filament\Pages\Concerns\ClassificationMetrics`, defined nowhere else (FR-050, D-TG-156). All eight
statements below (C1–C8) were extracted from this file and run verbatim — parameters substituted as literals —
over research probe 10's scenario in `injaz_ai_test`, inside `BEGIN … ROLLBACK`, and matched hand computation
(C8's operator p90 over 30 s, 120 s, 180 s interpolates to 168 s, as `percentile_cont` should).

**What these figures are.** An *estimate* of how the model's judgements compare with the human labels already
recorded — never a measured accuracy. The human labels are few, not random, and after this milestone not fully
independent of the model (the labels are on screen). Every ratio is shown with its numerator and denominator;
no bare percentage, no average of anything, no combined score (FR-047, FR-049).

---

## §1 — Selection and grouping

- **K1.** A period selects by the **platform send time** of the message a figure is about — `attention_items.opened_at`
  and `moderation_incidents.opened_at` are both that time by construction — inclusive at `:period_from`,
  exclusive at `:period_to` (FR-048). Never `created_at`, never `detected_at`.
- **K2.** `:chat_id` is a `telegram_chats.id` or NULL for every measured group.
- **K3.** Every model figure is grouped by `(model_profile_id, prompt_version, taxonomy_version)` and **never
  pooled** across them (FR-046, SC-012). A number that mixes two models describes no model that ever ran.
- **K4.** Only **current** predictions count (`is_current`) — the only kind that exists in this milestone.
- **K5.** Catch-up predictions count exactly like live ones: the comparison is what they exist for.

---

## §2 — C1: questions the humans labelled

```sql
WITH items AS (
  SELECT ai.id, ai.telegram_chat_id, ai.telegram_message_id,
         CASE WHEN ai.source = 'rule' AND ai.status <> 'dismissed' THEN 'rule_kept'
              WHEN ai.source = 'rule'                             THEN 'rule_dismissed'
              ELSE 'operator_added' END AS label
  FROM attention_items ai
  WHERE ai.source IN ('rule','operator')
    AND ai.opened_at >= :period_from AND ai.opened_at < :period_to
    AND (:chat_id IS NULL OR ai.telegram_chat_id = :chat_id)
), judged AS (
  SELECT i.id, i.label, c.model_profile_id, c.prompt_version, c.taxonomy_version,
         bool_or(c.needs_response) AS any_needs_response
  FROM items i
  JOIN telegram_messages m ON m.telegram_chat_id = i.telegram_chat_id
                          AND (m.attention_item_id = i.id OR m.message_id = i.telegram_message_id)
  JOIN message_classifications c ON c.telegram_chat_id = m.telegram_chat_id
                                AND c.telegram_message_id = m.message_id AND c.is_current
  GROUP BY 1, 2, 3, 4, 5
)
SELECT model_profile_id, prompt_version, taxonomy_version, label,
       count(*) AS classified, count(*) FILTER (WHERE any_needs_response) AS judged_needs_response
FROM judged GROUP BY 1, 2, 3, 4;
```

- **M1.** An item's messages are its anchor plus every message its burst linked to it
  (`telegram_messages.attention_item_id`). The model judged the item as needing an answer when **any** of them was
  judged so — the rule set's own "at least one message carries a question signal" (the spec's first edge case).
- **M2.** The three labels are the human labels TG-M3 recorded: *rule-kept* (the rules opened it and nobody
  dismissed it — TG-M3's precision treats these as correct), *rule-dismissed* (an operator said the rules were
  wrong), *operator-added* (the rules missed it).
- **M3.** Read as: of rule-kept, how many the model agrees need an answer; of rule-dismissed, how many the model
  would also have wrongly flagged; of operator-added, how many rule misses the model caught.
- **M4.** `classified` is the denominator. Items with no prediction from a given model are not in its row; the
  page shows, per label, how many items no model classified.

## §3 — C2: model-only judgements, unverified

```sql
SELECT c.model_profile_id, c.prompt_version, c.taxonomy_version, count(*) AS unverified_needs_response
FROM message_classifications c
JOIN telegram_messages m ON m.telegram_chat_id = c.telegram_chat_id AND m.message_id = c.telegram_message_id
WHERE c.is_current AND c.needs_response
  AND m.sent_at >= :period_from AND m.sent_at < :period_to
  AND (:chat_id IS NULL OR m.telegram_chat_id = :chat_id)
  AND m.attention_item_id IS NULL
  AND NOT EXISTS (SELECT 1 FROM attention_items a
                  WHERE a.telegram_chat_id = m.telegram_chat_id AND a.telegram_message_id = m.message_id)
GROUP BY 1, 2, 3;
```

- **M5.** Messages the model says need an answer where no question item exists and so no human label exists. They
  are **unverified** — never counted as right and never as wrong (FR-046). The operator turns one into a label by
  adding the question by hand (TG-M3's action), after which it moves into C1's *operator-added*.

## §4 — C3: violations the humans labelled, and the model's own incidents

```sql
WITH inc AS (
  SELECT i.*, s.status
  FROM moderation_incidents i JOIN moderation_incident_state s ON s.incident_id = i.id
  WHERE i.opened_at >= :period_from AND i.opened_at < :period_to
    AND (:chat_id IS NULL OR i.telegram_chat_id = :chat_id)
)
SELECT c.model_profile_id, c.prompt_version, c.taxonomy_version,
  count(*) FILTER (WHERE inc.source = 'operator' AND inc.prompted_by_classification_id IS NULL)                                     AS indep_flags,
  count(*) FILTER (WHERE inc.source = 'operator' AND inc.prompted_by_classification_id IS NULL AND c.needs_moderation)              AS indep_agreed,
  count(*) FILTER (WHERE inc.source = 'operator' AND inc.prompted_by_classification_id IS NULL AND c.needs_moderation
                     AND c.category = inc.category)                                                                                 AS indep_same_cat,
  count(*) FILTER (WHERE inc.source = 'operator' AND inc.prompted_by_classification_id IS NOT NULL)                                 AS prompted_flags,
  count(*) FILTER (WHERE inc.source = 'operator' AND inc.prompted_by_classification_id IS NOT NULL AND c.needs_moderation)          AS prompted_agreed,
  count(*) FILTER (WHERE inc.source = 'operator' AND inc.prompted_by_classification_id IS NOT NULL AND c.needs_moderation
                     AND c.category = inc.category)                                                                                 AS prompted_same_cat,
  count(*) FILTER (WHERE inc.status = 'closed_false_positive')                                                                      AS fp_closures,
  count(*) FILTER (WHERE inc.status = 'closed_false_positive' AND c.needs_moderation)                                              AS fp_model_raised,
  count(*) FILTER (WHERE inc.source = 'ai')                                                                                         AS model_opened,
  count(*) FILTER (WHERE inc.source = 'ai' AND inc.status = 'closed_false_positive')                                                AS model_opened_fp
FROM inc
JOIN message_classifications c ON c.telegram_chat_id = inc.telegram_chat_id
                              AND c.telegram_message_id = inc.telegram_message_id AND c.is_current
GROUP BY 1, 2, 3;
```

- **M6.** *Independent* operator flags and *list-prompted* ones are reported apart (FR-044, FR-046): a flag the
  model prompted is not the operator independently agreeing with it. Only the independent row is evidence of
  agreement.
- **M7.** Category agreement is counted **among** the flags the model agreed need moderation — "of those, how many
  it gave the same category" (FR-046).
- **M8.** `fp_closures` spans every source: of the flags that proved wrong, how many the model would have raised.
- **M9.** `model_opened_fp` over `model_opened` is the model's **incident false-positive count** — the figure that
  Finding 2 makes the real control on automatic opening. Read it after a week, with its denominator.
- **M10.** A model-opened incident is joined through its message, which is the same prediction as its
  `message_classification_id` — one current prediction per message.
- **M11.** Status comes from `moderation_incident_state`, never computed (TG-M4 N6).

## §5 — C4: the possible-violations list

```sql
SELECT c.id, c.telegram_chat_id, c.telegram_message_id, m.sent_at, m.original_text,
       c.category, c.severity, c.confidence, c.route_reason, p.name AS model, c.prompt_version, c.created_at
FROM message_classifications c
JOIN telegram_messages m ON m.telegram_chat_id = c.telegram_chat_id AND m.message_id = c.telegram_message_id
JOIN model_profiles p    ON p.id = c.model_profile_id
WHERE c.is_current AND c.route = 'possible_violation'
  AND NOT EXISTS (SELECT 1 FROM moderation_incidents i
                  WHERE i.telegram_chat_id = c.telegram_chat_id AND i.telegram_message_id = c.telegram_message_id)
  AND m.sent_at >= :period_from AND m.sent_at < :period_to
  AND (:chat_id IS NULL OR c.telegram_chat_id = :chat_id)
ORDER BY m.sent_at DESC;
```

- **M12.** Membership is **read, never stored** (FR-042): an entry leaves the list the moment its message anchors an
  incident, whoever opened it. Catch-up predictions never appear (`route = 'measurement_only'`).
- **M13.** Its count, per model, is also shown on the accuracy page as "listed now".

## §6 — C5: what happened to every message

```sql
SELECT count(*) AS messages,
       count(*) FILTER (WHERE c.id IS NOT NULL)                                   AS classified,
       count(*) FILTER (WHERE c.id IS NULL AND x.id IS NOT NULL)                  AS excluded,
       count(*) FILTER (WHERE c.id IS NULL AND x.id IS NULL AND f.id IS NOT NULL) AS failed,
       count(*) FILTER (WHERE c.id IS NULL AND x.id IS NULL AND f.id IS NULL)     AS not_classified_yet
FROM telegram_messages m
LEFT JOIN message_classifications c ON c.telegram_chat_id = m.telegram_chat_id
                                   AND c.telegram_message_id = m.message_id AND c.is_current
LEFT JOIN message_classification_attempts x ON x.telegram_chat_id = m.telegram_chat_id
                                           AND x.telegram_message_id = m.message_id AND x.outcome = 'excluded'
LEFT JOIN LATERAL (SELECT a.id FROM message_classification_attempts a
                   WHERE a.telegram_chat_id = m.telegram_chat_id AND a.telegram_message_id = m.message_id
                     AND a.outcome = 'failed'
                   ORDER BY a.created_at DESC, a.id DESC LIMIT 1) f ON true
WHERE m.sent_at >= :period_from AND m.sent_at < :period_to
  AND (:chat_id IS NULL OR m.telegram_chat_id = :chat_id);
```

- **M14.** The four outcomes partition the messages: `messages = classified + excluded + failed +
  not_classified_yet` (probe 10: 14 = 11 + 1 + 1 + 1). The precedence is `data-model.md` §3's.
- **M15.** The breakdowns — exclusions by `reason`, failures by the **latest** failure's `reason` — are the same
  joins grouped by reason (FR-051).
- **M16.** A single message's status on any screen is this precedence applied to one message (FR-055).

## §7 — C6: the model's label on a waiting question

```sql
SELECT DISTINCT ON (ai.id) ai.id AS item_id, m.message_id AS labelled_message, c.category, c.confidence
FROM attention_items ai
JOIN telegram_messages m ON m.telegram_chat_id = ai.telegram_chat_id
                        AND (m.attention_item_id = ai.id OR m.message_id = ai.telegram_message_id)
JOIN message_classifications c ON c.telegram_chat_id = m.telegram_chat_id
                              AND c.telegram_message_id = m.message_id AND c.is_current
WHERE ai.id = ANY(:item_ids)
ORDER BY ai.id, c.needs_response DESC, m.sent_at, m.message_id;
```

- **M17.** The label shown is the earliest of the item's messages the model judged to need an answer; if none,
  the earliest classified message. A greeting that anchors a burst does not hide the question after it (probe 10).
- **M18.** An item none of whose messages is classified shows C5's status of its anchor.

## §8 — C7: the rule set's baseline, and C8: detection latency by opener

**C7** is TG-M3's `attention-metrics.md` §5 statement **verbatim**, with `AND (:chat_id IS NULL OR
telegram_chat_id = :chat_id)` added — the baseline the model is compared against, on its own definitions:

```sql
SELECT count(*) FILTER (WHERE source = 'rule')                          AS rule_opened,
       count(*) FILTER (WHERE source = 'rule' AND status = 'dismissed') AS rule_dismissed,
       count(*) FILTER (WHERE source = 'operator')                      AS operator_added,
       rule_version
FROM attention_items
WHERE opened_at >= :period_from AND opened_at < :period_to
  AND (:chat_id IS NULL OR telegram_chat_id = :chat_id)
GROUP BY rule_version;
```

- **M19.** Grouped by `rule_version`, operator additions arrive in their **own** row, where `rule_version` is NULL
  (probe 10). Precision is per rule-version row: `1 − rule_dismissed ÷ rule_opened`. Recall uses the NULL row's
  `operator_added`: `rule_opened ÷ (rule_opened + operator_added)`, labelled — as TG-M3's M16 says — a floor, not a
  measurement. The statement is not changed; the page reads it as it is.

**C8** is TG-M4's `incident-metrics.md` §4 statement with `i.source` selected and grouped (D-TG-159, FR-037):

```sql
SELECT i.source,
       count(*)                                                         AS flagged,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY lat)                 AS latency_median,
       percentile_cont(0.9) WITHIN GROUP (ORDER BY lat)                 AS latency_p90,
       max(lat)                                                         AS latency_max
FROM (
  SELECT i.source, extract(epoch FROM i.detected_at - i.opened_at) AS lat
  FROM moderation_incidents i
  WHERE i.detected_at >= :period_from AND i.detected_at < :period_to
    AND (:chat_id IS NULL OR i.telegram_chat_id = :chat_id)
) i
GROUP BY i.source;
```

- **M20.** Unchanged from TG-M4 in every other respect: no moderator parameter (M16), false positives included
  (M17), p90 suppressed below `MODERATION_PERCENTILE_MIN_SAMPLES` on each row's own `flagged`. It selects by
  `detected_at` — it is TG-M4's figure, not a classification figure, and K1 does not apply to it. The model's row
  is the model's own delay; the operator's row is the operator's.

## §9 — "No data" is not zero

- **M21.** A ratio whose denominator is 0 renders "no labelled examples", never `0/0` or `0%`.
- **M22.** A model with no predictions in the period has no row — the page says so, rather than printing zeros.

## §10 — Verified by

`tests/moderation/classification/test_metrics.py` loads probe 10's fixed scenario — fourteen messages, two models,
three question items, four incidents — and asserts every figure above against the hand-computed values recorded in
research §1, including the never-pooled rows, the list-prompted split, the partition of M14 and C6's label choice.
`ClassificationMetricsTest.php` asserts the page renders the same numbers, with their denominators, and no average.
