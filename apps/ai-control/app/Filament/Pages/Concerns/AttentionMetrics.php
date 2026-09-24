<?php

namespace App\Filament\Pages\Concerns;

use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;

/**
 * The SQL of `contracts/attention-metrics.md` §2-§5, quoted here once for the panel — the same
 * arithmetic `apps/ai-api/app/application/moderation/metrics.py` runs on the Python side (T072,
 * P9, D-TG-91). Neither side re-expresses the other's definition; a changed figure changes this
 * file and that one, never a third, and **no arithmetic is invented here** — every method below
 * is a direct reading of the contract's own query.
 *
 * Every method takes its scoping (`$from`/`$to`, `$moderatorId`, `$chatId`) as an explicit
 * argument rather than reading page state itself, mirroring the Python side's explicit-parameter
 * style — a query has no business owning "the current period".
 */
trait AttentionMetrics
{
    /**
     * §2 — First Response Time. Only `status = 'answered'` contributes (M3): `open`, `expired`
     * and `dismissed` items contribute no value, not zero. `answered` is always returned beside
     * the percentiles (M5); `p90_frt` is suppressed to `null` — with `p90_suppressed = true` —
     * below `MODERATION_PERCENTILE_MIN_SAMPLES` (M6), so a figure built from too few points is
     * never rendered as if it were authoritative. **No average is computed anywhere** (M7).
     *
     * @return array{answered: int, median_frt: float|null, p90_frt: float|null,
     *               p90_suppressed: bool, max_frt: float|null}
     */
    private function attentionFrtStats(
        Carbon $from,
        Carbon $to,
        ?int $moderatorId = null,
        ?int $chatId = null,
    ): array {
        $row = DB::selectOne(
            <<<'SQL'
            SELECT
              count(*)                                          AS answered,
              percentile_cont(0.5) WITHIN GROUP (ORDER BY frt)  AS median_frt,
              percentile_cont(0.9) WITHIN GROUP (ORDER BY frt)  AS p90_frt,
              max(frt)                                          AS max_frt
            FROM (
              SELECT extract(epoch FROM (first_response_at - opened_at)) AS frt
              FROM attention_items
              WHERE status = 'answered'
                AND opened_at >= :period_from AND opened_at < :period_to
                AND (:moderator_id1::bigint IS NULL OR responsible_moderator_id = :moderator_id2::bigint)
                AND (:chat_id1::bigint      IS NULL OR telegram_chat_id        = :chat_id2::bigint)
            ) s
            SQL,
            [
                'period_from' => $from,
                'period_to' => $to,
                'moderator_id1' => $moderatorId,
                'moderator_id2' => $moderatorId,
                'chat_id1' => $chatId,
                'chat_id2' => $chatId,
            ],
        );

        $answered = (int) $row->answered;
        $suppressed = $answered < $this->attentionPercentileMinSamples();

        return [
            'answered' => $answered,
            'median_frt' => $row->median_frt !== null ? (float) $row->median_frt : null,
            'p90_frt' => (! $suppressed && $row->p90_frt !== null) ? (float) $row->p90_frt : null,
            'p90_suppressed' => $suppressed,
            'max_frt' => $row->max_frt !== null ? (float) $row->max_frt : null,
        ];
    }

    /**
     * §3 — Unanswered: the count and its share of `opened` (M9), never a bare number.
     * `dismissed` items are excluded from both `unanswered` and `opened` (M10); `expired` items
     * stay counted in `unanswered` permanently, with their own count shown alongside (M11).
     * `unanswered_share` is `null`, not `0`, when nothing was asked.
     *
     * @return array{unanswered: int, expired: int, opened: int, unanswered_share: float|null}
     */
    private function attentionUnansweredStats(
        Carbon $from,
        Carbon $to,
        ?int $moderatorId = null,
        ?int $chatId = null,
    ): array {
        $row = DB::selectOne(
            <<<'SQL'
            SELECT count(*) FILTER (WHERE status IN ('open','expired'))      AS unanswered,
                   count(*) FILTER (WHERE status = 'expired')                AS expired,
                   count(*) FILTER (WHERE status <> 'dismissed')             AS opened
            FROM attention_items
            WHERE opened_at >= :period_from AND opened_at < :period_to
              AND (:moderator_id1::bigint IS NULL OR responsible_moderator_id = :moderator_id2::bigint)
              AND (:chat_id1::bigint      IS NULL OR telegram_chat_id        = :chat_id2::bigint)
            SQL,
            [
                'period_from' => $from,
                'period_to' => $to,
                'moderator_id1' => $moderatorId,
                'moderator_id2' => $moderatorId,
                'chat_id1' => $chatId,
                'chat_id2' => $chatId,
            ],
        );

        $opened = (int) $row->opened;
        $unanswered = (int) $row->unanswered;

        return [
            'unanswered' => $unanswered,
            'expired' => (int) $row->expired,
            'opened' => $opened,
            'unanswered_share' => $opened > 0 ? $unanswered / $opened : null,
        ];
    }

    /**
     * §4 — Oldest still waiting, in seconds. `status = 'open'` only (M12) — expired items are
     * excluded so one abandoned question cannot pin this figure forever. Ignores the period
     * window on purpose (M13): a live statement about now, not a historical one. Computed
     * server-side on every call (M14) — never from a browser clock.
     */
    private function attentionOldestWaitingSeconds(?int $chatId = null): ?float
    {
        $row = DB::selectOne(
            <<<'SQL'
            SELECT extract(epoch FROM (max(now() - opened_at))) AS oldest_waiting_s
            FROM attention_items
            WHERE status = 'open'
              AND (:chat_id1::bigint IS NULL OR telegram_chat_id = :chat_id2::bigint)
            SQL,
            ['chat_id1' => $chatId, 'chat_id2' => $chatId],
        );

        return $row->oldest_waiting_s !== null ? (float) $row->oldest_waiting_s : null;
    }

    /**
     * `MODERATION_PERCENTILE_MIN_SAMPLES` (`config/moderation.php`) — the same threshold and
     * default (10) as `apps/ai-api`'s own copy of this setting.
     */
    private function attentionPercentileMinSamples(): int
    {
        return (int) config('moderation.percentile_min_samples', 10);
    }
}
