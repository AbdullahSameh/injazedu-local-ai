<?php

namespace App\Filament\Resources\TelegramChats\Pages;

use App\Filament\Resources\TelegramChats\TelegramChatResource;
use Filament\Resources\Pages\ListRecords;

/**
 * No `CreateAction` in the header — groups are discovered by capture, never typed in (FR-046).
 */
class ListTelegramChats extends ListRecords
{
    protected static string $resource = TelegramChatResource::class;

    protected function getHeaderActions(): array
    {
        return [
            //
        ];
    }
}
