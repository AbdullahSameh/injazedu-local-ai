<?php

namespace App\Filament\Pages;

use App\Filament\Resources\Incidents\IncidentResource;
use App\Filament\Resources\TelegramChats\TelegramChatResource;
use App\Models\Alert;
use App\Models\AlertRule;
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
use Illuminate\Database\Eloquent\Builder;
use Illuminate\Support\Carbon;
use UnitEnum;

/**
 * TG-M6 S3 (`specs/013-tg-m6-alerts/contracts/alerting.md` §7, FR-572): every alert the evaluator
 * fired, newest first, ten to a page. Read-only — no edit, no resend, no bulk action; the panel
 * never calls Telegram (N10) and `Alert` refuses every write (S6). The status carries its
 * `not_sent` reason or its provider error category, never a message text (V7).
 */
class Alerts extends Page implements HasTable
{
    use InteractsWithTable;

    protected static string|BackedEnum|null $navigationIcon = Heroicon::OutlinedBell;

    protected string $view = 'filament.pages.alerts';

    public static function getNavigationGroup(): string|UnitEnum|null
    {
        return __('Moderation Intelligence');
    }

    public static function getNavigationLabel(): string
    {
        return __('Alerts');
    }

    public function getTitle(): string
    {
        return __('Alerts');
    }

    public function table(Table $table): Table
    {
        return $table
            ->query(Alert::query()->with(['rule', 'chat'])->withCount('acts'))
            ->columns([
                TextColumn::make('alert_rule_id')
                    ->label(__('Rule'))
                    ->formatStateUsing(fn (int $state): string => __('Rule #:id', ['id' => $state])),
                TextColumn::make('trigger')
                    ->label(__('Trigger'))
                    ->formatStateUsing(fn (string $state): string => AlertRule::triggerLabel($state))
                    ->badge(),
                TextColumn::make('group')
                    ->label(__('Group'))
                    ->getStateUsing(fn (Alert $record): string => $record->chat?->title
                        ?? __('Chat :id', ['id' => $record->chat?->chat_id]))
                    ->extraAttributes(['dir' => 'auto']),
                TextColumn::make('subject')
                    ->label(__('Subject'))
                    ->getStateUsing(fn (Alert $record): string => self::subjectText($record))
                    ->url(fn (Alert $record): ?string => self::subjectUrl($record))
                    ->color('primary'),
                TextColumn::make('repeat')
                    ->label(__('Repeat'))
                    ->getStateUsing(fn (Alert $record): string => $record->repeatText()),
                TextColumn::make('delivery_status')
                    ->label(__('Status'))
                    ->formatStateUsing(fn (Alert $record): string => $record->statusText())
                    ->badge()
                    ->color(fn (string $state): string => match ($state) {
                        'sent' => 'success',
                        'failed' => 'danger',
                        'not_sent', 'suppressed' => 'gray',
                        default => 'warning',
                    }),
                TextColumn::make('fired_at')
                    ->label(__('Fired'))
                    ->dateTime('Y-m-d H:i', 'Asia/Riyadh')
                    ->sortable(),
                TextColumn::make('delivered_at')
                    ->label(__('Delivered'))
                    ->dateTime('Y-m-d H:i', 'Asia/Riyadh')
                    ->placeholder('—'),
                TextColumn::make('acts_count')
                    ->label(__('Presses')),
            ])
            ->filters([
                SelectFilter::make('rule')
                    ->label(__('Rule'))
                    ->attribute('alert_rule_id')
                    ->options(fn (): array => AlertRule::query()
                        ->with('chat')
                        ->orderBy('id')
                        ->get()
                        ->mapWithKeys(fn (AlertRule $rule): array => [
                            $rule->id => __('Rule #:id', ['id' => $rule->id]).' · '.AlertRule::triggerLabel($rule->trigger)
                                .' · '.($rule->telegram_chat_id === null ? __('All groups') : ($rule->chat?->title ?? '#'.$rule->telegram_chat_id)),
                        ])
                        ->all()),
                SelectFilter::make('trigger')
                    ->label(__('Trigger'))
                    ->options(fn (): array => array_map(fn (string $label): string => __($label), AlertRule::TRIGGERS)),
                SelectFilter::make('group')
                    ->label(__('Group'))
                    ->attribute('telegram_chat_id')
                    ->options(fn (): array => TelegramChat::query()
                        ->whereIn('id', Alert::query()->select('telegram_chat_id'))
                        ->orderBy('title')
                        ->get()
                        ->mapWithKeys(fn (TelegramChat $chat): array => [
                            $chat->id => $chat->title ?? __('Chat :id', ['id' => $chat->chat_id]),
                        ])
                        ->all()),
                SelectFilter::make('status')
                    ->label(__('Status'))
                    ->attribute('delivery_status')
                    ->options(fn (): array => array_map(fn (string $label): string => __($label), Alert::STATUSES)),
                Filter::make('fired')
                    ->label(__('Fired'))
                    ->schema([
                        DatePicker::make('from')->label(__('From')),
                        DatePicker::make('until')->label(__('Until')),
                    ])
                    // `Asia/Riyadh` calendar days, as the half-open UTC bound `[from, until + 1 day)`.
                    ->query(fn (Builder $query, array $data): Builder => $query
                        ->when(filled($data['from'] ?? null), fn (Builder $q) => $q->where(
                            'fired_at', '>=', Carbon::parse($data['from'], 'Asia/Riyadh')->startOfDay()->utc()
                        ))
                        ->when(filled($data['until'] ?? null), fn (Builder $q) => $q->where(
                            'fired_at', '<', Carbon::parse($data['until'], 'Asia/Riyadh')->addDay()->startOfDay()->utc()
                        ))),
            ])
            ->defaultSort(fn (Builder $query): Builder => $query->orderByDesc('fired_at')->orderByDesc('id'))
            ->paginated([10])
            ->emptyStateHeading(__('No alerts yet'))
            ->emptyStateDescription(__('An alert appears here when an enabled rule fires, whether or not it was sent.'));
    }

    private static function subjectText(Alert $record): string
    {
        return match ($record->subject_type) {
            'incident' => __('Incident #:id', ['id' => $record->subject_id]),
            'attention_item' => __('Question #:id', ['id' => $record->subject_id]),
            default => __('The group'),
        };
    }

    /** The incident's page, the queue for a question, the group's page for a health alert. */
    private static function subjectUrl(Alert $record): ?string
    {
        return match ($record->subject_type) {
            'incident' => IncidentResource::getUrl('view', ['record' => $record->subject_id]),
            'attention_item' => LiveAttentionQueue::getUrl(),
            'chat' => TelegramChatResource::getUrl('edit', ['record' => $record->subject_id]),
            default => null,
        };
    }
}
