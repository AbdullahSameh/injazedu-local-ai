<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\HasOne;

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
     * The one `primary` assignment currently open for this chat, if any —
     * `uq_assignment_one_current_primary` guarantees at most one row. Used to surface a measured
     * group with no current primary owner as a coverage problem (FR-049).
     */
    public function currentPrimaryAssignment(): HasOne
    {
        return $this->hasOne(ModeratorGroupAssignment::class, 'telegram_chat_id')
            ->where('assignment_role', 'primary')
            ->whereNull('valid_to');
    }
}
