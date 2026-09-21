<?php

namespace App\Filament\Resources\TelegramChats\Schemas;

use Filament\Forms\Components\Textarea;
use Filament\Forms\Components\TextInput;
use Filament\Forms\Components\Toggle;
use Filament\Schemas\Schema;

/**
 * The measured toggle, the course reference and notes — the three columns `TelegramChat::
 * $fillable` allows (`control-panel-moderation.md` §2). The toggle writes one boolean and
 * starts nothing; the course reference is a plain integer with no relational link and no
 * cross-system validation, since the reference application is on another host and read-only
 * (FR-046, Principle III).
 */
class TelegramChatForm
{
    public static function configure(Schema $schema): Schema
    {
        return $schema
            ->components([
                Toggle::make('is_monitored')
                    ->label('Measured')
                    ->helperText(
                        'Turning this on starts nothing by itself — no job, no bulk derivation. '
                        .'To bring in events captured before this was switched on, the operator '
                        .'runs `python -m app.scripts.rederive_chat --chat <chat_id>`.'
                    ),
                TextInput::make('injaz_course_id')
                    ->label('Course reference')
                    ->numeric()
                    ->helperText(
                        'A plain numeric id, entered by hand — nothing here is validated '
                        .'against the reference application.'
                    ),
                Textarea::make('notes')
                    ->extraInputAttributes(['dir' => 'auto'])
                    ->columnSpanFull(),
            ]);
    }
}
