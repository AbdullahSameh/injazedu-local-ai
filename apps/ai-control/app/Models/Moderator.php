<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Casts\Attribute;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
use Illuminate\Database\Eloquent\Relations\HasMany;
use Illuminate\Support\Facades\DB;

/**
 * A moderator is someone the operator named — this domain's fact, informed by the platform's
 * administrator lists but never granted by them (data-model.md §3, FR-031).
 *
 * The table is owned by Alembic — this model never migrates it (config/database.php: "Alembic
 * owns this schema"). `is_active = false` ends every current team membership at the
 * deactivation instant (TG-M2.1 T6, D-TG-208) and blocks new ones; the record, the assignment
 * history and every `is_from_moderator` already written stay exactly as they are (FR-030, SC-011)
 * — deactivation is not a retraction of history.
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
        'user_id',
    ];

    protected function casts(): array
    {
        return [
            'is_active' => 'boolean',
            'injaz_user_id' => 'integer',
            'user_id' => 'integer',
        ];
    }

    public function telegramUser(): BelongsTo
    {
        return $this->belongsTo(TelegramUser::class, 'telegram_user_id');
    }

    /**
     * The panel account this moderator signs in with, if any (revision 0009). Optional, at most
     * one moderator per account (`uq_moderators_user_id`), and it grants no access.
     */
    public function user(): BelongsTo
    {
        return $this->belongsTo(User::class);
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

    /**
     * T6: a deactivation and the end of every current membership it implies are one transaction,
     * with one timestamp value — otherwise someone who left stays on "Team: …" and keeps
     * collecting misses (D-TG-208). Mirrors `ModelProfile::save()`, so it holds from `tinker` too.
     */
    public function save(array $options = []): bool
    {
        return DB::transaction(function () use ($options): bool {
            $deactivating = $this->exists && $this->isDirty('is_active') && ! $this->is_active;
            $saved = parent::save($options);

            if ($saved && $deactivating) {
                ModeratorGroupAssignment::query()
                    ->where('moderator_id', $this->id)
                    ->whereNull('valid_to')
                    ->update(['valid_to' => now()->utc()->format('Y-m-d H:i:s.u')]);
            }

            return $saved;
        });
    }
}
