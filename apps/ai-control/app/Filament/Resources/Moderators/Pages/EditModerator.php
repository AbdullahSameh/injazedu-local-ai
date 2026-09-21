<?php

namespace App\Filament\Resources\Moderators\Pages;

use App\Filament\Resources\Moderators\ModeratorResource;
use Filament\Resources\Pages\EditRecord;

/**
 * No `DeleteAction` — a moderator's record, assignment history and every message flag already
 * written are not discarded (FR-030). Identity is set once, at creation, and is not editable
 * here.
 */
class EditModerator extends EditRecord
{
    protected static string $resource = ModeratorResource::class;

    protected function getHeaderActions(): array
    {
        return [
            //
        ];
    }
}
