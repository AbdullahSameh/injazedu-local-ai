<?php

namespace App\Filament\Resources\Moderators\Pages;

use App\Filament\Resources\Moderators\ModeratorResource;
use Filament\Actions\CreateAction;
use Filament\Resources\Pages\ListRecords;

class ListModerators extends ListRecords
{
    protected static string $resource = ModeratorResource::class;

    protected function getHeaderActions(): array
    {
        return [
            CreateAction::make(),
        ];
    }
}
