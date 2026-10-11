<?php

namespace App\Filament\Resources\Incidents\Concerns;

use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;

/**
 * The SQL of `contracts/incident-metrics.md` §2-§4, quoted here once for the panel — the same
 * arithmetic `apps/ai-api/app/application/moderation/metrics.py`'s `incident_outcome_stats`,
 * `incident_timing_stats` and `detection_latency_stats` run on the Python side (T060, D-TG-118).
 * Neither side re-expresses the other's definition; a changed figure changes this file and that
 * one, never a third — **no arithmetic is invented here**, and no `avg(` appears anywhere (M14).
 *
 * Every statement reads `moderation_incident_state` (lifecycle contract N6) and selects by
 * `detected_at` — the detection moment, never `opened_at` and never `created_at` (M1). Every
 * method takes its scoping (`$from`/`$to`, `$moderatorId`, `$chatId`) as an explicit argument,
 * mirroring `AttentionMetrics`'s own style.
 */
trait IncidentMetrics
{
    /**
     * §2 — Outcomes: `handled + missed + within_window + false_positive == flagged`, always
     * (M7). `handled_share` is `handled / (handled + missed)`, `null` when that denominator is
     * zero (M9) — within-window incidents never enter it. `acknowledged_not_handled` is the
     * acknowledged share of `missed + within_window` (M8), shown beside them, never inside
     * `handled`.
     *
     * @return array{flagged: int, false_positive: int, handled: int, missed: int,
     *               within_window: int, acknowledged_not_handled: int, handled_share: float|null}
     */
    private function incidentOutcomeStats(
        Carbon $from,
        Carbon $to,
        ?int $moderatorId = null,
        ?int $chatId = null,
    ): array {
        $row = DB::selectOne(
            <<<'SQL'
            SELECT
              count(*)                                                                    AS flagged,
              count(*) FILTER (WHERE s.status = 'closed_false_positive')                  AS false_positive,
              count(*) FILTER (WHERE s.status <> 'closed_false_positive'
                                 AND s.resolved_at <= i.detected_at + make_interval(secs => :max_age_s1))
                                                                                            AS handled,
              count(*) FILTER (WHERE s.status <> 'closed_false_positive'
                                 AND (s.resolved_at IS NULL
                                      OR s.resolved_at > i.detected_at + make_interval(secs => :max_age_s2))
                                 AND now() >  i.detected_at + make_interval(secs => :max_age_s3))
                                                                                            AS missed,
              count(*) FILTER (WHERE s.status <> 'closed_false_positive'
                                 AND s.resolved_at IS NULL
                                 AND now() <= i.detected_at + make_interval(secs => :max_age_s4))
                                                                                            AS within_window,
              count(*) FILTER (WHERE s.status <> 'closed_false_positive'
                                 AND (s.resolved_at IS NULL
                                      OR s.resolved_at > i.detected_at + make_interval(secs => :max_age_s5))
                                 AND s.first_acknowledgement_at
                                     <= i.detected_at + make_interval(secs => :max_age_s6))
                                                                                            AS acknowledged_not_handled
            FROM moderation_incidents i
            JOIN moderation_incident_state s ON s.incident_id = i.id
            WHERE i.detected_at >= :period_from AND i.detected_at < :period_to
              AND (:moderator_id1::bigint IS NULL OR i.responsible_moderator_id = :moderator_id2::bigint)
              AND (:chat_id1::bigint      IS NULL OR i.telegram_chat_id        = :chat_id2::bigint)
            SQL,
            [
                'max_age_s1' => $this->incidentMaxAgeS(),
                'max_age_s2' => $this->incidentMaxAgeS(),
                'max_age_s3' => $this->incidentMaxAgeS(),
                'max_age_s4' => $this->incidentMaxAgeS(),
                'max_age_s5' => $this->incidentMaxAgeS(),
                'max_age_s6' => $this->incidentMaxAgeS(),
                'period_from' => $from,
                'period_to' => $to,
                'moderator_id1' => $moderatorId,
                'moderator_id2' => $moderatorId,
                'chat_id1' => $chatId,
                'chat_id2' => $chatId,
            ],
        );

        $handled = (int) $row->handled;
        $missed = (int) $row->missed;
        $denominator = $handled + $missed;

        return [
            'flagged' => (int) $row->flagged,
            'false_positive' => (int) $row->false_positive,
            'handled' => $handled,
            'missed' => $missed,
            'within_window' => (int) $row->within_window,
            'acknowledged_not_handled' => (int) $row->acknowledged_not_handled,
            'handled_share' => $denominator > 0 ? $handled / $denominator : null,
        ];
    }

