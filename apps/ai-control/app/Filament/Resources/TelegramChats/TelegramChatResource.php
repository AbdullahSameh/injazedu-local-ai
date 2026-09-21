<?php

namespace App\Filament\Resources\TelegramChats;

use App\Filament\Resources\TelegramChats\Pages\EditTelegramChat;
use App\Filament\Resources\TelegramChats\Pages\ListTelegramChats;
use App\Filament\Resources\TelegramChats\Schemas\TelegramChatForm;
use App\Filament\Resources\TelegramChats\Tables\TelegramChatsTable;
use App\Models\TelegramChat;
use BackedEnum;
use Filament\Resources\Resource;
use Filament\Schemas\Schema;
use Filament\Support\Icons\Heroicon;
use Filament\Tables\Table;
use UnitEnum;

/**
 * List and edit only (`control-panel-moderation.md` §2). Groups are discovered by TG-M1's
 * capture, never typed in, and deleting one would orphan messages and assignments — so there is
 * no create page and no delete action anywhere on this resource (FR-046).
 */
class TelegramChatResource extends Resource
{
    protected static ?string $model = TelegramChat::class;

    protected static string|BackedEnum|null $navigationIcon = Heroicon::OutlinedChatBubbleLeftRight;

    protected static string|UnitEnum|null $navigationGroup = 'Moderation Intelligence';

    public static function form(Schema $schema): Schema
    {
        return TelegramChatForm::configure($schema);
    }

    public static function table(Table $table): Table
    {
        return TelegramChatsTable::configure($table);
    }

    public static function getRelations(): array
    {
        return [
            //
        ];
    }

    public static function getPages(): array
    {
        return [
            'index' => ListTelegramChats::route('/'),
            'edit' => EditTelegramChat::route('/{record}/edit'),
        ];
    }
}
