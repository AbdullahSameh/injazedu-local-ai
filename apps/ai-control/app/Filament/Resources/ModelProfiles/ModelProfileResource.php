<?php

namespace App\Filament\Resources\ModelProfiles;

use App\Filament\Resources\ModelProfiles\Pages\CreateModelProfile;
use App\Filament\Resources\ModelProfiles\Pages\EditModelProfile;
use App\Filament\Resources\ModelProfiles\Pages\ListModelProfiles;
use App\Filament\Resources\ModelProfiles\Schemas\ModelProfileForm;
use App\Filament\Resources\ModelProfiles\Tables\ModelProfilesTable;
use App\Models\ModelProfile;
use BackedEnum;
use Filament\Resources\Resource;
use Filament\Schemas\Schema;
use Filament\Support\Icons\Heroicon;
use Filament\Tables\Table;

class ModelProfileResource extends Resource
{
    protected static ?string $model = ModelProfile::class;

    protected static string|BackedEnum|null $navigationIcon = Heroicon::OutlinedRectangleStack;

    public static function form(Schema $schema): Schema
    {
        return ModelProfileForm::configure($schema);
    }

    public static function table(Table $table): Table
    {
        return ModelProfilesTable::configure($table);
    }

    public static function getRelations(): array
    {
        return [
            //
        ];
    }

    public static function getPages(): array
    {
        return [
            'index' => ListModelProfiles::route('/'),
            'create' => CreateModelProfile::route('/create'),
            'edit' => EditModelProfile::route('/{record}/edit'),
        ];
    }
}