    /**
     * §3 — The three timings, each its own earliest evidence minus `detected_at` (M11). Evidence
     * before the flag lands in `before_flagging` and in no percentile or maximum (M12) — no
     * negative or zero stand-in is ever produced. p90 is withheld, with a reason, below
     * `MODERATION_PERCENTILE_MIN_SAMPLES`, judged on each timing's own count (M13).
     *
     * @return array{acknowledgement: array, confirmation: array, enforcement: array}
     */
    private function incidentTimingStats(
        Carbon $from,
        Carbon $to,
        ?int $moderatorId = null,
        ?int $chatId = null,
    ): array {
        $row = DB::selectOne(
            <<<'SQL'
            SELECT
              count(*) FILTER (WHERE t_ack  >= 0)                                          AS ack_samples,
              count(*) FILTER (WHERE t_ack  <  0)                                          AS ack_before_flagging,
              percentile_cont(0.5) WITHIN GROUP (ORDER BY t_ack)  FILTER (WHERE t_ack  >= 0) AS ack_median,
              percentile_cont(0.9) WITHIN GROUP (ORDER BY t_ack)  FILTER (WHERE t_ack  >= 0) AS ack_p90,
              max(t_ack)  FILTER (WHERE t_ack  >= 0)                                       AS ack_max,

              count(*) FILTER (WHERE t_conf >= 0)                                          AS conf_samples,
              count(*) FILTER (WHERE t_conf <  0)                                          AS conf_before_flagging,
              percentile_cont(0.5) WITHIN GROUP (ORDER BY t_conf) FILTER (WHERE t_conf >= 0) AS conf_median,
              percentile_cont(0.9) WITHIN GROUP (ORDER BY t_conf) FILTER (WHERE t_conf >= 0) AS conf_p90,
              max(t_conf) FILTER (WHERE t_conf >= 0)                                       AS conf_max,

              count(*) FILTER (WHERE t_enf  >= 0)                                          AS enf_samples,
              count(*) FILTER (WHERE t_enf  <  0)                                          AS enf_before_flagging,
              percentile_cont(0.5) WITHIN GROUP (ORDER BY t_enf)  FILTER (WHERE t_enf  >= 0) AS enf_median,
              percentile_cont(0.9) WITHIN GROUP (ORDER BY t_enf)  FILTER (WHERE t_enf  >= 0) AS enf_p90,
              max(t_enf)  FILTER (WHERE t_enf  >= 0)                                       AS enf_max
            FROM (
              SELECT extract(epoch FROM s.first_acknowledgement_at - i.detected_at) AS t_ack,
                     extract(epoch FROM s.first_confirmation_at    - i.detected_at) AS t_conf,
                     extract(epoch FROM s.first_enforcement_at     - i.detected_at) AS t_enf
              FROM moderation_incidents i
              JOIN moderation_incident_state s ON s.incident_id = i.id
              WHERE s.status <> 'closed_false_positive'
                AND i.detected_at >= :period_from AND i.detected_at < :period_to
                AND (:moderator_id1::bigint IS NULL OR i.responsible_moderator_id = :moderator_id2::bigint)
                AND (:chat_id1::bigint      IS NULL OR i.telegram_chat_id        = :chat_id2::bigint)
            ) t
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

        return [
            'acknowledgement' => $this->timingBlock($row, 'ack'),
            'confirmation' => $this->timingBlock($row, 'conf'),
            'enforcement' => $this->timingBlock($row, 'enf'),
        ];
    }

    /**
     * @return array{samples: int, before_flagging: int, median: float|null, p90: float|null,
     *               p90_suppressed: bool, max: float|null}
     */
    private function timingBlock(object $row, string $prefix): array
    {
        $samples = (int) $row->{"{$prefix}_samples"};
        $suppressed = $samples < $this->incidentPercentileMinSamples();
        $p90 = $row->{"{$prefix}_p90"};

        return [
            'samples' => $samples,
            'before_flagging' => (int) $row->{"{$prefix}_before_flagging"},
            'median' => $row->{"{$prefix}_median"} !== null ? (float) $row->{"{$prefix}_median"} : null,
            'p90' => (! $suppressed && $p90 !== null) ? (float) $p90 : null,
            'p90_suppressed' => $suppressed,
            'max' => $row->{"{$prefix}_max"} !== null ? (float) $row->{"{$prefix}_max"} : null,
        ];
    }

    /**
     * §4, amended for TG-M5 (`classification-metrics.md` C8, D-TG-159): grouped by `i.source` —
     * one block per opener, keyed `'operator'` / `'ai'`. Still a figure about the system, never
     * about a moderator (M16) — this method takes no `$moderatorId` parameter by construction.
     * Includes false positives (M17): a wrong flag took exactly as long to raise as a right one.
     * A source with no incidents in the period has no key at all — never a zero-filled block.
     *
     * @return array<string, array{flagged: int, median: float|null, p90: float|null,
     *               p90_suppressed: bool, max: float|null}>
     */
    private function detectionLatencyStats(Carbon $from, Carbon $to, ?int $chatId = null): array
    {
        $rows = DB::select(
            <<<'SQL'
            SELECT i.source,
                   count(*)                                                         AS flagged,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY lat)                 AS latency_median,
                   percentile_cont(0.9) WITHIN GROUP (ORDER BY lat)                 AS latency_p90,
                   max(lat)                                                         AS latency_max
            FROM (
              SELECT i.source, extract(epoch FROM i.detected_at - i.opened_at) AS lat
              FROM moderation_incidents i
              WHERE i.detected_at >= :period_from AND i.detected_at < :period_to
                AND (:chat_id1::bigint IS NULL OR i.telegram_chat_id = :chat_id2::bigint)
            ) i
            GROUP BY i.source
            SQL,
            [
                'period_from' => $from,
                'period_to' => $to,
                'chat_id1' => $chatId,
                'chat_id2' => $chatId,
            ],
        );

        $result = [];
        foreach ($rows as $row) {
            $flagged = (int) $row->flagged;
            $suppressed = $flagged < $this->incidentPercentileMinSamples();
            $p90 = $row->latency_p90;

            $result[$row->source] = [
                'flagged' => $flagged,
                'median' => $row->latency_median !== null ? (float) $row->latency_median : null,
                'p90' => (! $suppressed && $p90 !== null) ? (float) $p90 : null,
                'p90_suppressed' => $suppressed,
                'max' => $row->latency_max !== null ? (float) $row->latency_max : null,
            ];
        }

        return $result;
    }

    /**
     * `MODERATION_PERCENTILE_MIN_SAMPLES` — the p90 suppression floor, the same key and default
     * (10) `AttentionMetrics` reads.
     */
    private function incidentPercentileMinSamples(): int
    {
        return (int) config('moderation.percentile_min_samples', 10);
    }

    /**
     * `MODERATION_INCIDENT_MAX_AGE_S` — the "missed" ceiling (`contracts/incident-metrics.md`
     * M3), blank-safe (research Finding 2, D-TG-122), default 86400 (24h).
     */
    private function incidentMaxAgeS(): int
    {
        return (int) config('moderation.incident_max_age_s', 86400);
    }
}
