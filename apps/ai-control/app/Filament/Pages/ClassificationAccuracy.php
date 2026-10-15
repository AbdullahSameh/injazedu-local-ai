<?php

namespace App\Filament\Pages;

use App\Filament\Pages\Concerns\AttentionJudgementMetrics;
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
 *
 * TG-M5.3 (`specs/011-…/contracts/dismissal-reasons.md` K7-K12): every dismissal count reads
 * "dismissed (any reason)", with its per-reason breakdown beside it — four counts read straight
 * from the same statement, never a ratio and never summed here.
 *
 * TG-M5.3 (`specs/011-…/contracts/attention-metrics.md` §2-§3): the attention judgement's own
 * figures — "Attention judgements: what happened to every message" (C10a) and one block per
 * `(model, attention instruction)` with its intents and `on_time / judged` (C10b) — read straight
 * from `AttentionJudgementMetrics`, never pooled with the classification blocks. Beneath C10a,
 * C10c splits the operator-added items by their anchor's attention status and burst size.
 *
 * TG-M5.3 C9′ (`attention-metrics.md` §1, M23′): the questions the model opened are routed by the
 * record that opened them — a `classification` row to its classification block, an `attention`
 * row to its attention block. "Model-opened and kept" sums `model_kept` over both (M19).
 */
class ClassificationAccuracy extends Page
{
    use AttentionJudgementMetrics;
    use ClassificationMetrics;

    protected static string|BackedEnum|null $navigationIcon = Heroicon::OutlinedChartBar;

    public static function getNavigationGroup(): string|UnitEnum|null
    {
        return __('Moderation Intelligence');
    }

    public static function getNavigationLabel(): string
    {
        return __('Classification Accuracy');
    }

