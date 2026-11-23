<?php

namespace App\Filament\Resources\TelegramChats\Tables;

use App\Models\TelegramChat;
use Filament\Actions\Action;
use Filament\Actions\EditAction;
use Filament\Notifications\Notification;
use Filament\Support\Icons\Heroicon;
use Filament\Tables\Columns\IconColumn;
use Filament\Tables\Columns\TextColumn;
use Filament\Tables\Table;
use Illuminate\Validation\ValidationException;

/**
 * Platform identifier · kind · title (`dir="auto"`, D-TG-56) · bot standing and when observed ·
 * whether the bot may remove messages · when anything last happened · measured
 * (`control-panel-moderation.md` §2, FR-046, FR-051).
 *
 * No delete action, bulk or otherwise — a group's row is history (§4).
 *
 * Two coverage problems are distinguishable at a glance (FR-049), because both are silent by
 * nature: a measured group with nobody on its team (TG-M2.1), and a measured group whose bot is not
 * an administrator — the source plan calls the second the single most likely way the system
 * quietly stops working.
 *
 * TG-M6 S2: "Use as alert destination" on an unmeasured group the bot is in, "Stop using" on the
 * destination, and a badge naming it. Both delegate to `TelegramChat`, where D1-D2 live; the panel
 * never calls Telegram (N10).
 */
class TelegramChatsTable
{
    public static function configure(Table $table): Table
    {
        return $table
            ->columns([
                TextColumn::make('chat_id')->label(__('Chat ID'))->sortable(),
                TextColumn::make('chat_type')
                    ->label(__('Kind'))
                    ->formatStateUsing(fn (string $state): string => __($state))
                    ->badge(),
                TextColumn::make('title')
                    ->label(__('Title'))
                    ->searchable()
                    ->extraAttributes(['dir' => 'auto'])
                    ->placeholder(__('(untitled)')),
                TextColumn::make('bot_status')
                    ->label(__('Bot standing'))
                    ->formatStateUsing(fn (string $state): string => __($state))
                    ->badge()
                    ->description(fn ($record): ?string => $record->bot_status_at?->diffForHumans()),
                IconColumn::make('bot_can_delete')->label(__('Can delete'))->boolean(),
                TextColumn::make('last_event_at')->label(__('Last event'))->dateTime()->since()->sortable(),
                IconColumn::make('is_monitored')->label(__('Measured'))->boolean()->sortable(),
                TextColumn::make('destination')
                    ->label(__('Alerts'))
                    ->getStateUsing(fn (TelegramChat $record): ?string => $record->is_alert_destination
                        ? __('Alert destination')
                        : null)
                    ->badge()
                    ->color('warning')
                    ->placeholder('—'),
                // TG-M2.1 S4: the current team by name; a measured group with nobody on it is a
                // coverage problem, shown as a red "Nobody" (FR-049).
                TextColumn::make('team')
                    ->label(__('Team'))
                    ->getStateUsing(fn ($record): string => self::teamNames($record)
                        ?: ($record->is_monitored ? __('Nobody') : '—'))
                    ->badge()
                    ->color(fn ($record): string => (self::teamNames($record) === '' && $record->is_monitored)
                        ? 'danger'
                        : 'gray')
                    ->tooltip(fn ($record): ?string => ($record->is_monitored && self::teamNames($record) === '')
                        ? __('Measured with nobody on its team')
                        : null)
                    ->extraAttributes(['dir' => 'auto']),
                IconColumn::make('bot_is_admin')
                    ->label(__('Bot admin'))
                    ->state(fn ($record): bool => ! $record->is_monitored
                        || $record->bot_status === 'administrator')
                    ->boolean()
                    ->trueColor('success')
                    ->falseColor('danger')
                    ->tooltip(fn ($record): ?string => ($record->is_monitored
                        && $record->bot_status !== 'administrator')
                        ? __('Measured with the bot not an administrator — several event kinds silently stop arriving')
                        : null),
            ])
            ->recordActions([
                EditAction::make(),
                self::useAsDestination(),
                self::stopUsingAsDestination(),
            ])
            ->defaultSort('chat_id')
            ->emptyStateHeading(__('No groups captured yet'))
            ->emptyStateDescription(__('Groups appear here once the bot observes an event in them.'));
    }

    private static function useAsDestination(): Action
    {
        return Action::make('use_as_alert_destination')
            ->label(__('Use as alert destination'))
            ->icon(Heroicon::OutlinedBellAlert)
            ->visible(fn (TelegramChat $record): bool => $record->canBeAlertDestination())
            ->requiresConfirmation()
            ->modalDescription(function (): string {
                $current = TelegramChat::alertDestination();

                return $current === null
                    ? __('Alerts will be posted in this group. Nothing in it is ever measured.')
                    : __('Alerts will be posted in this group instead of :current. Nothing in it is ever measured.', [
                        'current' => $current->title ?? __('Chat :id', ['id' => $current->chat_id]),
                    ]);
            })
            ->action(function (TelegramChat $record): void {
                try {
                    $record->useAsAlertDestination();
                } catch (ValidationException $refused) {
                    self::refuse($refused);
                }
            });
    }

    private static function stopUsingAsDestination(): Action
    {
        return Action::make('stop_using_as_alert_destination')
            ->label(__('Stop using'))
            ->icon(Heroicon::OutlinedBellSlash)
            ->color('gray')
            ->visible(fn (TelegramChat $record): bool => (bool) $record->is_alert_destination)
            ->requiresConfirmation()
            ->modalDescription(__('Alerts stop being sent at once. Each alert fired meanwhile is recorded as not sent, for lack of a destination.'))
            ->action(fn (TelegramChat $record) => $record->stopUsingAsAlertDestination());
    }

    private static function refuse(ValidationException $refused): void
    {
        Notification::make()
            ->danger()
            ->title(__('Not saved'))
            ->body(collect($refused->errors())->flatten()->first())
            ->send();
    }

    /**
     * The group's current team members' names, comma-separated, or `''` when nobody is on it.
     */
    private static function teamNames($record): string
    {
        return $record->currentMemberships()
            ->with('moderator')
            ->get()
            ->map(fn ($membership): string => $membership->moderator?->display_name ?? '')
            ->filter()
            ->sort()
            ->implode(', ');
    }
}
