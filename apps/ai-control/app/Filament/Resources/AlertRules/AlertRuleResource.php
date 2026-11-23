<?php

namespace App\Filament\Resources\AlertRules;

use App\Filament\Resources\AlertRules\Pages\CreateAlertRule;
use App\Filament\Resources\AlertRules\Pages\EditAlertRule;
use App\Filament\Resources\AlertRules\Pages\ListAlertRules;
use App\Filament\Resources\AlertRules\Schemas\AlertRuleForm;
use App\Filament\Resources\AlertRules\Tables\AlertRulesTable;
use App\Models\AlertRule;
use BackedEnum;
use Filament\Resources\Resource;
use Filament\Schemas\Schema;
use Filament\Support\Icons\Heroicon;
use Filament\Tables\Table;
use UnitEnum;

/**
 * TG-M6 S1 (`specs/013-tg-m6-alerts/contracts/alerting.md` §7): list, create and edit alert rules.
 * There is no delete action anywhere on this resource — a rule is disabled, never deleted, and one
 * that has fired cannot be (FR-514, `RESTRICT`). The rules themselves live on `AlertRule`.
 */
class AlertRuleResource extends Resource
{
    protected static ?string $model = AlertRule::class;

    protected static string|BackedEnum|null $navigationIcon = Heroicon::OutlinedBellAlert;

    public static function getNavigationGroup(): string|UnitEnum|null
    {
        return __('Moderation Intelligence');
    }

    public static function getNavigationLabel(): string
    {
        return __('Alert Rules');
    }

    public static function getModelLabel(): string
    {
        return __('alert rule');
    }

    public static function getPluralModelLabel(): string
    {
        return __('alert rules');
    }

    public static function form(Schema $schema): Schema
    {
        return AlertRuleForm::configure($schema);
    }

    public static function table(Table $table): Table
    {
        return AlertRulesTable::configure($table);
    }

    public static function getPages(): array
    {
        return [
            'index' => ListAlertRules::route('/'),
            'create' => CreateAlertRule::route('/create'),
            'edit' => EditAlertRule::route('/{record}/edit'),
        ];
    }
}
