<?php

namespace App\Filament\Resources\Users\Tables;

use Filament\Actions\EditAction;
use Filament\Tables\Columns\IconColumn;
use Filament\Tables\Columns\TextColumn;
use Filament\Tables\Table;

/**
 * Name · email · panel access · the moderator the account is linked to, if any. No delete and no
 * bulk action (`UserResource`).
 */
class UsersTable
{
    public static function configure(Table $table): Table
    {
        return $table
            ->columns([
                TextColumn::make('name')
                    ->label(__('Name'))
                    ->searchable()
                    ->extraAttributes(['dir' => 'auto']),
                TextColumn::make('email')
                    ->label(__('Email'))
                    ->searchable(),
                IconColumn::make('is_panel_operator')
                    ->label(__('Panel access'))
                    ->boolean()
                    ->sortable(),
                TextColumn::make('moderator.display_name')
                    ->label(__('Moderator'))
                    ->placeholder('—')
                    ->extraAttributes(['dir' => 'auto']),
                TextColumn::make('created_at')
                    ->label(__('Created at'))
                    ->dateTime()
                    ->sortable(),
            ])
            ->recordActions([
                EditAction::make(),
            ])
            ->defaultSort('name');
    }
}
