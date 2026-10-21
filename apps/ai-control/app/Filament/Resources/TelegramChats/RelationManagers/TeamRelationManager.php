<?php

namespace App\Filament\Resources\TelegramChats\RelationManagers;

use App\Filament\Support\TeamMembershipActions;
use Filament\Resources\RelationManagers\RelationManager;
use Filament\Schemas\Schema;
use Filament\Tables\Columns\TextColumn;
use Filament\Tables\Table;
use Illuminate\Database\Eloquent\Model;

/**
 * A group's team, with its history (TG-M2.1 S4, `specs/012-tg-m2-1-group-teams/contracts/
 * group-teams.md` T1-T5): every membership past and current, newest first and ten to a page,
 * nothing deletable. **Add member**, **End** and **Replace with…** are the same actions
 * Moderators › Assignments offers, delegated to the model where the rules live.
 */
class TeamRelationManager extends RelationManager
{
    protected static string $relationship = 'assignments';

    public static function getTitle(Model $ownerRecord, string $pageClass): string
    {
        return __('Team');
    }

    public function form(Schema $schema): Schema
    {
        return $schema->components([]);
    }

    public function table(Table $table): Table
    {
        return $table
            ->recordTitleAttribute('id')
            ->columns([
                TextColumn::make('moderator.display_name')
                    ->label(__('Moderator'))
                    ->extraAttributes(['dir' => 'auto']),
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
                    'add_member',
                    __('Add member'),
                    fn (): array => ['telegram_chat_id' => $this->getOwnerRecord()->id],
                ),
            ])
            ->recordActions([
                TeamMembershipActions::end(),
                TeamMembershipActions::replace(),
            ])
            ->toolbarActions([])
            ->defaultSort('valid_from', 'desc')
            ->paginated([10])
            ->emptyStateHeading(__('Nobody on this team yet'))
            ->emptyStateDescription(__('Use Add member to put a moderator on this group\'s team.'));
    }
}
