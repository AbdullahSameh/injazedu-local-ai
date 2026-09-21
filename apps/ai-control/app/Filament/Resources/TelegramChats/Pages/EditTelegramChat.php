<?php

namespace App\Filament\Resources\TelegramChats\Pages;

use App\Filament\Resources\TelegramChats\TelegramChatResource;
use Filament\Resources\Pages\EditRecord;

/**
 * No `DeleteAction` — a group's row is history, and deleting it would orphan messages and
 * assignments (`control-panel-moderation.md` §2, §4).
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
}
