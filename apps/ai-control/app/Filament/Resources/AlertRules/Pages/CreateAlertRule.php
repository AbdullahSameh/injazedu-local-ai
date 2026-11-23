<?php

namespace App\Filament\Resources\AlertRules\Pages;

use App\Filament\Resources\AlertRules\AlertRuleResource;
use App\Filament\Resources\AlertRules\Schemas\AlertRuleForm;
use Illuminate\Database\Eloquent\Model;
use Filament\Resources\Pages\CreateRecord;

/**
 * The model refuses what R1-R8 refuse; `AlertRuleForm::refusingInPlace` shows each refusal under
 * its field.
 */
class CreateAlertRule extends CreateRecord
{
    protected static string $resource = AlertRuleResource::class;

    protected function handleRecordCreation(array $data): Model
    {
        return AlertRuleForm::refusingInPlace(
            fn (): Model => parent::handleRecordCreation(AlertRuleForm::normalize($data))
        );
    }
}
