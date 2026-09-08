<?php

namespace App\Filament\Resources\ModelProfiles\Tables;

use Filament\Actions\BulkActionGroup;
use Filament\Actions\DeleteBulkAction;
use Filament\Actions\EditAction;
use Filament\Tables\Columns\IconColumn;
use Filament\Tables\Columns\TextColumn;
use Filament\Tables\Filters\SelectFilter;
use Filament\Tables\Table;

class ModelProfilesTable
{
    public static function configure(Table $table): Table
    {
        return $table
            ->columns([
                TextColumn::make('name')->searchable()->sortable(),
                TextColumn::make('role')->badge()->sortable(),
                TextColumn::make('provider')->badge(),
                TextColumn::make('model')->searchable(),
                TextColumn::make('base_url')->toggleable(isToggledHiddenByDefault: true),
                TextColumn::make('dim')->label('Dim')->placeholder('—'),
                IconColumn::make('is_active')->boolean()->label('Active'),
                TextColumn::make('updated_at')->dateTime()->sortable()->toggleable(),
            ])
            ->filters([
                SelectFilter::make('role')->options(['llm' => 'llm', 'embedding' => 'embedding']),
                SelectFilter::make('is_active')->options([1 => 'Active', 0 => 'Inactive']),
            ])
            ->recordActions([
                EditAction::make(),
            ])
            ->toolbarActions([
                BulkActionGroup::make([
                    DeleteBulkAction::make(),
                ]),
            ])
            ->defaultSort('role')
            ->emptyStateHeading('No model profiles yet')
            ->emptyStateDescription('Run `make seed-profiles` to load the default roster.');
    }
}
