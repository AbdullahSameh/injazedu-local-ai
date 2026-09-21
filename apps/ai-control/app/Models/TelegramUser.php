<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\HasOne;

/**
 * A sender identity observed by the bot, or a placeholder mapped ahead of observation
 * (`first_seen_at IS NULL`, data-model.md §1). The durable pseudonym is `tg_user_id`.
 *
 * The table is owned by Alembic — this model never migrates it (config/database.php: "Alembic
 * owns this schema"). Read side only here: the replay-safe upsert lives in the Python service
 * (`app/application/moderation/identities.py`), which is the single definition this model must
 * not duplicate. Mapping a not-yet-observed moderator (D-TG-52) is the one write this model's
 * panel callers make — a plain `INSERT … ON CONFLICT (tg_user_id) DO NOTHING`, mirrored in
 * `Filament\Resources\Moderators\Pages\CreateModerator`, not the nuanced replay-safe upsert.
 */
class TelegramUser extends Model
{
    protected $table = 'telegram_users';

    protected function casts(): array
    {
        return [
            'is_bot' => 'boolean',
            'first_seen_at' => 'datetime',
            'last_seen_at' => 'datetime',
            'identity_purged_at' => 'datetime',
        ];
    }

    public function moderator(): HasOne
    {
        return $this->hasOne(Moderator::class);
    }
}
