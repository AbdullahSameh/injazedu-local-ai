<?php

namespace App\Filament\Resources\Moderators\RelationManagers;

use App\Filament\Support\TeamMembershipActions;
use Filament\Resources\RelationManagers\RelationManager;
use Filament\Schemas\Schema;
use Filament\Tables\Columns\TextColumn;
use Filament\Tables\Table;

/**
 * Every past and current assignment for this moderator — group, role, interval and note, newest
 * first and ten to a page, nothing deletable (`control-panel-moderation.md` §3, FR-048).
 *
 * A relation manager rather than a resource of its own: assignments are never navigated to
 * independently, and they must be created through the actions below rather than a free-form create
 * form, which a top-level resource would invite bypassing (D-TG-66). TG-M2.1 S4
 * (`specs/012-tg-m2-1-group-teams/contracts/group-teams.md`): a group has a team, so "Reassign"
 * became **Add to group**, **End** and **Replace with…**, each delegated to the model (T4-T5).
 */
class AssignmentsRelationManager extends RelationManager
{
    protected static string $relationship = 'assignments';

    public function form(Schema $schema): Schema
    {
        return $schema->components([]);
    }

    public function table(Table $table): Table
    {
        return $table
            ->recordTitleAttribute('id')
            ->columns([
                TextColumn::make('chat.title')
                    ->label(__('Group'))
                    ->extraAttributes(['dir' => 'auto'])
                    ->placeholder(__('(untitled)')),
                TextColumn::make('assignment_role')
                    ->label(__('Role'))
                    ->formatStateUsing(fn (string $state): string => $state === 'primary' ? __('Team member') : __($state))
                    ->badge(),
                TextColumn::make('valid_from')->label(__('From'))->dateTime(),
                TextColumn::make('valid_to')->label(__('Until'))->dateTime()->placeholder(__('current')),
                TextColumn::make('note')->label(__('Note'))->extraAttributes(['dir' => 'auto'])->wrap(),
            ])
            ->headerActions([
                TeamMembershipActions::add(
                    'add_to_group',
                    __('Add to group'),
                    fn (): array => ['moderator_id' => $this->getOwnerRecord()->id],
                ),
            ])
            ->recordActions([
                TeamMembershipActions::end(),
                TeamMembershipActions::replace(),
            ])
            ->toolbarActions([])
            ->defaultSort('valid_from', 'desc')
            ->paginated([10])
            ->emptyStateHeading(__('No assignments yet'))
            ->emptyStateDescription(__('Use Add to group to put this moderator on a group\'s team.'));
    }
}
