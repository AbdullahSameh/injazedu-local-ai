<?php

namespace App\Filament\Resources\Incidents\Actions;

use App\Models\ModerationIncident;
use App\Models\User;
use Filament\Actions\Action;
use Illuminate\Support\Facades\Auth;

/**
 * `contracts/incident-lifecycle.md` §5 H1: allowed only from `open`. The guarded insert lives on
 * `ModerationIncident::acknowledge()`, not here — this action is only the confirmation dialog and
 * the visibility rule (`control-panel-incidents.md` §3).
 */
class AcknowledgeIncidentAction
{
    public static function make(): Action
    {
        return Action::make('acknowledge_incident')
            ->label('Acknowledge')
            ->requiresConfirmation()
            ->visible(
                fn (ModerationIncident $record): bool => $record->state()?->status === 'open'
            )
            ->action(function (ModerationIncident $record): void {
                /** @var User $user */
                $user = Auth::user();
                $record->acknowledge($user);
            });
    }
}
