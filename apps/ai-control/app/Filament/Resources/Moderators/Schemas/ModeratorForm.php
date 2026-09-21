<?php

namespace App\Filament\Resources\Moderators\Schemas;

use App\Models\TelegramUser;
use Filament\Forms\Components\Radio;
use Filament\Forms\Components\Select;
use Filament\Forms\Components\Textarea;
use Filament\Forms\Components\TextInput;
use Filament\Forms\Components\Toggle;
use Filament\Schemas\Components\Utilities\Get;
use Filament\Schemas\Schema;
use Illuminate\Support\Facades\DB;

/**
 * A stable display name plus either an observed sender identity or a not-yet-observed numeric
 * identifier (`control-panel-moderation.md` §3, FR-025, FR-027, D-TG-52) — the latter is the
 * runbook's normal path, since the operator collects moderator identifiers before anyone has
 * necessarily posted. Whichever is chosen resolves to `moderators.telegram_user_id` in
 * `Pages\CreateModerator::mutateFormDataBeforeCreate`.
 */
class ModeratorForm
{
    public static function configure(Schema $schema): Schema
    {
        return $schema
            ->components([
                TextInput::make('display_name')
                    ->label('Display name')
                    ->required()
                    ->maxLength(200)
                    ->extraInputAttributes(['dir' => 'auto'])
                    ->helperText(
                        'Operator-set and stable — a renamed platform profile never changes '
                        .'who a report is about (FR-029).'
                    ),
                Radio::make('identity_source')
                    ->label('Identity')
                    ->options([
                        'observed' => 'An already-observed sender',
                        'placeholder' => 'A numeric platform id not yet observed',
                    ])
                    ->default('placeholder')
                    ->inline()
                    ->required()
                    ->visibleOn('create'),
                Select::make('existing_telegram_user_id')
                    ->label('Observed sender')
                    ->options(fn (): array => self::observedSenderOptions())
                    ->searchable()
                    ->visible(fn (Get $get): bool => $get('identity_source') === 'observed')
                    ->required(fn (Get $get): bool => $get('identity_source') === 'observed')
                    ->visibleOn('create')
                    ->helperText(
                        '★ marks someone the bot has observed treated as an administrator '
                        .'(FR-031, D-TG-62) — a proposal, not a grant: confirming it is what '
                        .'creates the mapping.'
                    ),
                TextInput::make('tg_user_id')
                    ->label('Platform numeric id')
                    ->numeric()
                    ->visible(fn (Get $get): bool => $get('identity_source') !== 'observed')
                    ->required(fn (Get $get): bool => $get('identity_source') !== 'observed')
                    ->visibleOn('create')
                    ->helperText(
                        'Creates a placeholder identity with no name until this person is '
                        .'first observed (FR-027, FR-028).'
                    ),
                Toggle::make('is_active')
                    ->label('Active')
                    ->default(true)
                    ->helperText(
                        'Deactivating changes only availability for new assignments — the '
                        .'record, the assignment history and every message flag already '
                        .'written stay exactly as they are (FR-030).'
                    ),
                TextInput::make('injaz_user_id')
                    ->label('Organisation user reference')
                    ->numeric()
                    ->helperText(
                        'A plain, optional reference — no relational link to that system '
                        .'(Principle III).'
                    ),
                Textarea::make('notes')
                    ->extraInputAttributes(['dir' => 'auto'])
                    ->columnSpanFull(),
            ]);
    }

    /**
     * Observed senders not already mapped to a moderator, starred when the bot has observed
     * them treated as an administrator. Options are keyed by `telegram_users.id`, the surrogate
     * `Moderator::create()` expects.
     */
    private static function observedSenderOptions(): array
    {
        $adminTgUserIds = self::observedAdministratorTgUserIds();

        return TelegramUser::query()
            ->whereNotNull('first_seen_at')
            ->doesntHave('moderator')
            ->get()
            ->sortByDesc(fn (TelegramUser $user): bool => in_array($user->tg_user_id, $adminTgUserIds, true))
            ->mapWithKeys(function (TelegramUser $user) use ($adminTgUserIds): array {
                $label = trim(($user->display_name ?: $user->username ?: '(no name)')." (#{$user->tg_user_id})");
                if (in_array($user->tg_user_id, $adminTgUserIds, true)) {
                    $label = "★ {$label}";
                }

                return [$user->id => $label];
            })
            ->all();
    }

    /**
     * Platform numeric ids the bot has observed treated as an administrator — read from stored
     * `chat_member` promotions (the *other* member, the update's subject) and the human actor
     * behind a `my_chat_member` change to the bot's own standing (only an administrator can
     * change it). Read-only, no platform call (FR-050, D-TG-62). Being on this list is a
     * proposal: an administrator on the platform is not a moderator in this domain (FR-031).
     */
    private static function observedAdministratorTgUserIds(): array
    {
        $rows = DB::select(<<<'SQL'
            SELECT DISTINCT tg_user_id FROM (
                SELECT (payload #>> '{chat_member,new_chat_member,user,id}')::bigint AS tg_user_id
                  FROM telegram_updates
                 WHERE update_type = 'chat_member'
                   AND payload #>> '{chat_member,new_chat_member,status}' IN ('administrator', 'creator')
                UNION ALL
                SELECT (payload #>> '{my_chat_member,from,id}')::bigint AS tg_user_id
                  FROM telegram_updates
                 WHERE update_type = 'my_chat_member'
                   AND COALESCE((payload #>> '{my_chat_member,from,is_bot}')::boolean, false) = false
            ) candidates
            WHERE tg_user_id IS NOT NULL
            SQL);

        return array_map(static fn ($row) => (int) $row->tg_user_id, $rows);
    }

    /**
     * Resolves the create form's identity fields to a `telegram_users.id` surrogate, creating a
     * placeholder identity for a not-yet-observed numeric id (D-TG-52) — a plain `INSERT …
     * ON CONFLICT (tg_user_id) DO NOTHING`, not the Python service's replay-safe upsert
     * (`TelegramUser`'s docstring), mirrored here because the panel and that service are
     * separate processes sharing only the database.
     */
    public static function resolveTelegramUserId(array $data): int
    {
        if (($data['identity_source'] ?? null) === 'observed') {
            return (int) $data['existing_telegram_user_id'];
        }

        DB::table('telegram_users')->insertOrIgnore([
            'tg_user_id' => $data['tg_user_id'],
            'is_bot' => false,
        ]);

        return TelegramUser::query()->where('tg_user_id', $data['tg_user_id'])->value('id');
    }
}
