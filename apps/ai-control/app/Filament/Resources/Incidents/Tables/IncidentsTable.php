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
                    ->label('Group')
                    ->placeholder('(untitled)')
                    ->extraAttributes(['dir' => 'auto']),
                TextColumn::make('message')
                    ->label('Message')
                    ->getStateUsing(
                        fn (ModerationIncident $record): string => $record->anchorMessage()
                            ?->original_text ?? 'Text removed'
                    )
                    ->limit(80)
                    ->extraAttributes(['dir' => 'auto']),
                TextColumn::make('category')->badge(),
                TextColumn::make('severity')->badge(),
                // moderation_incident_state is the only definition of status (lifecycle
                // contract N6) — this reads it, never computes it.
                TextColumn::make('status')
                    ->getStateUsing(fn (ModerationIncident $record): ?string => $record->state()?->status)
                    ->badge(),
                TextColumn::make('responsibleModerator.display_name')
                    ->label('Responsible')
                    ->placeholder('Unassigned')
                    ->badge(),
                TextColumn::make('opened_at')->label('Posted')->dateTime()->sortable(),
                TextColumn::make('detected_at')->label('Flagged')->dateTime()->sortable(),
                TextColumn::make('age')
                    ->label('Age / took')
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
                    ->options(self::STATUSES)
                    ->query(fn (Builder $query, array $data): Builder => $query->when(
                        $data['value'] ?? null,
                        fn (Builder $q, string $status): Builder => $q->whereIn(
                            'id',
                            fn ($sub) => $sub->select('incident_id')
                                ->from('moderation_incident_state')
                                ->where('status', $status)
                        )
                    )),
                SelectFilter::make('category')->options(self::CATEGORIES),
                SelectFilter::make('severity')->options(self::SEVERITIES),
                SelectFilter::make('telegram_chat_id')
                    ->label('Group')
                    ->options(
                        fn (): array => TelegramChat::query()
                            ->orderBy('title')
                            ->get()
                            ->mapWithKeys(fn (TelegramChat $chat): array => [
                                $chat->id => $chat->title ?? '(untitled)',
                            ])
                            ->all()
                    ),
                SelectFilter::make('responsible_moderator_id')
                    ->label('Responsible')
                    ->options(fn (): array => Moderator::query()->orderBy('display_name')->pluck('display_name', 'id')->all()),
                Filter::make('detected_at')
                    ->label('Detection date')
                    ->schema([
                        DatePicker::make('from'),
                        DatePicker::make('until'),
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
            ->emptyStateHeading('No incidents opened yet')
            ->emptyStateDescription('Flag a message from here or from the Live Attention Queue.');
    }
}
