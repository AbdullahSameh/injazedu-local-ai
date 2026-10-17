<?php

namespace App\Filament\Resources\Users\Schemas;

use App\Models\User;
use Filament\Forms\Components\TextInput;
use Filament\Forms\Components\Toggle;
use Filament\Schemas\Components\Utilities\Get;
use Filament\Schemas\Schema;
use Illuminate\Support\Facades\Auth;
use Illuminate\Validation\Rules\Password;
use SensitiveParameter;

/**
 * Name, email, password and panel access. The password follows Filament's own profile page: blank
 * on edit keeps the current one, a confirmation appears once it is typed, and `User`'s `hashed`
 * cast stores the hash — the plain value is never dehydrated anywhere else.
 */
class UserForm
{
    public static function configure(Schema $schema): Schema
    {
        return $schema
            ->components([
                TextInput::make('name')
                    ->label(__('Name'))
                    ->required()
                    ->maxLength(255)
                    ->extraInputAttributes(['dir' => 'auto']),
                TextInput::make('email')
                    ->label(__('Email'))
                    ->email()
                    ->required()
                    ->maxLength(255)
                    ->unique(ignoreRecord: true),
                TextInput::make('password')
                    ->label(__('Password'))
                    ->password()
                    ->revealable()
                    ->autocomplete('new-password')
                    ->required(fn (string $operation): bool => $operation === 'create')
                    ->rule(Password::default())
                    ->dehydrated(fn (#[SensitiveParameter] ?string $state): bool => filled($state))
                    ->live(debounce: 500)
                    ->same('passwordConfirmation')
                    ->helperText(
                        fn (string $operation): ?string => $operation === 'edit'
                            ? __('Leave blank to keep the current password.')
                            : null
                    ),
                TextInput::make('passwordConfirmation')
                    ->label(__('Confirm password'))
                    ->password()
                    ->revealable()
                    ->autocomplete('new-password')
                    ->required()
                    ->visible(fn (Get $get): bool => filled($get('password')))
                    ->dehydrated(false),
                // Disabled — and so never saved — on your own account: switching it off would
                // sign you out with no one guaranteed left to switch it back on.
                Toggle::make('is_panel_operator')
                    ->label(__('Panel access'))
                    ->default(true)
                    ->disabled(fn (?User $record): bool => $record !== null && $record->is(Auth::user()))
                    ->helperText(
                        __('Off: this account can no longer sign in. Your own access cannot be switched off.')
                    ),
            ]);
    }
}
