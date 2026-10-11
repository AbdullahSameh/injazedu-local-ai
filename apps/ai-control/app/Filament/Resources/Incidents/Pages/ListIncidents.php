<?php

namespace App\Filament\Resources\Incidents\Pages;

use App\Filament\Resources\Incidents\Concerns\IncidentMetrics;
use App\Filament\Resources\Incidents\IncidentResource;
use App\Models\Moderator;
use App\Models\TelegramChat;
use Filament\Resources\Pages\ListRecords;
use Illuminate\Support\Carbon;
use Illuminate\Support\Collection;
use Illuminate\Support\Facades\DB;

/**
 * No `CreateAction` in the header — an incident is opened only through
 * `OpenIncidentAction` (already the table's header action), never typed in directly. The custom
 * view adds the standing sentence and the figures table beneath the table (`control-panel-
 * incidents.md` §1.4 P4, T056; §4, T062).
 */
class ListIncidents extends ListRecords
{
    use IncidentMetrics;

    protected static string $resource = IncidentResource::class;

    protected string $view = 'filament.resources.incidents.pages.list-incidents';

    /**
     * The figures table's period filter (T062), read in `Asia/Riyadh` calendar days and
     * converted once to the half-open `[from, to)` UTC bound the metrics statements expect (M2),
     * mirroring the Live Attention Queue's own `periodFrom`/`periodTo` (D-TG-56).
     */
    public string $periodFrom = '';

    public string $periodTo = '';

    public function mount(): void
    {
        parent::mount();
        $this->periodTo = now('Asia/Riyadh')->toDateString();
        $this->periodFrom = now('Asia/Riyadh')->subDays(29)->toDateString();
    }

    protected function getHeaderActions(): array
    {
        return [
            //
        ];
    }

    /**
     * @return array{0: Carbon, 1: Carbon}
     */
    private function periodBounds(): array
    {
        $from = Carbon::parse($this->periodFrom, 'Asia/Riyadh')->startOfDay()->utc();
        $to = Carbon::parse($this->periodTo, 'Asia/Riyadh')->addDay()->startOfDay()->utc();

        return [$from, $to];
    }

    /**
     * T062: one row per group with any incident flagged in the period — outcomes, timings and
     * this group's own detection latency (P15: latency is a group/total figure only).
     */
    public function figuresByGroup(): Collection
    {
        [$from, $to] = $this->periodBounds();

        $chatIds = DB::table('moderation_incidents')
            ->where('detected_at', '>=', $from)
            ->where('detected_at', '<', $to)
            ->distinct()
            ->pluck('telegram_chat_id');

        return TelegramChat::query()
            ->whereIn('id', $chatIds)
            ->orderBy('title')
            ->get()
            ->map(fn (TelegramChat $chat): array => array_merge(
                ['label' => $chat->title ?? '(untitled)'],
                $this->incidentOutcomeStats($from, $to, null, $chat->id),
                ['timings' => $this->incidentTimingStats($from, $to, null, $chat->id)],
                ['latency' => $this->detectionLatencyStats($from, $to, $chat->id)],
            ))
            ->values();
    }

    /**
     * T062: one row per moderator responsible for any incident flagged in the period — from
     * `moderation_incidents.responsible_moderator_id`, the owner snapshotted at detection, never
     * the actor who happened to perform the resolving evidence (M2). No detection-latency column
     * (P15, FR-054): the figure cannot be attributed to a moderator by construction.
     */
    public function figuresByModerator(): Collection
    {
        [$from, $to] = $this->periodBounds();

        $moderatorIds = DB::table('moderation_incidents')
            ->where('detected_at', '>=', $from)
            ->where('detected_at', '<', $to)
            ->whereNotNull('responsible_moderator_id')
            ->distinct()
            ->pluck('responsible_moderator_id');

        return Moderator::query()
            ->whereIn('id', $moderatorIds)
            ->orderBy('display_name')
            ->get()
            ->map(fn (Moderator $moderator): array => array_merge(
                ['label' => $moderator->display_name],
                $this->incidentOutcomeStats($from, $to, $moderator->id, null),
                ['timings' => $this->incidentTimingStats($from, $to, $moderator->id, null)],
            ))
            ->values();
    }

    /**
     * The total row across every group in the period — the same statements with no chat filter
     * (P13: every number is the quoted SQL; nothing here is invented arithmetic).
     */
    public function totalFigures(): array
    {
        [$from, $to] = $this->periodBounds();

        return array_merge(
            $this->incidentOutcomeStats($from, $to),
            ['timings' => $this->incidentTimingStats($from, $to)],
            ['latency' => $this->detectionLatencyStats($from, $to)],
        );
    }

    /**
     * P10, M18: `null` renders "no data" — never "0s" — the difference between "nothing happened"
     * and "happened instantly".
     */
    public function humanDuration(?float $seconds): string
    {
        if ($seconds === null) {
            return 'no data';
        }

        return \Carbon\CarbonInterval::seconds((int) round($seconds))->cascade()->forHumans(['short' => true]);
    }

    /**
     * P14: below `MODERATION_PERCENTILE_MIN_SAMPLES` this renders the suppression reason, never a
     * number built from too few points — judged on this figure's own sample count (M13), which is
     * `samples` for a timing block and `flagged` for the latency block, so the count is passed in
     * explicitly rather than assumed from a shared key name.
     */
    public function p90Display(?float $p90, bool $suppressed, int $sampleCount): string
    {
        if ($suppressed) {
            return sprintf(
                'Fewer than %d samples (n=%d)',
                $this->incidentPercentileMinSamples(),
                $sampleCount,
            );
        }

        return $this->humanDuration($p90);
    }

    /**
     * M9: "—" when the denominator (`handled + missed`) is zero — never "0%".
     */
    public function shareDisplay(?float $share): string
    {
        return $share === null ? '—' : number_format($share * 100, 0).'%';
    }

    /**
     * TG-M5, D-TG-159: `'operator'` / `'ai'` → the words the page uses, matching the Incidents
     * list's own "Opened by" column (L1) — never the raw `source` value.
     */
    public function openerLabel(string $source): string
    {
        return $source === 'ai' ? 'Model' : 'Operator';
    }

    /**
     * One row per opener present in a `detectionLatencyStats()` block, sorted so `'Model'` and
     * `'Operator'` render in a stable order regardless of which source's row the query returned
     * first — a source absent from the period has no row at all (never a zero-filled one).
     *
     * @param  array<string, array{flagged: int, median: float|null, p90: float|null,
     *                p90_suppressed: bool, max: float|null}>  $latencyBySource
     * @return Collection<int, array{opener: string, flagged: int, median: float|null,
     *                p90: float|null, p90_suppressed: bool, max: float|null}>
     */
    public function latencyRows(array $latencyBySource): Collection
    {
        return collect($latencyBySource)
            ->map(fn (array $block, string $source): array => array_merge(
                ['opener' => $this->openerLabel($source)],
                $block,
            ))
            ->values()
            ->sortBy('opener')
            ->values();
    }
}
