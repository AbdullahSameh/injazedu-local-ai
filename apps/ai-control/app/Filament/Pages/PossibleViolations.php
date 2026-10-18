<?php

namespace App\Filament\Pages;

use App\Filament\Pages\Concerns\ClassificationMetrics;
use App\Filament\Resources\Incidents\Actions\OpenIncidentAction;
use App\Filament\Support\ModelView;
use App\Models\ModelProfile;
use App\Models\TelegramChat;
use BackedEnum;
use Filament\Forms\Components\DatePicker;
use Filament\Pages\Page;
use Filament\Support\Icons\Heroicon;
use Filament\Tables\Columns\TextColumn;
use Filament\Tables\Concerns\InteractsWithTable;
use Filament\Tables\Contracts\HasTable;
use Filament\Tables\Filters\Filter;
use Filament\Tables\Filters\SelectFilter;
use Filament\Tables\Table;
use Illuminate\Support\Carbon;
use Illuminate\Support\Collection;
use UnitEnum;

/**
 * `control-panel-classification.md` §3 — live predictions routed `possible_violation` whose
 * message anchors no incident yet: not confident or consistent enough for the model to open one
 * on its own, waiting for a person. Read-only: the one row action opens an operator incident
 * through TG-M4's own guarded write and records it as list-prompted; there is no dismissal, no
 * relabel, no bulk action and no model call anywhere on this page (V3).
 *
 * Rows come straight from `ClassificationMetrics::possibleViolations()` — C4, quoted verbatim —
 * as plain arrays, never a second, parallel Eloquent query re-deriving the same membership (N7):
 * membership is read, never stored, so a row leaves the list the instant its message anchors an
 * incident, whoever opened it.
 */
class PossibleViolations extends Page implements HasTable
{
    use ClassificationMetrics;
    use InteractsWithTable;

    protected static string|BackedEnum|null $navigationIcon = Heroicon::OutlinedShieldExclamation;

    public static function getNavigationGroup(): string|UnitEnum|null
    {
        return __('Moderation Intelligence');
    }

    public static function getNavigationLabel(): string
    {
        return __('Possible Violations');
    }

    public function getTitle(): string
    {
        return __('Possible Violations');
    }

    protected string $view = 'filament.pages.possible-violations';

    public function table(Table $table): Table
    {
        if (! $this->hasActiveClassificationModel()) {
            return $table
                ->records(fn (): Collection => collect())
                ->columns([])
                ->emptyStateHeading(__('No classification model is active'))
                ->emptyStateDescription(
                    __('Activate a moderation model in the Model Profiles roster to start listing possible violations.')
                );
        }

        return $table
            ->records(function (array $filters, ?string $sortDirection): Collection {
                $chatId = $filters['group']['value'] ?? null;
                [$from, $to] = $this->periodBounds($filters['posted'] ?? []);

                $rows = collect($this->possibleViolations($chatId !== null ? (int) $chatId : null, $from, $to))
                    ->map(fn (object $row): array => (array) $row + ['__key' => (string) $row->id]);

                // C4 already orders newest posting first (V1); "Posted" is the only sortable
                // column, so oldest first is that same order reversed — never a second query.
                return $sortDirection === 'asc' ? $rows->reverse()->values() : $rows;
            })
            ->columns([
                TextColumn::make('group')
                    ->label(__('Group'))
                    ->getStateUsing(
                        fn (array $record): string => TelegramChat::find($record['telegram_chat_id'])?->title
                            ?? __('(untitled)')
                    )
                    ->extraAttributes(['dir' => 'auto']),
                TextColumn::make('message')
                    ->label(__('Message'))
                    ->getStateUsing(
                        fn (array $record): string => $record['original_text'] ?? __('Text removed')
                    )
                    ->limit(80)
                    ->extraAttributes(['dir' => 'auto']),
                TextColumn::make('posted')
                    ->label(__('Posted'))
                    ->getStateUsing(
                        fn (array $record): string => Carbon::parse($record['sent_at'])
                            ->setTimezone('Asia/Riyadh')
                            ->format('Y-m-d H:i')
                    )
                    ->sortable(),
                TextColumn::make('model_view')
                    ->label(__("Model's view"))
                    ->getStateUsing(
                        fn (array $record): string => sprintf(
                            '%s · %s · %s',
                            __($record['category']),
                            __($record['severity']),
                            ModelView::confidence($record['confidence']),
                        )
                    ),
                TextColumn::make('why_listed')
                    ->label(__('Why listed'))
                    ->getStateUsing(
                        fn (array $record): string => match ($record['route_reason']) {
                            'inconsistent' => __('Inconsistent'),
                            // R4b (2026-10-18): an advert reading with nothing pointing outside.
                            'no_contact_signal' => __('No link, phone or handle'),
                            default => __('Uncertain'),
                        }
                    )
                    ->badge(),
                TextColumn::make('model')
                    ->label(__('Model'))
                    ->getStateUsing(
                        fn (array $record): string => sprintf('%s · %s', $record['model'], $record['prompt_version'])
                    ),
            ])
            ->filters([
                SelectFilter::make('group')
                    ->label(__('Group'))
                    ->options(
                        fn (): array => TelegramChat::query()
                            ->orderBy('title')
                            ->get()
                            ->mapWithKeys(fn (TelegramChat $chat): array => [
                                $chat->id => $chat->title ?? __('(untitled)'),
                            ])
                            ->all()
                    ),
                Filter::make('posted')
                    ->label(__('Posted'))
                    ->schema([
                        DatePicker::make('from')->label(__('From')),
                        DatePicker::make('until')->label(__('Until')),
                    ]),
            ])
            ->recordActions([
                OpenIncidentAction::forPossibleViolationRow(),
            ])
            ->defaultSort('posted', 'desc')
            ->emptyStateHeading(__('Nothing listed'))
            ->emptyStateDescription(
                __('A message appears here when the model thinks it may need moderation but is not confident or consistent enough to open an incident.')
            );
    }

    private function hasActiveClassificationModel(): bool
    {
        return ModelProfile::query()->where('role', 'moderation')->where('is_active', true)->exists();
    }

    /**
     * Reads the "Posted" filter's `from`/`until` in `Asia/Riyadh` calendar days, converted to the
     * half-open `[from, to)` UTC bound `possibleViolations()` expects (K1) — an open range by
     * default, so the list shows every currently-listed row rather than only a recent window.
     *
     * @param  array{from?: string|null, until?: string|null}  $posted
     * @return array{0: Carbon, 1: Carbon}
     */
    private function periodBounds(array $posted): array
    {
        $from = filled($posted['from'] ?? null)
            ? Carbon::parse($posted['from'], 'Asia/Riyadh')->startOfDay()->utc()
            : Carbon::createFromTimestamp(0)->utc();
        $to = filled($posted['until'] ?? null)
            ? Carbon::parse($posted['until'], 'Asia/Riyadh')->addDay()->startOfDay()->utc()
            : now()->addDay();

        return [$from, $to];
    }
}
