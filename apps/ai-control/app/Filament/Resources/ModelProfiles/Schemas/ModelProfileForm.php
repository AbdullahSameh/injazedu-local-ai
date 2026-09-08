<?php

namespace App\Filament\Resources\ModelProfiles\Schemas;

use App\Models\ModelProfile;
use Filament\Forms\Components\KeyValue;
use Filament\Forms\Components\Select;
use Filament\Forms\Components\Textarea;
use Filament\Forms\Components\TextInput;
use Filament\Forms\Components\Toggle;
use Filament\Schemas\Schema;

class ModelProfileForm
{
    public static function configure(Schema $schema): Schema
    {
        return $schema
            ->components([
                TextInput::make('name')
                    ->required()
                    ->maxLength(100)
                    ->unique(ignoreRecord: true)
                    ->helperText('The seed\'s conflict target — re-seeding never overwrites this row.'),
                Select::make('role')
                    ->options(['llm' => 'llm', 'embedding' => 'embedding'])
                    ->required()
                    ->native(false),
                Select::make('provider')
                    ->options(['ollama' => 'ollama', 'vllm' => 'vllm', 'fake' => 'fake'])
                    ->required()
                    ->native(false),
                TextInput::make('model')
                    ->required()
                    ->maxLength(200)
                    ->helperText('The runtime\'s model id, e.g. gemma4:e2b-it-qat.'),
                TextInput::make('base_url')
                    ->url()
                    ->maxLength(500)
                    ->helperText('Must end in /v1 (research D-24). Leave blank only for provider=fake.'),
                TextInput::make('dim')
                    ->numeric()
                    ->minValue(1)
                    // Greyed out for an existing row (FR-017), but still dehydrated — the model's
                    // own guard (App\Models\ModelProfile::booted) is what actually refuses the
                    // change, with a message, so the UI restriction is never the only backstop.
                    ->disabled(fn (?ModelProfile $record): bool => $record !== null)
                    ->dehydrated()
                    ->helperText(
                        'Required for role=embedding, must stay empty for role=llm. '
                        .'Immutable once set (FR-017) — create a new profile to change it.'
                    ),
                TextInput::make('api_key_env')
                    ->maxLength(100)
                    ->helperText(
                        'An environment variable NAME, resolved at call time — never a secret '
                        .'value (D-38). Leave blank when the runtime needs no credential.'
                    ),
                KeyValue::make('params')
                    ->keyLabel('parameter')
                    ->valueLabel('value')
                    ->helperText(
                        'llm: num_ctx, num_predict, temperature. embedding: batch_size, '
                        .'prefix_document, prefix_query (with {text}).'
                    ),
                Toggle::make('is_active')
                    ->helperText(
                        'Activating deactivates the incumbent for this role in the same '
                        .'transaction; deactivating the only active profile for a role is refused.'
                    ),
                Textarea::make('notes')
                    ->maxLength(65535)
                    ->columnSpanFull(),
            ]);
    }
}
