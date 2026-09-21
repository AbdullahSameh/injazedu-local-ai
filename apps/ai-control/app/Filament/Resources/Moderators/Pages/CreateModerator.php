<?php

namespace App\Filament\Resources\Moderators\Pages;

use App\Filament\Resources\Moderators\ModeratorResource;
use App\Filament\Resources\Moderators\Schemas\ModeratorForm;
use Filament\Resources\Pages\CreateRecord;

/**
 * Resolves the form's "observed identity" / "not-yet-observed numeric id" choice to a
 * `telegram_users.id` surrogate before the `Moderator` row is created — `ModeratorForm::
 * resolveTelegramUserId` is the one place that logic lives (FR-027, D-TG-52).
 */
class CreateModerator extends CreateRecord
{
    protected static string $resource = ModeratorResource::class;

    protected function mutateFormDataBeforeCreate(array $data): array
    {
        $data['telegram_user_id'] = ModeratorForm::resolveTelegramUserId($data);

        unset($data['identity_source'], $data['existing_telegram_user_id'], $data['tg_user_id']);

        return $data;
    }
}
