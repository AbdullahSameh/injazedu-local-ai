<?php

namespace App\Filament\Resources\Incidents\Tables;

use App\Filament\Resources\Incidents\Actions\AcknowledgeIncidentAction;
use App\Filament\Resources\Incidents\Actions\CloseFalsePositiveAction;
use App\Filament\Resources\Incidents\Actions\OpenIncidentAction;
use App\Filament\Resources\Incidents\Actions\ResolveIncidentAction;
use App\Filament\Resources\Incidents\IncidentResource;
use App\Filament\Resources\Incidents\Support\IncidentDisplay;
use App\Models\ModerationIncident;
use App\Models\Moderator;
use App\Models\TelegramChat;
use Filament\Forms\Components\DatePicker;
use Filament\Tables\Columns\TextColumn;
use Filament\Tables\Filters\Filter;
use Filament\Tables\Filters\SelectFilter;
use Filament\Tables\Table;
use Illuminate\Database\Eloquent\Builder;
use Illuminate\Support\Carbon;

/**
 * Group · Message · Category · Severity · Status (read from `moderation_incident_state`, never
 * computed here) · Responsible (**Unassigned** badge when NULL) · Posted · Flagged · Age/took
 * (`control-panel-incidents.md` §1.1, T057). Filters: status, category, severity, group,
 * responsible moderator, detection date range (P1). No bulk action anywhere (FR-038); no
 * create/edit/delete page on the resource — an incident is opened by an action and never edited
 * or deleted.
 */
class IncidentsTable
{
    private const STATUSES = [
        'open' => 'Open',
        'acknowledged' => 'Acknowledged',
        'resolved' => 'Resolved',
        'closed_false_positive' => 'Closed (false positive)',
    ];

    private const CATEGORIES = [
        'SPAM_OR_AD' => 'Spam or ad',
        'ABUSE' => 'Abuse',
        'OTHER' => 'Other',
    ];

    private const SEVERITIES = [
        'low' => 'Low',
        'medium' => 'Medium',
        'high' => 'High',
    ];

    public static function configure(Table $table): Table
    {
        return $table
            ->query(ModerationIncident::query())
            ->recordUrl(
                fn (ModerationIncident $record): string => IncidentResource::getUrl('view', ['record' => $record])
            )
            ->columns([
                TextColumn::make('chat.title')
                    ->label(__('Group'))
                    ->placeholder(__('(untitled)'))
                    ->extraAttributes(['dir' => 'auto']),
                TextColumn::make('message')
                    ->label(__('Message'))
                    ->getStateUsing(
                        fn (ModerationIncident $record): string => $record->anchorMessage()
                            ?->original_text ?? __('Text removed')
                    )
                    ->limit(80)
                    ->extraAttributes(['dir' => 'auto']),
                TextColumn::make('category')
                    ->label(__('Category'))
                    ->formatStateUsing(fn (string $state): string => __($state))
                    ->badge(),
                TextColumn::make('severity')
                    ->label(__('Severity'))
                    ->formatStateUsing(fn (string $state): string => __($state))
                    ->badge(),
                // L1 (`control-panel-classification.md` §2.2): "Operator", "Model" or "Link rule"
                // — read straight from `source`, never recomputed (P2).
                TextColumn::make('source')
                    ->label(__('Opened by'))
                    ->formatStateUsing(fn (string $state): string => IncidentDisplay::openerLabel($state))
                    ->badge(),
                // moderation_incident_state is the only definition of status (lifecycle
                // contract N6) — this reads it, never computes it.
                TextColumn::make('status')
                    ->label(__('Status'))
                    ->getStateUsing(fn (ModerationIncident $record): ?string => $record->state()?->status)
                    ->formatStateUsing(fn (string $state): string => __($state))
                    ->badge(),
                TextColumn::make('responsibleModerator.display_name')
                    ->label(__('Responsible'))
                    ->placeholder(__('Unassigned'))
                    ->badge(),
                TextColumn::make('opened_at')->label(__('Posted'))->dateTime()->sortable(),
                TextColumn::make('detected_at')->label(__('Flagged'))->dateTime()->sortable(),
                TextColumn::make('age')
                    ->label(__('Age / took'))
                    ->getStateUsing(function (ModerationIncident $record): string {
                        $state = $record->state();

                        return IncidentDisplay::ageOrTook(
                            $state?->status,
                            $record->detected_at,
                            $state?->resolved_at !== null ? Carbon::parse($state->resolved_at) : null,
                            $state?->closed_at !== null ? Carbon::parse($state->closed_at) : null,
                        );
                    }),
            ])
            ->filters([
                SelectFilter::make('status')
                    ->label(__('Status'))
                    ->options(array_map(__(...), self::STATUSES))
                    ->query(fn (Builder $query, array $data): Builder => $query->when(
                        $data['value'] ?? null,
                        fn (Builder $q, string $status): Builder => $q->whereIn(
                            'id',
                            fn ($sub) => $sub->select('incident_id')
                                ->from('moderation_incident_state')
                                ->where('status', $status)
                        )
                    )),
                SelectFilter::make('category')
                    ->label(__('Category'))
                    ->options(array_map(__(...), self::CATEGORIES)),
                // L2: the same values as the column above.
                SelectFilter::make('source')
                    ->label(__('Opened by'))
                    ->options(array_combine(
                        ['operator', 'ai', 'rule'],
                        array_map(IncidentDisplay::openerLabel(...), ['operator', 'ai', 'rule']),
                    )),
                SelectFilter::make('severity')
                    ->label(__('Severity'))
                    ->options(array_map(__(...), self::SEVERITIES)),
                SelectFilter::make('telegram_chat_id')
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
                SelectFilter::make('responsible_moderator_id')
                    ->label(__('Responsible'))
                    ->options(fn (): array => Moderator::query()->orderBy('display_name')->pluck('display_name', 'id')->all()),
                Filter::make('detected_at')
                    ->label(__('Detection date'))
                    ->schema([
                        DatePicker::make('from')->label(__('From')),
                        DatePicker::make('until')->label(__('Until')),
                    ])
                    ->query(fn (Builder $query, array $data): Builder => $query
                        ->when(
                            $data['from'] ?? null,
                            fn (Builder $q, string $from): Builder => $q->whereDate('detected_at', '>=', $from)
                        )
                        ->when(
                            $data['until'] ?? null,
                            fn (Builder $q, string $until): Builder => $q->whereDate('detected_at', '<=', $until)
                        )),
            ])
            ->headerActions([
                OpenIncidentAction::forList(),
            ])
            ->recordActions([
                AcknowledgeIncidentAction::make(),
                ResolveIncidentAction::make(),
                CloseFalsePositiveAction::make(),
            ])
            ->defaultSort('detected_at', 'desc')
            ->emptyStateHeading(__('No incidents opened yet'))
            ->emptyStateDescription(__('Flag a message from here or from the Live Attention Queue.'));
    }
}
