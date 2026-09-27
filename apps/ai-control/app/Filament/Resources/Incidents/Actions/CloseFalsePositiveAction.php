<?php

namespace App\Filament\Resources\Incidents\Actions;

use App\Models\ModerationIncident;
use App\Models\User;
use Filament\Actions\Action;
use Filament\Forms\Components\Textarea;
use Illuminate\Support\Facades\Auth;

/**
 * `contracts/incident-lifecycle.md` §5 H1: allowed from `open` or `acknowledged`, a required
 * reason. The guarded insert lives on `ModerationIncident::closeAsFalsePositive()`; this action is
 * the form and the visibility rule (`control-panel-incidents.md` §3).
 */
class CloseFalsePositiveAction
{
    public static function make(): Action
    {
        return Action::make('close_false_positive')
            ->label('Not a violation')
            ->color('gray')
            ->schema([
                Textarea::make('reason')
                    ->label('Reason')
                    ->required(),
            ])
            ->visible(
                fn (ModerationIncident $record): bool => in_array(
                    $record->state()?->status,
                    ['open', 'acknowledged'],
                    true,
                )
            )
            ->action(function (array $data, ModerationIncident $record): void {
                /** @var User $user */
                $user = Auth::user();
                $record->closeAsFalsePositive($user, $data['reason']);
            });
    }
}
