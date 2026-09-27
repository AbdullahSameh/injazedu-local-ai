<?php

namespace App\Filament\Resources\Incidents;

use App\Filament\Resources\Incidents\Pages\ListIncidents;
use App\Filament\Resources\Incidents\Pages\ViewIncident;
use App\Filament\Resources\Incidents\Schemas\IncidentInfolist;
use App\Filament\Resources\Incidents\Tables\IncidentsTable;
use App\Models\ModerationIncident;
use BackedEnum;
use Filament\Resources\Resource;
use Filament\Schemas\Schema;
use Filament\Support\Icons\Heroicon;
use Filament\Tables\Table;
use UnitEnum;

/**
 * List and view only (`control-panel-incidents.md` §1) — no create, edit or delete page: an
 * incident is opened by `OpenIncidentAction`, its labels are never edited, and it is never
 * deleted (D-TG-123).
 */
class IncidentResource extends Resource
{
    protected static ?string $model = ModerationIncident::class;

    protected static string|BackedEnum|null $navigationIcon = Heroicon::OutlinedShieldExclamation;

    protected static string|UnitEnum|null $navigationGroup = 'Moderation Intelligence';

    protected static ?string $navigationLabel = 'Incidents';

    public static function table(Table $table): Table
    {
        return IncidentsTable::configure($table);
    }

    public static function infolist(Schema $schema): Schema
    {
        return IncidentInfolist::configure($schema);
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
            'index' => ListIncidents::route('/'),
            'view' => ViewIncident::route('/{record}'),
        ];
    }
}
