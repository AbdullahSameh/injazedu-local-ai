<?php

namespace App\Filament\Pages\Concerns;

use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;

/**
 * The exact SQL behind every classification figure
 * (`specs/008-tg-m5-ai-classification/contracts/classification-metrics.md`), quoted here once for
 * the panel — the same arithmetic `apps/ai-api/app/application/moderation/metrics.py` runs on the
 * Python side (D-TG-156). Neither side re-expresses the other's definition; a changed figure
 * changes this file and that one, never a third — **no arithmetic is invented here**, every
 * method is a direct reading of the contract's own query.
 *
 * US5 (T061) adds C4, the Possible Violations page's own list; US6 (T068) adds C1, C2, C3, C5
 * (plus M15's by-reason breakdowns), C6 and C7 for the Classification Accuracy page.
 */
trait ClassificationMetrics
{
    /**
     * C4: live predictions routed `possible_violation` whose message anchors no incident —
     * membership is read, never stored (M12): a row leaves the list the moment its message
     * anchors an incident, whoever opened it. Catch-up predictions never appear
     * (`route = 'measurement_only'` never matches `route = 'possible_violation'`). Newest posting
     * first (`control-panel-classification.md` §3 V1).
     *
     * @return array<int, object>
     */
    private function possibleViolations(?int $chatId, Carbon $from, Carbon $to): array
    {
        return DB::select(
            <<<'SQL'
            SELECT c.id, c.telegram_chat_id, c.telegram_message_id, m.sent_at, m.original_text,
                   c.category, c.severity, c.confidence, c.route_reason, p.name AS model,
                   c.prompt_version, c.created_at
            FROM message_classifications c
            JOIN telegram_messages m ON m.telegram_chat_id = c.telegram_chat_id
                                    AND m.message_id = c.telegram_message_id
            JOIN model_profiles p    ON p.id = c.model_profile_id
            WHERE c.is_current AND c.route = 'possible_violation'
              AND NOT EXISTS (SELECT 1 FROM moderation_incidents i
                              WHERE i.telegram_chat_id = c.telegram_chat_id
                                AND i.telegram_message_id = c.telegram_message_id)
              AND m.sent_at >= :period_from AND m.sent_at < :period_to
              AND (:chat_id1::bigint IS NULL OR c.telegram_chat_id = :chat_id2::bigint)
            ORDER BY m.sent_at DESC
            SQL,
            [
                'period_from' => $from,
                'period_to' => $to,
                'chat_id1' => $chatId,
                'chat_id2' => $chatId,
            ],
        );
    }

    /**
     * C1: questions the humans labelled — one row per `(model, prompt_version, taxonomy_version,
     * label)`. `classified` is always the denominator (M4); a model that never classified any of
     * an item's messages has no row for that item at all.
     *
     * @return array<int, object>
     */
    private function classificationQuestionStats(?int $chatId, Carbon $from, Carbon $to): array
    {
        return DB::select(
            <<<'SQL'
            WITH items AS (
              SELECT ai.id, ai.telegram_chat_id, ai.telegram_message_id,
                     CASE WHEN ai.source = 'rule' AND ai.status <> 'dismissed' THEN 'rule_kept'
                          WHEN ai.source = 'rule'                             THEN 'rule_dismissed'
                          ELSE 'operator_added' END AS label
              FROM attention_items ai
              WHERE ai.source IN ('rule','operator')
                AND ai.opened_at >= :period_from AND ai.opened_at < :period_to
                AND (:chat_id1::bigint IS NULL OR ai.telegram_chat_id = :chat_id2::bigint)
            ), judged AS (
              SELECT i.id, i.label, c.model_profile_id, c.prompt_version, c.taxonomy_version,
                     bool_or(c.needs_response) AS any_needs_response
              FROM items i
              JOIN telegram_messages m
                ON m.telegram_chat_id = i.telegram_chat_id
               AND (m.attention_item_id = i.id OR m.message_id = i.telegram_message_id)
              JOIN message_classifications c
                ON c.telegram_chat_id = m.telegram_chat_id
               AND c.telegram_message_id = m.message_id AND c.is_current
              GROUP BY 1, 2, 3, 4, 5
            )
            SELECT model_profile_id, prompt_version, taxonomy_version, label,
                   count(*) AS classified,
                   count(*) FILTER (WHERE any_needs_response) AS judged_needs_response
            FROM judged GROUP BY 1, 2, 3, 4
            SQL,
            [
                'period_from' => $from,
                'period_to' => $to,
                'chat_id1' => $chatId,
                'chat_id2' => $chatId,
            ],
        );
    }

