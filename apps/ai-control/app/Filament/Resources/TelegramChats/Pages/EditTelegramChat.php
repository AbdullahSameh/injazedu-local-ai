<?php

namespace App\Filament\Resources\TelegramChats\Pages;

use App\Filament\Resources\TelegramChats\TelegramChatResource;
use Filament\Notifications\Notification;
use Filament\Resources\Pages\EditRecord;

/**
 * No `DeleteAction` — a group's row is history, and deleting it would orphan messages and
 * assignments (`control-panel-moderation.md` §2, §4).
 *
 * TG-M6 D2/S2: switching on measurement for the alert destination is refused with a notification,
 * and nothing is saved; `TelegramChat` and `ck_chat_destination_not_monitored` back it.
 */
class EditTelegramChat extends EditRecord
{
    protected static string $resource = TelegramChatResource::class;

    protected function getHeaderActions(): array
    {
        return [
            //
        ];
    }

    protected function beforeSave(): void
    {
        if ($this->getRecord()->getAttribute('is_alert_destination') && ($this->data['is_monitored'] ?? false)) {
            Notification::make()
                ->danger()
                ->title(__('Not saved'))
                ->body(__('This chat is the alert destination, which is never measured. Stop using it as the destination first.'))
                ->send();

            $this->halt();
        }
    }
}
