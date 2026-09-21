<?php

namespace App\Filament\Resources\Moderators;

use App\Filament\Resources\Moderators\Pages\CreateModerator;
use App\Filament\Resources\Moderators\Pages\EditModerator;
use App\Filament\Resources\Moderators\Pages\ListModerators;
use App\Filament\Resources\Moderators\RelationManagers\AssignmentsRelationManager;
use App\Filament\Resources\Moderators\Schemas\ModeratorForm;
use App\Filament\Resources\Moderators\Tables\ModeratorsTable;
use App\Models\Moderator;
use BackedEnum;
use Filament\Resources\Resource;
use Filament\Schemas\Schema;
use Filament\Support\Icons\Heroicon;
use Filament\Tables\Table;
use UnitEnum;

/**
 * Moderators are declared, never read live from the platform's administrator list (FR-031).
 * Ownership history lives on `AssignmentsRelationManager`, not a resource of its own
 * (`control-panel-moderation.md` §3, D-TG-66).
 */
class ModeratorResource extends Resource
{
    protected static ?string $model = Moderator::class;

    protected static string|BackedEnum|null $navigationIcon = Heroicon::OutlinedUserGroup;

    protected static string|UnitEnum|null $navigationGroup = 'Moderation Intelligence';

    public static function form(Schema $schema): Schema
    {
        return ModeratorForm::configure($schema);
    }

    public static function table(Table $table): Table
    {
        return ModeratorsTable::configure($table);
    }

    public static function getRelations(): array
    {
        return [
            AssignmentsRelationManager::class,
        ];
    }

    public static function getPages(): array
    {
        return [
            'index' => ListModerators::route('/'),
            'create' => CreateModerator::route('/create'),
            'edit' => EditModerator::route('/{record}/edit'),
        ];
    }
}