    /**
     * C2: model-only judgements, unverified — one row per model, never pooled (K3). M5: a message
     * the model says needs an answer where no question item exists at all — never counted as
     * right and never as wrong.
     *
     * @return array<int, object>
     */
    private function classificationUnverifiedStats(?int $chatId, Carbon $from, Carbon $to): array
    {
        return DB::select(
            <<<'SQL'
            SELECT c.model_profile_id, c.prompt_version, c.taxonomy_version,
                   count(*) AS unverified_needs_response
            FROM message_classifications c
            JOIN telegram_messages m
              ON m.telegram_chat_id = c.telegram_chat_id AND m.message_id = c.telegram_message_id
            WHERE c.is_current AND c.needs_response
              AND m.sent_at >= :period_from AND m.sent_at < :period_to
              AND (:chat_id1::bigint IS NULL OR m.telegram_chat_id = :chat_id2::bigint)
              AND m.attention_item_id IS NULL
              AND NOT EXISTS (
                SELECT 1 FROM attention_items a
                WHERE a.telegram_chat_id = m.telegram_chat_id AND a.telegram_message_id = m.message_id
              )
            GROUP BY 1, 2, 3
            SQL,
            [
                'period_from' => $from,
                'period_to' => $to,
                'chat_id1' => $chatId,
                'chat_id2' => $chatId,
            ],
        );
    }

    /**
     * C3: violations the humans labelled, and the model's own incidents — one row per model. M6:
     * independent and list-prompted flags reported apart; M9: `model_opened_fp` over
     * `model_opened` is the model's incident false-positive count (Finding 2's real control).
     *
     * @return array<int, object>
     */
    private function classificationViolationStats(?int $chatId, Carbon $from, Carbon $to): array
    {
        return DB::select(
            <<<'SQL'
            WITH inc AS (
              SELECT i.*, s.status
              FROM moderation_incidents i JOIN moderation_incident_state s ON s.incident_id = i.id
              WHERE i.opened_at >= :period_from AND i.opened_at < :period_to
                AND (:chat_id1::bigint IS NULL OR i.telegram_chat_id = :chat_id2::bigint)
            )
            SELECT c.model_profile_id, c.prompt_version, c.taxonomy_version,
              count(*) FILTER (
                WHERE inc.source = 'operator' AND inc.prompted_by_classification_id IS NULL
              ) AS indep_flags,
              count(*) FILTER (
                WHERE inc.source = 'operator' AND inc.prompted_by_classification_id IS NULL
                  AND c.needs_moderation
              ) AS indep_agreed,
              count(*) FILTER (
                WHERE inc.source = 'operator' AND inc.prompted_by_classification_id IS NULL
                  AND c.needs_moderation AND c.category = inc.category
              ) AS indep_same_cat,
              count(*) FILTER (
                WHERE inc.source = 'operator' AND inc.prompted_by_classification_id IS NOT NULL
              ) AS prompted_flags,
              count(*) FILTER (
                WHERE inc.source = 'operator' AND inc.prompted_by_classification_id IS NOT NULL
                  AND c.needs_moderation
              ) AS prompted_agreed,
              count(*) FILTER (
                WHERE inc.source = 'operator' AND inc.prompted_by_classification_id IS NOT NULL
                  AND c.needs_moderation AND c.category = inc.category
              ) AS prompted_same_cat,
              count(*) FILTER (WHERE inc.status = 'closed_false_positive') AS fp_closures,
              count(*) FILTER (
                WHERE inc.status = 'closed_false_positive' AND c.needs_moderation
              ) AS fp_model_raised,
              count(*) FILTER (WHERE inc.source = 'ai') AS model_opened,
              count(*) FILTER (
                WHERE inc.source = 'ai' AND inc.status = 'closed_false_positive'
              ) AS model_opened_fp
            FROM inc
            JOIN message_classifications c
              ON c.telegram_chat_id = inc.telegram_chat_id
             AND c.telegram_message_id = inc.telegram_message_id AND c.is_current
            GROUP BY 1, 2, 3
            SQL,
            [
                'period_from' => $from,
                'period_to' => $to,
                'chat_id1' => $chatId,
                'chat_id2' => $chatId,
            ],
        );
    }

