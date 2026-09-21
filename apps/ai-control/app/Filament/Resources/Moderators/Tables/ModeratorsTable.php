<?php

namespace App\Filament\Resources\Moderators\Tables;

use Filament\Actions\EditAction;
use Filament\Tables\Columns\IconColumn;
use Filament\Tables\Columns\TextColumn;
use Filament\Tables\Table;

/**
 * Display name (`dir="auto"`, D-TG-56) · platform id and handle · active · organisation
 * reference (`control-panel-moderation.md` §3, FR-047). No delete action — a moderator's record
 * and history are not discarded; deactivation (FR-030) is the retirement path.
 */
class ModeratorsTable
{
    public static function configure(Table $table): Table
    {
        return $table
            ->columns([
                TextColumn::make('display_name')
                    ->label('Name')
                    ->searchable()
                    ->extraAttributes(['dir' => 'auto']),
                TextColumn::make('telegramUser.tg_user_id')->label('Platform id'),
                TextColumn::make('telegramUser.username')
                    ->label('Handle')
                    ->placeholder('—')
                    ->formatStateUsing(fn (?string $state): ?string => $state ? "@{$state}" : null),
                IconColumn::make('is_active')->label('Active')->boolean()->sortable(),
                TextColumn::make('injaz_user_id')->label('Org reference')->placeholder('—'),
                TextColumn::make('updated_at')
                    ->dateTime()
                    ->sortable()
                    ->toggleable(isToggledHiddenByDefault: true),
            ])
            ->recordActions([
                EditAction::make(),
            ])
            ->defaultSort('display_name')
            ->emptyStateHeading('No moderators yet')
            ->emptyStateDescription(
                'Add one by a numeric platform id before they have posted, or from an '
                .'already-observed sender.'
            );
    }
}
