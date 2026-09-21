<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Casts\Attribute;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
use Illuminate\Database\Eloquent\Relations\HasMany;

/**
 * A moderator is someone the operator named — this domain's fact, informed by the platform's
 * administrator lists but never granted by them (data-model.md §3, FR-031).
 *
 * The table is owned by Alembic — this model never migrates it (config/database.php: "Alembic
 * owns this schema"). `is_active = false` changes only availability for new assignments: the
 * record, the assignment history and every `is_from_moderator` already written stay exactly as
 * they are (FR-030, SC-011) — deactivation is not a retraction of history.
 */
class Moderator extends Model
{
    protected $table = 'moderators';

    protected $fillable = [
        'telegram_user_id',
        'display_name',
        'injaz_user_id',
        'is_active',
        'notes',
    ];

    protected function casts(): array
    {
        return [
            'is_active' => 'boolean',
            'injaz_user_id' => 'integer',
        ];
    }

    public function telegramUser(): BelongsTo
    {
        return $this->belongsTo(TelegramUser::class, 'telegram_user_id');
    }

    protected function telegramUserId(): Attribute
    {
        return Attribute::make(
            get: fn (?string $value) => $value !== null ? (int) $value : null,
        );
    }

    public function assignments(): HasMany
    {
        return $this->hasMany(ModeratorGroupAssignment::class);
    }
}
