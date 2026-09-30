<?php

namespace App\Filament\Pages;

use App\Filament\Pages\Concerns\ClassificationMetrics;
use App\Models\ModelProfile;
use App\Models\TelegramChat;
use BackedEnum;
use Filament\Pages\Page;
use Filament\Support\Icons\Heroicon;
use Illuminate\Support\Carbon;
use Illuminate\Support\Collection;
use UnitEnum;

/**
 * `control-panel-classification.md` §4 — the model compared against the human labels already
 * recorded, one section per C1-C7 (`classification-metrics.md`), one block per `(model,
 * instruction version, vocabulary version)`, never pooled (K3). Every figure is read straight
 * from `ClassificationMetrics` — nothing here averages, computes a percentage or a combined
 * score (A2, FR-049, SC-013); a ratio with a zero denominator reads "no labelled examples" (A1,
 * M21) and a model with no predictions in the period has no block at all (M22). No control on
 * this page changes anything (A3, FR-059) — it is read-only, exactly as the Possible Violations
 * page.
 */
class ClassificationAccuracy extends Page
{
    use ClassificationMetrics;

    protected static string|BackedEnum|null $navigationIcon = Heroicon::OutlinedChartBar;

    protected static string|UnitEnum|null $navigationGroup = 'Moderation Intelligence';

    protected static ?string $navigationLabel = 'Classification Accuracy';

    protected static ?string $title = 'Classification Accuracy';

    protected string $view = 'filament.pages.classification-accuracy';

    /**
     * The period filter, read in `Asia/Riyadh` calendar days — mirrors the Incidents list's own
     * `periodFrom`/`periodTo` (D-TG-56).
     */
    public string $periodFrom = '';

    public string $periodTo = '';

    /** The group filter — a `telegram_chats.id`, or blank for every measured group (K2). */
    public ?string $chatId = null;

