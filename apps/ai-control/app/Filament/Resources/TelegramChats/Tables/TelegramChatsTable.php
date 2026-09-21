<?php

namespace App\Filament\Resources\TelegramChats\Tables;

use Filament\Actions\EditAction;
use Filament\Tables\Columns\IconColumn;
use Filament\Tables\Columns\TextColumn;
use Filament\Tables\Table;

/**
 * Platform identifier · kind · title (`dir="auto"`, D-TG-56) · bot standing and when observed ·
 * whether the bot may remove messages · when anything last happened · measured
 * (`control-panel-moderation.md` §2, FR-046, FR-051).
 *
 * No delete action, bulk or otherwise — a group's row is history (§4).
 *
 * Two coverage problems are distinguishable at a glance (FR-049), because both are silent by
 * nature: a measured group with no current primary owner, and a measured group whose bot is not
 * an administrator — the source plan calls the second the single most likely way the system
 * quietly stops working.
 */
class TelegramChatsTable
{
    public static function configure(Table $table): Table
    {
        return $table
            ->columns([
                TextColumn::make('chat_id')->label('Chat ID')->sortable(),
                TextColumn::make('chat_type')->label('Kind')->badge(),
                TextColumn::make('title')
                    ->searchable()
                    ->extraAttributes(['dir' => 'auto'])
                    ->placeholder('(untitled)'),
                TextColumn::make('bot_status')
                    ->label('Bot standing')
                    ->badge()
                    ->description(fn ($record): ?string => $record->bot_status_at?->diffForHumans()),
                IconColumn::make('bot_can_delete')->label('Can delete')->boolean(),
                TextColumn::make('last_event_at')->label('Last event')->dateTime()->since()->sortable(),
                IconColumn::make('is_monitored')->label('Measured')->boolean()->sortable(),
                IconColumn::make('has_current_owner')
                    ->label('Owner')
                    ->state(fn ($record): bool => ! $record->is_monitored
                        || $record->currentPrimaryAssignment()->exists())
                    ->boolean()
                    ->trueColor('success')
                    ->falseColor('danger')
                    ->tooltip(fn ($record): ?string => ($record->is_monitored
                        && ! $record->currentPrimaryAssignment()->exists())
                        ? 'Measured with no current primary owner'
                        : null),
                IconColumn::make('bot_is_admin')
                    ->label('Bot admin')
                    ->state(fn ($record): bool => ! $record->is_monitored
                        || $record->bot_status === 'administrator')
                    ->boolean()
                    ->trueColor('success')
                    ->falseColor('danger')
                    ->tooltip(fn ($record): ?string => ($record->is_monitored
                        && $record->bot_status !== 'administrator')
                        ? 'Measured with the bot not an administrator — several event kinds '
                            .'silently stop arriving'
                        : null),
            ])
            ->recordActions([
                EditAction::make(),
            ])
            ->defaultSort('chat_id')
            ->emptyStateHeading('No groups captured yet')
            ->emptyStateDescription('Groups appear here once the bot observes an event in them.');
    }
}
