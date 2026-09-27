<?php

namespace App\Filament\Resources\Incidents\Pages;

use App\Filament\Resources\Incidents\Actions\AcknowledgeIncidentAction;
use App\Filament\Resources\Incidents\Actions\CloseFalsePositiveAction;
use App\Filament\Resources\Incidents\Actions\ResolveIncidentAction;
use App\Filament\Resources\Incidents\IncidentResource;
use Filament\Resources\Pages\ViewRecord;

/**
 * T054 (US5): the six questions of `control-panel-incidents.md` §1.2, rendered by
 * `Schemas\IncidentInfolist`. Header actions reuse US4's three guarded acts — the same classes
 * the list's rows already offer — bound to this page's own record.
 */
class ViewIncident extends ViewRecord
{
    protected static string $resource = IncidentResource::class;

    protected string $view = 'filament.resources.incidents.pages.view-incident';

    protected function getHeaderActions(): array
    {
        return [
            AcknowledgeIncidentAction::make()->record($this->getRecord()),
            ResolveIncidentAction::make()->record($this->getRecord()),
            CloseFalsePositiveAction::make()->record($this->getRecord()),
        ];
    }
}