    public function mount(): void
    {
        $this->periodTo = now('Asia/Riyadh')->toDateString();
        $this->periodFrom = now('Asia/Riyadh')->subDays(29)->toDateString();
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

    private function scopedChatId(): ?int
    {
        return filled($this->chatId) ? (int) $this->chatId : null;
    }

    public function groupOptions(): array
    {
        return TelegramChat::query()
            ->orderBy('title')
            ->get()
            ->mapWithKeys(fn (TelegramChat $chat): array => [$chat->id => $chat->title ?? '(untitled)'])
            ->all();
    }

    /**
     * One block per `(model_profile_id, prompt_version, taxonomy_version)` seen in C1, C2 or C3
     * for the current period and group — the union, since a model with a row in only one of the
     * three still earns a block (M22 applies per figure, not per model).
     */
    public function blocks(): Collection
    {
        [$from, $to] = $this->periodBounds();
        $chatId = $this->scopedChatId();

        $questions = collect($this->classificationQuestionStats($chatId, $from, $to));
        $unverified = collect($this->classificationUnverifiedStats($chatId, $from, $to));
        $violations = collect($this->classificationViolationStats($chatId, $from, $to));
        $listed = collect($this->possibleViolations($chatId, $from, $to));

        $keyOf = fn (int|string $modelProfileId, string $promptVersion, int $taxonomyVersion): string => "{$modelProfileId}|{$promptVersion}|{$taxonomyVersion}";

        $profileIdsByName = ModelProfile::query()->pluck('id', 'name');

        $keys = $questions->map(fn (object $r): string => $keyOf($r->model_profile_id, $r->prompt_version, $r->taxonomy_version))
            ->merge($unverified->map(fn (object $r): string => $keyOf($r->model_profile_id, $r->prompt_version, $r->taxonomy_version)))
            ->merge($violations->map(fn (object $r): string => $keyOf($r->model_profile_id, $r->prompt_version, $r->taxonomy_version)))
            ->unique()
            ->values();

        return $keys->map(function (string $key) use ($questions, $unverified, $violations, $listed, $profileIdsByName): array {
            [$modelProfileId, $promptVersion, $taxonomyVersion] = explode('|', $key);
            $modelProfileId = (int) $modelProfileId;
            $taxonomyVersion = (int) $taxonomyVersion;
            $profile = ModelProfile::find($modelProfileId);

            $questionRows = $questions->filter(
                fn (object $r): bool => (int) $r->model_profile_id === $modelProfileId
                    && $r->prompt_version === $promptVersion && (int) $r->taxonomy_version === $taxonomyVersion
            )->keyBy('label');

            $unverifiedRow = $unverified->first(
                fn (object $r): bool => (int) $r->model_profile_id === $modelProfileId
                    && $r->prompt_version === $promptVersion && (int) $r->taxonomy_version === $taxonomyVersion
            );

            $violationRow = $violations->first(
                fn (object $r): bool => (int) $r->model_profile_id === $modelProfileId
                    && $r->prompt_version === $promptVersion && (int) $r->taxonomy_version === $taxonomyVersion
            );

            $listedNow = $listed->filter(
                fn (object $r): bool => ($profileIdsByName[$r->model] ?? null) === $modelProfileId
                    && $r->prompt_version === $promptVersion
            )->count();

            return [
                'model' => $profile?->name ?? "(profile {$modelProfileId})",
                'prompt_version' => $promptVersion,
                'taxonomy_version' => $taxonomyVersion,
                'questions' => [
                    'rule_kept' => $this->questionLabel($questionRows, 'rule_kept'),
                    'rule_dismissed' => $this->questionLabel($questionRows, 'rule_dismissed'),
                    'operator_added' => $this->questionLabel($questionRows, 'operator_added'),
                    'unverified' => (int) ($unverifiedRow->unverified_needs_response ?? 0),
                ],
                'violations' => [
                    'indep_flags' => (int) ($violationRow->indep_flags ?? 0),
                    'indep_agreed' => (int) ($violationRow->indep_agreed ?? 0),
                    'indep_same_cat' => (int) ($violationRow->indep_same_cat ?? 0),
                    'prompted_flags' => (int) ($violationRow->prompted_flags ?? 0),
                    'prompted_agreed' => (int) ($violationRow->prompted_agreed ?? 0),
                    'prompted_same_cat' => (int) ($violationRow->prompted_same_cat ?? 0),
                    'fp_closures' => (int) ($violationRow->fp_closures ?? 0),
                    'fp_model_raised' => (int) ($violationRow->fp_model_raised ?? 0),
                    'model_opened' => (int) ($violationRow->model_opened ?? 0),
                    'model_opened_fp' => (int) ($violationRow->model_opened_fp ?? 0),
                    'listed_now' => $listedNow,
                ],
            ];
        })->values();
    }

    /**
     * @param  Collection<string, object>  $questionRows
     * @return array{classified: int, judged_needs_response: int}
     */
    private function questionLabel(Collection $questionRows, string $label): array
    {
        $row = $questionRows->get($label);

        return [
            'classified' => (int) ($row->classified ?? 0),
            'judged_needs_response' => (int) ($row->judged_needs_response ?? 0),
        ];
    }

    /** C5: what happened to every message — one figure, never grouped by model. */
    public function volume(): array
    {
        [$from, $to] = $this->periodBounds();

        return $this->classificationVolumeStats($this->scopedChatId(), $from, $to);
    }

    /** C7: the rule set's own baseline, read per M19 — grouped by `rule_version`. */
    public function ruleBaseline(): Collection
    {
        [$from, $to] = $this->periodBounds();

        return collect($this->classificationRuleBaseline($this->scopedChatId(), $from, $to))
            ->map(function (object $row): array {
                $ruleOpened = (int) $row->rule_opened;
                $ruleDismissed = (int) $row->rule_dismissed;
                $operatorAdded = (int) $row->operator_added;

                return [
                    'rule_version' => $row->rule_version,
                    'rule_opened' => $ruleOpened,
                    'rule_dismissed' => $ruleDismissed,
                    'operator_added' => $operatorAdded,
                ];
            })
            ->filter(fn (array $row): bool => $row['rule_opened'] > 0 || $row['operator_added'] > 0)
            ->values();
    }

    /** A1, M21: "no labelled examples" over a zero denominator — never `0/0`. */
    public function ratio(int $numerator, int $denominator): string
    {
        return $denominator > 0 ? "{$numerator} / {$denominator}" : 'no labelled examples';
    }
}
