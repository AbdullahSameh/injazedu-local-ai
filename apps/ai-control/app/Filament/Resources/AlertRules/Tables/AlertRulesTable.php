<?php

namespace App\Filament\Resources\AlertRules\Tables;

use App\Filament\Resources\Incidents\Support\IncidentDisplay;
use App\Models\AlertRule;
use Filament\Actions\EditAction;
use Filament\Tables\Columns\IconColumn;
use Filament\Tables\Columns\TextColumn;
use Filament\Tables\Table;

/**
 * Trigger · scope · threshold · filters · repeats · quiet hours · enabled and since when (TG-M6
 * S1). No delete action, bulk or otherwise — a rule is disabled, never deleted (FR-514).
 */
class AlertRulesTable
{
    public static function configure(Table $table): Table
    {
        return $table
            ->modifyQueryUsing(fn ($query) => $query->with('chat'))
            ->columns([
                TextColumn::make('trigger')
                    ->label(__('Trigger'))
                    ->formatStateUsing(fn (string $state): string => AlertRule::triggerLabel($state))
                    ->badge()
                    ->sortable(),
                TextColumn::make('scope')
                    ->label(__('Scope'))
                    ->getStateUsing(fn (AlertRule $record): string => $record->telegram_chat_id === null
                        ? __('All groups')
                        : ($record->chat?->title ?? __('Chat :id', ['id' => $record->chat?->chat_id])))
                    ->extraAttributes(['dir' => 'auto']),
                TextColumn::make('threshold_s')
                    ->label(__('Threshold'))
                    ->formatStateUsing(fn (?int $state): string => self::duration($state))
                    ->placeholder('—'),
                TextColumn::make('filters')
                    ->label(__('Filters'))
                    ->getStateUsing(fn (AlertRule $record): string => self::filters($record))
                    ->wrap(),
                TextColumn::make('repeats')
                    ->label(__('Repeats'))
                    ->getStateUsing(fn (AlertRule $record): string => $record->repeat_every_s === null
                        ? '—'
                        : __('Every :interval, up to :max', [
                            'interval' => self::duration($record->repeat_every_s),
                            'max' => $record->max_repeats,
                        ])),
                TextColumn::make('quiet_hours')
                    ->label(__('Quiet hours'))
                    ->getStateUsing(fn (AlertRule $record): string => collect($record->quiet_hours ?? [])
                        ->map(fn (array $window): string => ($window['from'] ?? '?').'–'.($window['to'] ?? '?'))
                        ->implode(', ') ?: '—'),
                IconColumn::make('is_enabled')->label(__('Enabled'))->boolean()->sortable(),
                TextColumn::make('enabled_at')
                    ->label(__('Enabled at'))
                    ->dateTime('Y-m-d H:i', 'Asia/Riyadh')
                    ->placeholder('—'),
            ])
            ->recordActions([
                EditAction::make(),
            ])
            ->defaultSort('trigger')
            ->emptyStateHeading(__('No alert rules yet'))
            ->emptyStateDescription(
                __('Nothing alerts until a rule exists and is enabled. Create one per trigger for all groups, then add a group\'s own rule where it should differ.')
            );
    }

    /** Whole minutes as "N min", or hours and minutes past an hour. */
    public static function duration(?int $seconds): string
    {
        if ($seconds === null) {
            return '—';
        }
        $minutes = intdiv($seconds, 60);
        if ($seconds % 60 !== 0) {
            return __(':n s', ['n' => $seconds]);
        }
        if ($minutes < 60 || $minutes % 60 !== 0) {
            return __(':n min', ['n' => $minutes]);
        }

        return __(':n h', ['n' => intdiv($minutes, 60)]);
    }

    private static function filters(AlertRule $record): string
    {
        if (! in_array($record->trigger, AlertRule::FILTER_TRIGGERS, true)) {
            return '—';
        }
        $parts = [];
        if ($record->min_severity !== null) {
            $parts[] = __('Severity at least :severity', ['severity' => __(ucfirst($record->min_severity))]);
        }
        if ($record->categories !== null) {
            $parts[] = collect($record->categories)->map(fn (string $code): string => __($code))->implode(', ');
        }
        if ($record->openers !== null) {
            $parts[] = collect($record->openers)->map(IncidentDisplay::openerLabel(...))->implode(', ');
        }

        return $parts === [] ? __('Any incident') : implode(' · ', $parts);
    }
}
