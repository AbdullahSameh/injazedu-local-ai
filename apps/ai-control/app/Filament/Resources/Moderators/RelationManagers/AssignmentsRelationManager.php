<?php

namespace App\Filament\Resources\Moderators\RelationManagers;

use App\Models\ModeratorGroupAssignment;
use App\Models\TelegramChat;
use Filament\Actions\Action;
use Filament\Forms\Components\Select;
use Filament\Forms\Components\Textarea;
use Filament\Resources\RelationManagers\RelationManager;
use Filament\Schemas\Schema;
use Filament\Tables\Columns\TextColumn;
use Filament\Tables\Table;

/**
 * Every past and current assignment for this moderator — group, role, interval and note, in
 * chronological order, nothing deletable (`control-panel-moderation.md` §3, FR-048).
 *
 * A relation manager rather than a resource of its own: assignments are never navigated to
 * independently, and they must be created through the **Reassign** action below rather than a
 * free-form create form, which a top-level resource would invite bypassing (D-TG-66).
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
                    ->label('Group')
                    ->extraAttributes(['dir' => 'auto'])
                    ->placeholder('(untitled)'),
                TextColumn::make('assignment_role')->label('Role')->badge(),
                TextColumn::make('valid_from')->label('From')->dateTime(),
                TextColumn::make('valid_to')->label('Until')->dateTime()->placeholder('current'),
                TextColumn::make('note')->extraAttributes(['dir' => 'auto'])->wrap(),
            ])
            ->headerActions([
                // The whole reassign protocol of moderator-ownership.md §2, delegated to the
                // Eloquent model method (T052) rather than performed here as two writes — one
                // transaction, close before open, one timestamp value bound to both sides
                // (FR-037, D-TG-58).
                Action::make('reassign')
                    ->label('Reassign')
                    ->schema([
                        Select::make('telegram_chat_id')
                            ->label('Group')
                            ->options(fn (): array => TelegramChat::query()
                                ->orderBy('title')
                                ->get()
                                ->mapWithKeys(fn (TelegramChat $chat): array => [
                                    $chat->id => $chat->title ?? "Chat {$chat->chat_id}",
                                ])
                                ->all())
                            ->searchable()
                            ->required(),
                        Textarea::make('note')->extraInputAttributes(['dir' => 'auto']),
                    ])
                    ->action(function (array $data): void {
                        ModeratorGroupAssignment::handover(
                            (int) $data['telegram_chat_id'],
                            $this->getOwnerRecord()->id,
                            $data['note'] ?? null,
                        );
                    }),
            ])
            ->recordActions([])
            ->toolbarActions([])
            ->defaultSort('valid_from')
            ->emptyStateHeading('No assignments yet')
            ->emptyStateDescription('Use Reassign to make this moderator the primary owner of a group.');
    }
}
