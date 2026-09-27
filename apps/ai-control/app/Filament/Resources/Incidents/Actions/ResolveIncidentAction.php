<?php

namespace App\Filament\Resources\Incidents\Actions;

use App\Models\ModerationIncident;
use App\Models\User;
use Filament\Actions\Action;
use Filament\Forms\Components\Textarea;
use Illuminate\Support\Facades\Auth;

/**
 * `contracts/incident-lifecycle.md` §5 H1: allowed from `open` or `acknowledged`, a required
 * note. The guarded insert lives on `ModerationIncident::resolve()`; this action is the form, the
 * helper text of `control-panel-incidents.md` §3, and the visibility rule.
 */
class ResolveIncidentAction
{
    public static function make(): Action
    {
        return Action::make('resolve_incident')
            ->label('Resolve')
            ->schema([
                Textarea::make('note')
                    ->label('Note')
                    ->required()
                    ->helperText(
                        'Record what you were told or saw. This is recorded as your '
                            .'confirmation, not as something Telegram reported.'
                    ),
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
                $record->resolve($user, $data['note']);
            });
    }
}
