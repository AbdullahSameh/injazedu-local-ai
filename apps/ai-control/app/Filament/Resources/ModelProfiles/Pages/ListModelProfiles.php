<?php

namespace App\Filament\Resources\ModelProfiles\Pages;

use App\Filament\Resources\ModelProfiles\ModelProfileResource;
use Filament\Actions\CreateAction;
use Filament\Resources\Pages\ListRecords;

class ListModelProfiles extends ListRecords
{
    protected static string $resource = ModelProfileResource::class;

    protected function getHeaderActions(): array
    {
        return [
            CreateAction::make(),
        ];
    }
}
