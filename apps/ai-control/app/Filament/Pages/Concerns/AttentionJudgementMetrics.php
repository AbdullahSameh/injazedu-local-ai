<?php

namespace App\Filament\Pages\Concerns;

use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;

/**
 * The exact SQL behind the attention judgement's figures (TG-M5.3,
 * `specs/011-tg-m5-3-attention-judgement/contracts/attention-metrics.md` §2), quoted here once for
 * the panel — the same statements `apps/ai-api/app/application/moderation/metrics.py` runs on the
 * Python side. **No arithmetic is invented here** (spec FR-337): every method is a direct reading
 * of the contract's own query, and the derivation of needs-response is never restated.
 *
 * - C10a: what happened to every message — judged, excluded, failed, not judged yet — never
 *   grouped by model, with M26's breakdowns (exclusions by reason, failures by the latest reason,
 *   as 008 M15).
 * - C10b: live judgements by intent and timeliness, per `(model, attention instruction)`. `:gap_s`
 *   is `config('moderation.burst_gap_s')`, the panel's half of `MODERATION_BURST_GAP_S`.
 * - C10c: operator-added items — the misses a person noticed — by their anchor's attention status
 *   and by whether the anchor's sender posted a same-thread neighbour within the gap (M30-M32).
 *
 * Named parameters cannot repeat under PDO, so the chat filter binds twice (`chat_id1`,
 * `chat_id2`), exactly as `ClassificationMetrics` does.
 */
trait AttentionJudgementMetrics
{
    /**
     * C10a (M26, M27): `messages = judged + excluded + failed + not_judged_yet`, always. Messages
     * posted before an attention instruction was configured stay "not judged yet".
     *
     * @return array{messages: int, judged: int, excluded: int, failed: int, not_judged_yet: int, excluded_by_reason: array<string, int>, failed_by_reason: array<string, int>}
     */
    private function attentionJudgementVolumeStats(?int $chatId, Carbon $from, Carbon $to): array
    {
        $bindings = [
            'period_from' => $from,
            'period_to' => $to,
            'chat_id1' => $chatId,
            'chat_id2' => $chatId,
        ];

        $row = DB::selectOne(
            <<<'SQL'
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
              AND (:chat_id1::bigint IS NULL OR m.telegram_chat_id = :chat_id2::bigint)
            SQL,
            $bindings,
        );

        $excludedByReason = DB::select(
            <<<'SQL'
            SELECT x.reason, count(*) AS n
            FROM message_attention_attempts x
            JOIN telegram_messages m
              ON m.telegram_chat_id = x.telegram_chat_id AND m.message_id = x.telegram_message_id
            WHERE x.outcome = 'excluded'
              AND m.sent_at >= :period_from AND m.sent_at < :period_to
              AND (:chat_id1::bigint IS NULL OR m.telegram_chat_id = :chat_id2::bigint)
            GROUP BY x.reason
            SQL,
            $bindings,
        );

        $failedByReason = DB::select(
            <<<'SQL'
            SELECT f.reason, count(*) AS n
            FROM telegram_messages m
            JOIN LATERAL (
              SELECT a.reason FROM message_attention_attempts a
              WHERE a.telegram_chat_id = m.telegram_chat_id AND a.telegram_message_id = m.message_id
                AND a.outcome = 'failed'
              ORDER BY a.created_at DESC, a.id DESC LIMIT 1
            ) f ON true
            WHERE NOT EXISTS (
                SELECT 1 FROM message_attention_judgements j
                WHERE j.telegram_chat_id = m.telegram_chat_id
                  AND j.telegram_message_id = m.message_id AND j.is_current
              )
              AND NOT EXISTS (
                SELECT 1 FROM message_attention_attempts x
                WHERE x.telegram_chat_id = m.telegram_chat_id
                  AND x.telegram_message_id = m.message_id AND x.outcome = 'excluded'
              )
              AND m.sent_at >= :period_from AND m.sent_at < :period_to
              AND (:chat_id1::bigint IS NULL OR m.telegram_chat_id = :chat_id2::bigint)
            GROUP BY f.reason
            SQL,
            $bindings,
        );

        return [
            'messages' => (int) $row->messages,
            'judged' => (int) $row->judged,
            'excluded' => (int) $row->excluded,
            'failed' => (int) $row->failed,
            'not_judged_yet' => (int) $row->not_judged_yet,
            'excluded_by_reason' => collect($excludedByReason)
                ->mapWithKeys(fn (object $r): array => [$r->reason => (int) $r->n])->all(),
            'failed_by_reason' => collect($failedByReason)
                ->mapWithKeys(fn (object $r): array => [$r->reason => (int) $r->n])->all(),
        ];
    }

    /**
     * C10b (M28, M29): one row per `(model_profile_id, prompt_version)` with a live judgement in
     * the period. `on_time` counts judgements recorded no later than `sent_at + gap`; the page shows
     * it as `on_time / judged`.
     *
     * @return array<int, object>
     */
    private function attentionJudgementIntentStats(?int $chatId, Carbon $from, Carbon $to, int $gapS): array
    {
        return DB::select(
            <<<'SQL'
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
              AND (:chat_id1::bigint IS NULL OR m.telegram_chat_id = :chat_id2::bigint)
            GROUP BY 1, 2
            SQL,
            [
                'gap_s' => $gapS,
                'period_from' => $from,
                'period_to' => $to,
                'chat_id1' => $chatId,
                'chat_id2' => $chatId,
            ],
        );
    }

    /**
     * C10c (M30-M32): one row per `(anchor_status, multi_message)` among the operator-added items
     * opened in the period. `multi_message` is exact (M30): a `sender_chat` anchor has no
     * `telegram_user_id`, so it is never multi-message. The gap binds twice, as the chat filter
     * does, since PDO named parameters cannot repeat.
     *
     * @return array<int, object>
     */
    private function attentionOperatorAddedStats(?int $chatId, Carbon $from, Carbon $to, int $gapS): array
    {
        return DB::select(
            <<<'SQL'
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
                             AND n.sent_at BETWEEN m.sent_at - make_interval(secs => :gap_s1)
                                               AND m.sent_at + make_interval(secs => :gap_s2)) AS multi_message,
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
              AND (:chat_id1::bigint IS NULL OR ai.telegram_chat_id = :chat_id2::bigint)
            GROUP BY 1, 2
            SQL,
            [
                'gap_s1' => $gapS,
                'gap_s2' => $gapS,
                'period_from' => $from,
                'period_to' => $to,
                'chat_id1' => $chatId,
                'chat_id2' => $chatId,
            ],
        );
    }
}