    public function getTitle(): string
    {
        return __('Classification Accuracy');
    }

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
            ->mapWithKeys(fn (TelegramChat $chat): array => [$chat->id => $chat->title ?? __('(untitled)')])
            ->all();
    }

    /**
     * One block per `(model_profile_id, prompt_version, taxonomy_version)` seen in C1, C2, C3 or
     * C9′'s `classification` rows for the current period and group — the union, since a model with
     * a row in only one of them still earns a block (M22 applies per figure, not per model).
     */
    public function blocks(): Collection
    {
        [$from, $to] = $this->periodBounds();
        $chatId = $this->scopedChatId();

        $questions = collect($this->classificationQuestionStats($chatId, $from, $to));
        $unverified = collect($this->classificationUnverifiedStats($chatId, $from, $to));
        $violations = collect($this->classificationViolationStats($chatId, $from, $to));
        $listed = collect($this->possibleViolations($chatId, $from, $to));
        $modelOpened = collect($this->classificationModelOpenedQuestions($chatId, $from, $to))
            ->filter(fn (object $r): bool => $r->era === 'classification');

        $keyOf = fn (int|string $modelProfileId, string $promptVersion, int $taxonomyVersion): string => "{$modelProfileId}|{$promptVersion}|{$taxonomyVersion}";

        $profileIdsByName = ModelProfile::query()->pluck('id', 'name');

        $keys = $questions->map(fn (object $r): string => $keyOf($r->model_profile_id, $r->prompt_version, $r->taxonomy_version))
            ->merge($unverified->map(fn (object $r): string => $keyOf($r->model_profile_id, $r->prompt_version, $r->taxonomy_version)))
            ->merge($violations->map(fn (object $r): string => $keyOf($r->model_profile_id, $r->prompt_version, $r->taxonomy_version)))
            ->merge($modelOpened->map(fn (object $r): string => $keyOf($r->model_profile_id, $r->prompt_version, $r->taxonomy_version)))
            ->unique()
            ->values();

        return $keys->map(function (string $key) use ($questions, $unverified, $violations, $listed, $modelOpened, $profileIdsByName): array {
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

            $modelOpenedRow = $modelOpened->first(
                fn (object $r): bool => (int) $r->model_profile_id === $modelProfileId
                    && $r->prompt_version === $promptVersion && (int) $r->taxonomy_version === $taxonomyVersion
            );

            $listedNow = $listed->filter(
                fn (object $r): bool => ($profileIdsByName[$r->model] ?? null) === $modelProfileId
                    && $r->prompt_version === $promptVersion
            )->count();

            return [
                'model' => $profile?->name ?? __('(profile :id)', ['id' => $modelProfileId]),
                'prompt_version' => $promptVersion,
                'taxonomy_version' => $taxonomyVersion,
                'questions' => [
                    'rule_kept' => $this->questionLabel($questionRows, 'rule_kept'),
                    'rule_dismissed' => $this->questionLabel($questionRows, 'rule_dismissed'),
                    'operator_added' => $this->questionLabel($questionRows, 'operator_added'),
                    'unverified' => (int) ($unverifiedRow->unverified_needs_response ?? 0),
                ],
                'model_questions' => $this->modelQuestions($modelOpenedRow),
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
     * One C9′ row's counts, as a block carries them — read straight from the statement, cast to
     * int; a block with no row reads zero, and the blade shows nothing when `opened` is zero.
     *
     * @return array{opened: int, dismissed: int, kept: int, answered: int, unanswered: int, dismissed_not_a_question: int, dismissed_member_discussion: int, dismissed_message_removed: int, dismissed_other: int}
     */
    private function modelQuestions(?object $row): array
    {
        return [
            'opened' => (int) ($row->model_opened ?? 0),
            'dismissed' => (int) ($row->model_dismissed ?? 0),
            'kept' => (int) ($row->model_kept ?? 0),
            'answered' => (int) ($row->model_answered ?? 0),
            'unanswered' => (int) ($row->model_unanswered ?? 0),
            'dismissed_not_a_question' => (int) ($row->dismissed_not_a_question ?? 0),
            'dismissed_member_discussion' => (int) ($row->dismissed_member_discussion ?? 0),
            'dismissed_message_removed' => (int) ($row->dismissed_message_removed ?? 0),
            'dismissed_other' => (int) ($row->dismissed_other ?? 0),
        ];
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

    /**
     * C7: the rule set's own baseline, read per M19 — grouped by `rule_version`, with the
     * per-reason breakdown of `rule_dismissed` beside it (TG-M5.3 K7).
     */
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
                    'dismissed_not_a_question' => (int) $row->dismissed_not_a_question,
                    'dismissed_member_discussion' => (int) $row->dismissed_member_discussion,
                    'dismissed_message_removed' => (int) $row->dismissed_message_removed,
                    'dismissed_other' => (int) $row->dismissed_other,
                ];
            })
            ->filter(fn (array $row): bool => $row['rule_opened'] > 0 || $row['operator_added'] > 0)
            ->values();
    }

    /**
     * M19, amended by TG-M5.1: questions the model opened that nobody dismissed are rule misses
     * the model caught — they never reach the recall floor's operator-added count, so the floor
     * reads higher with AI-assisted opening on. A count of items (one per anchor), shown beside
     * the baseline; C9′'s rows, of both eras, are its only source — summing counts pools no rate.
     */
    public function modelKeptQuestions(): int
    {
        [$from, $to] = $this->periodBounds();

        return (int) collect($this->classificationModelOpenedQuestions($this->scopedChatId(), $from, $to))
            ->sum(fn (object $row): int => (int) $row->model_kept);
    }

    /**
     * TG-M5.3 K11, K12: one row's dismissal breakdown, as the page prints it — counts only.
     *
     * @param  array{dismissed_not_a_question: int, dismissed_member_discussion: int, dismissed_message_removed: int, dismissed_other: int}  $row
     */
    public function dismissalBreakdown(array $row): string
    {
        return __('not a real question :not_a_question · member discussion :member_discussion · message removed :message_removed · other :other', [
            'not_a_question' => $row['dismissed_not_a_question'],
            'member_discussion' => $row['dismissed_member_discussion'],
            'message_removed' => $row['dismissed_message_removed'],
            'other' => $row['dismissed_other'],
        ]);
    }

    /**
     * C10a (M26, M27): what happened to every message, for the attention judgement — one figure,
     * never grouped by model.
     */
    public function attentionVolume(): array
    {
        [$from, $to] = $this->periodBounds();

        return $this->attentionJudgementVolumeStats($this->scopedChatId(), $from, $to);
    }

    /**
     * C10c (M30-M32): the operator-added items opened in the period, one row per anchor status with
     * its single- and multi-message counts side by side — the statement's rows laid out, nothing
     * added or derived. Rows read judged asking first, then judged by intent, excluded by reason,
     * failed, and none.
     *
     * @return array<int, array{anchor_status: string, single: int, multi: int}>
     */
    public function attentionOperatorAdded(): array
    {
        [$from, $to] = $this->periodBounds();
        $rows = $this->attentionOperatorAddedStats(
            $this->scopedChatId(), $from, $to, (int) config('moderation.burst_gap_s'),
        );

        $rank = fn (string $status): int => match (true) {
            $status === 'judged_asking' => 0,
            str_starts_with($status, 'judged_') => 1,
            str_starts_with($status, 'excluded_') => 2,
            $status === 'failed' => 3,
            default => 4,
        };

        return collect($rows)
            ->groupBy('anchor_status')
            ->map(fn (Collection $group, string $status): array => [
                'anchor_status' => $status,
                'single' => (int) ($group->first(fn (object $r): bool => ! $r->multi_message)->items ?? 0),
                'multi' => (int) ($group->first(fn (object $r): bool => (bool) $r->multi_message)->items ?? 0),
            ])
            ->sortBy(fn (array $row): array => [$rank($row['anchor_status']), $row['anchor_status']])
            ->values()
            ->all();
    }

    /**
     * C10b (M28, M29) and C9′'s `attention` rows (M23′, M24): one block per `(model, attention
     * instruction)` seen in either for the current period and group — the union, as `blocks()`
     * does, since an item can open in the period from a judgement whose message was sent before it.
     * A model with neither has no block (M22). The gap is the panel's `MODERATION_BURST_GAP_S`
     * (`config('moderation.burst_gap_s')`).
     */
    public function attentionBlocks(): Collection
    {
        [$from, $to] = $this->periodBounds();
        $chatId = $this->scopedChatId();
        $gapS = (int) config('moderation.burst_gap_s');

        $intents = collect($this->attentionJudgementIntentStats($chatId, $from, $to, $gapS));
        $modelOpened = collect($this->classificationModelOpenedQuestions($chatId, $from, $to))
            ->filter(fn (object $r): bool => $r->era === 'attention');

        $keyOf = fn (int|string $modelProfileId, string $promptVersion): string => "{$modelProfileId}|{$promptVersion}";

        $keys = $intents->map(fn (object $r): string => $keyOf($r->model_profile_id, $r->prompt_version))
            ->merge($modelOpened->map(fn (object $r): string => $keyOf($r->model_profile_id, $r->prompt_version)))
            ->unique()
            ->values();

        return $keys->map(function (string $key) use ($intents, $modelOpened): array {
            [$modelProfileId, $promptVersion] = explode('|', $key, 2);
            $modelProfileId = (int) $modelProfileId;
            $profile = ModelProfile::find($modelProfileId);

            $matches = fn (object $r): bool => (int) $r->model_profile_id === $modelProfileId
                && $r->prompt_version === $promptVersion;
            $intentRow = $intents->first($matches);
            $modelOpenedRow = $modelOpened->first($matches);

            return [
                'model' => $profile?->name ?? __('(profile :id)', ['id' => $modelProfileId]),
                'prompt_version' => $promptVersion,
                'judgements' => [
                    'judged' => (int) ($intentRow->judged ?? 0),
                    'asking' => (int) ($intentRow->asking ?? 0),
                    'discussion' => (int) ($intentRow->discussion ?? 0),
                    'informing' => (int) ($intentRow->informing ?? 0),
                    'social' => (int) ($intentRow->social ?? 0),
                    'offering' => (int) ($intentRow->offering ?? 0),
                    'other' => (int) ($intentRow->other ?? 0),
                    'on_time' => (int) ($intentRow->on_time ?? 0),
                ],
                'model_questions' => $this->modelQuestions($modelOpenedRow),
            ];
        })->values();
    }

    /**
     * M29: one block's intent counts, as the page prints them — counts only, never ratios.
     *
     * @param  array{asking: int, discussion: int, informing: int, social: int, offering: int, other: int}  $judgements
     */
    public function intentBreakdown(array $judgements): string
    {
        return __('asking :asking · discussion :discussion · informing :informing · social :social · offering :offering · other :other', [
            'asking' => $judgements['asking'],
            'discussion' => $judgements['discussion'],
            'informing' => $judgements['informing'],
            'social' => $judgements['social'],
            'offering' => $judgements['offering'],
            'other' => $judgements['other'],
        ]);
    }

    /** A1, M21: "no labelled examples" over a zero denominator — never `0/0`. */
    public function ratio(int $numerator, int $denominator): string
    {
        return $denominator > 0 ? "{$numerator} / {$denominator}" : __('no labelled examples');
    }
}
