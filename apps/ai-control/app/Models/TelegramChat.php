<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\HasMany;

/**
 * A group or channel TG-M1 has captured events for (data-model.md §0, 0003_moderation_ingest).
 *
 * The table is owned by Alembic — this model never migrates it (config/database.php: "Alembic
 * owns this schema"). Groups are discovered by capture, never typed in here: fillable is
 * limited to the three columns the panel may actually change (FR-046).
 */
class TelegramChat extends Model
{
    protected $table = 'telegram_chats';

    protected $fillable = [
        'is_monitored',
        'injaz_course_id',
        'notes',
    ];

    protected function casts(): array
    {
        return [
            'is_monitored' => 'boolean',
            'bot_can_delete' => 'boolean',
            'bot_status_at' => 'datetime',
            'last_event_at' => 'datetime',
            'injaz_course_id' => 'integer',
        ];
    }

    /**
     * Every assignment row of this chat, past and current — the Groups › Team relation manager's
     * history (TG-M2.1 S4).
     */
    public function assignments(): HasMany
    {
        return $this->hasMany(ModeratorGroupAssignment::class, 'telegram_chat_id');
    }

    /**
     * The chat's current team memberships — several since TG-M2.1 (T1). An empty set on a
     * measured group is a coverage problem to surface (FR-049).
     */
    public function currentMemberships(): HasMany
    {
        return $this->hasMany(ModeratorGroupAssignment::class, 'telegram_chat_id')
            ->where('assignment_role', 'primary')
            ->whereNull('valid_to');
    }
}
