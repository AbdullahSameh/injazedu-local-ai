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
                TextColumn::make('name')->label(__('Name'))->searchable()->sortable(),
                TextColumn::make('role')->label(__('Role'))->badge()->sortable(),
                TextColumn::make('provider')->label(__('Provider'))->badge(),
                TextColumn::make('model')->label(__('Model'))->searchable(),
                TextColumn::make('base_url')->label(__('Base url'))->toggleable(isToggledHiddenByDefault: true),
                TextColumn::make('dim')->label(__('Dim'))->placeholder('—'),
                IconColumn::make('is_active')->boolean()->label(__('Active')),
                TextColumn::make('updated_at')->label(__('Updated at'))->dateTime()->sortable()->toggleable(),
            ])
            ->filters([
                SelectFilter::make('role')->label(__('Role'))->options(['llm' => 'llm', 'embedding' => 'embedding', 'moderation' => 'moderation', 'attention' => 'attention']),
                SelectFilter::make('is_active')->label(__('Is active'))->options([1 => __('Active'), 0 => __('Inactive')]),
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
            ->emptyStateHeading(__('No model profiles yet'))
            ->emptyStateDescription(__('Run `make seed-profiles` to load the default roster.'));
    }
}