    /**
     * C5: what happened to every message — `messages == classified + excluded + failed +
     * not_classified_yet`, always (M14, probe 10: 14 = 11 + 1 + 1 + 1).
     */
    private function classificationVolumeStats(?int $chatId, Carbon $from, Carbon $to): array
    {
        $row = DB::selectOne(
            <<<'SQL'
            SELECT count(*) AS messages,
                   count(*) FILTER (WHERE c.id IS NOT NULL) AS classified,
                   count(*) FILTER (WHERE c.id IS NULL AND x.id IS NOT NULL) AS excluded,
                   count(*) FILTER (
                     WHERE c.id IS NULL AND x.id IS NULL AND f.id IS NOT NULL
                   ) AS failed,
                   count(*) FILTER (
                     WHERE c.id IS NULL AND x.id IS NULL AND f.id IS NULL
                   ) AS not_classified_yet
            FROM telegram_messages m
            LEFT JOIN message_classifications c
              ON c.telegram_chat_id = m.telegram_chat_id
             AND c.telegram_message_id = m.message_id AND c.is_current
            LEFT JOIN message_classification_attempts x
              ON x.telegram_chat_id = m.telegram_chat_id
             AND x.telegram_message_id = m.message_id AND x.outcome = 'excluded'
            LEFT JOIN LATERAL (
              SELECT a.id FROM message_classification_attempts a
              WHERE a.telegram_chat_id = m.telegram_chat_id AND a.telegram_message_id = m.message_id
                AND a.outcome = 'failed'
              ORDER BY a.created_at DESC, a.id DESC LIMIT 1
            ) f ON true
            WHERE m.sent_at >= :period_from AND m.sent_at < :period_to
              AND (:chat_id1::bigint IS NULL OR m.telegram_chat_id = :chat_id2::bigint)
            SQL,
            [
                'period_from' => $from,
                'period_to' => $to,
                'chat_id1' => $chatId,
                'chat_id2' => $chatId,
            ],
        );

        $excludedByReason = DB::select(
            <<<'SQL'
            SELECT x.reason, count(*) AS n
            FROM message_classification_attempts x
            JOIN telegram_messages m
              ON m.telegram_chat_id = x.telegram_chat_id AND m.message_id = x.telegram_message_id
            WHERE x.outcome = 'excluded'
              AND m.sent_at >= :period_from AND m.sent_at < :period_to
              AND (:chat_id1::bigint IS NULL OR m.telegram_chat_id = :chat_id2::bigint)
            GROUP BY x.reason
            SQL,
            [
                'period_from' => $from,
                'period_to' => $to,
                'chat_id1' => $chatId,
                'chat_id2' => $chatId,
            ],
        );

        $failedByReason = DB::select(
            <<<'SQL'
            SELECT f.reason, count(*) AS n
            FROM telegram_messages m
            JOIN LATERAL (
              SELECT a.reason FROM message_classification_attempts a
              WHERE a.telegram_chat_id = m.telegram_chat_id AND a.telegram_message_id = m.message_id
                AND a.outcome = 'failed'
              ORDER BY a.created_at DESC, a.id DESC LIMIT 1
            ) f ON true
            WHERE NOT EXISTS (
                SELECT 1 FROM message_classifications c
                WHERE c.telegram_chat_id = m.telegram_chat_id
                  AND c.telegram_message_id = m.message_id AND c.is_current
              )
              AND NOT EXISTS (
                SELECT 1 FROM message_classification_attempts x
                WHERE x.telegram_chat_id = m.telegram_chat_id
                  AND x.telegram_message_id = m.message_id AND x.outcome = 'excluded'
              )
              AND m.sent_at >= :period_from AND m.sent_at < :period_to
              AND (:chat_id1::bigint IS NULL OR m.telegram_chat_id = :chat_id2::bigint)
            GROUP BY f.reason
            SQL,
            [
                'period_from' => $from,
                'period_to' => $to,
                'chat_id1' => $chatId,
                'chat_id2' => $chatId,
            ],
        );

        return [
            'messages' => (int) $row->messages,
            'classified' => (int) $row->classified,
            'excluded' => (int) $row->excluded,
            'failed' => (int) $row->failed,
            'not_classified_yet' => (int) $row->not_classified_yet,
            'excluded_by_reason' => collect($excludedByReason)
                ->mapWithKeys(fn (object $r): array => [$r->reason => (int) $r->n])->all(),
            'failed_by_reason' => collect($failedByReason)
                ->mapWithKeys(fn (object $r): array => [$r->reason => (int) $r->n])->all(),
        ];
    }

