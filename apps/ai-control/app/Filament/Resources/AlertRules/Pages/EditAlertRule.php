<?php

namespace App\Filament\Resources\AlertRules\Pages;

use App\Filament\Resources\AlertRules\AlertRuleResource;
use App\Filament\Resources\AlertRules\Schemas\AlertRuleForm;
use Filament\Resources\Pages\EditRecord;
use Illuminate\Database\Eloquent\Model;

/**
 * No `DeleteAction`: a rule is disabled, never deleted (FR-514). The trigger and the scope are
 * fixed once created — another trigger or group is another rule.
 */
class EditAlertRule extends EditRecord
{
    protected static string $resource = AlertRuleResource::class;

    protected function getHeaderActions(): array
    {
        return [
            //
        ];
    }

    protected function handleRecordUpdate(Model $record, array $data): Model
    {
        $data['trigger'] = $record->getAttribute('trigger');

        return AlertRuleForm::refusingInPlace(
            fn (): Model => parent::handleRecordUpdate($record, AlertRuleForm::normalize($data))
        );
    }
}
