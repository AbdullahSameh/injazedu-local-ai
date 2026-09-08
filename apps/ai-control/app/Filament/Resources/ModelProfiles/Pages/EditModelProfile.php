<?php

namespace App\Filament\Resources\ModelProfiles\Pages;

use App\Filament\Resources\ModelProfiles\ModelProfileResource;
use Filament\Actions\DeleteAction;
use Filament\Resources\Pages\EditRecord;

class EditModelProfile extends EditRecord
{
    protected static string $resource = ModelProfileResource::class;

    protected function getHeaderActions(): array
    {
        return [
            DeleteAction::make(),
        ];
    }
}
