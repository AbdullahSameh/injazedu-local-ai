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
                    ->label(__('Name'))
                    ->required()
                    ->maxLength(100)
                    ->unique(ignoreRecord: true)
                    ->helperText(__('The seed\'s conflict target — re-seeding never overwrites this row.')),
                Select::make('role')
                    ->label(__('Role'))
                    ->options(['llm' => 'llm', 'embedding' => 'embedding', 'moderation' => 'moderation', 'attention' => 'attention'])
                    ->required()
                    ->native(false),
                Select::make('provider')
                    ->label(__('Provider'))
                    ->options(['ollama' => 'ollama', 'vllm' => 'vllm', 'fake' => 'fake'])
                    ->required()
                    ->native(false),
                TextInput::make('model')
                    ->label(__('Model'))
                    ->required()
                    ->maxLength(200)
                    ->helperText(__('The runtime\'s model id, e.g. gemma4:e2b-it-qat.')),
                TextInput::make('base_url')
                    ->label(__('Base url'))
                    ->url()
                    ->maxLength(500)
                    ->helperText(__('Must end in /v1 (research D-24). Leave blank only for provider=fake.')),
                TextInput::make('dim')
                    ->label(__('Dim'))
                    ->numeric()
                    ->minValue(1)
                    // Greyed out for an existing row (FR-017), but still dehydrated — the model's
                    // own guard (App\Models\ModelProfile::booted) is what actually refuses the
                    // change, with a message, so the UI restriction is never the only backstop.
                    ->disabled(fn (?ModelProfile $record): bool => $record !== null)
                    ->dehydrated()
                    ->helperText(
                        __('Required for role=embedding, must stay empty for role=llm. Immutable once set (FR-017) — create a new profile to change it.')
                    ),
                TextInput::make('api_key_env')
                    ->label(__('Api key env'))
                    ->maxLength(100)
                    ->helperText(
                        __('An environment variable NAME, resolved at call time — never a secret value (D-38). Leave blank when the runtime needs no credential.')
                    ),
                KeyValue::make('params')
                    ->label(__('Params'))
                    ->keyLabel(__('parameter'))
                    ->valueLabel(__('value'))
                    ->helperText(
                        __('llm: num_ctx, num_predict, temperature. embedding: batch_size, prefix_document, prefix_query (with {text}). moderation: num_ctx, num_predict, temperature, reasoning_effort.')
                    ),
                Toggle::make('is_active')
                    ->label(__('Is active'))
                    ->helperText(
                        __('Activating deactivates the incumbent for this role in the same transaction; deactivating the only active profile for a role is refused.')
                    ),
                Textarea::make('notes')
                    ->label(__('Notes'))
                    ->maxLength(65535)
                    ->columnSpanFull(),
            ]);
    }
}