    /**
     * C6: the model's label on a waiting question — the earliest of the item's messages the model
     * judged to need an answer; if none, the earliest classified message (M17: a greeting anchor
     * does not hide the question after it). Keyed by `item_id`; an item with no classified message
     * is absent (the caller falls back to C5's status of its anchor, M18).
     *
     * @param  array<int, int>  $itemIds
     * @return array<int, object>
     */
    private function classificationLabelsForItems(array $itemIds): array
    {
        if ($itemIds === []) {
            return [];
        }

        $rows = DB::select(
            <<<'SQL'
            SELECT DISTINCT ON (ai.id)
                   ai.id AS item_id, m.message_id AS labelled_message, c.category, c.confidence
            FROM attention_items ai
            JOIN telegram_messages m
              ON m.telegram_chat_id = ai.telegram_chat_id
             AND (m.attention_item_id = ai.id OR m.message_id = ai.telegram_message_id)
            JOIN message_classifications c
              ON c.telegram_chat_id = m.telegram_chat_id
             AND c.telegram_message_id = m.message_id AND c.is_current
            WHERE ai.id = ANY(:item_ids::bigint[])
            ORDER BY ai.id, c.needs_response DESC, m.sent_at, m.message_id
            SQL,
            ['item_ids' => '{'.implode(',', $itemIds).'}'],
        );

        return collect($rows)->keyBy('item_id')->all();
    }

    /**
     * C7: TG-M3's `attention-metrics.md` §5 statement, verbatim, with
     * `AND (:chat_id IS NULL OR telegram_chat_id = :chat_id)` added — the baseline the model is
     * compared against, on its own definitions (D-TG-156). Grouped by `rule_version` always (M15);
     * operator additions arrive in their own row, where `rule_version` is NULL.
     *
     * @return array<int, object>
     */
    private function classificationRuleBaseline(?int $chatId, Carbon $from, Carbon $to): array
    {
        return DB::select(
            <<<'SQL'
            SELECT count(*) FILTER (WHERE source = 'rule')                          AS rule_opened,
                   count(*) FILTER (WHERE source = 'rule' AND status = 'dismissed') AS rule_dismissed,
                   count(*) FILTER (WHERE source = 'operator')                      AS operator_added,
                   rule_version
            FROM attention_items
            WHERE opened_at >= :period_from AND opened_at < :period_to
              AND (:chat_id1::bigint IS NULL OR telegram_chat_id = :chat_id2::bigint)
            GROUP BY rule_version
            SQL,
            [
                'period_from' => $from,
                'period_to' => $to,
                'chat_id1' => $chatId,
                'chat_id2' => $chatId,
            ],
        );
    }
}
