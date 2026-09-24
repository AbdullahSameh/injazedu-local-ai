<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

/**
 * One captured message (`data-model.md` §2, TG-M1/TG-M2's `telegram_messages`). Read side only —
 * derivation is the Python service's (`app/application/moderation/messages.py`); this milestone
 * is the first to read `original_text` from the panel, for the Live Attention Queue's Question
 * column (`control-panel-attention.md` §1).
 *
 * The table is owned by Alembic — this model never migrates it (config/database.php: "Alembic
 * owns this schema").
 */
class TelegramMessage extends Model
{
    protected $table = 'telegram_messages';

    public $timestamps = false;

    protected function casts(): array
    {
        return [
            'sent_at' => 'datetime',
            'edited_at' => 'datetime',
            'is_service' => 'boolean',
            'is_from_moderator' => 'boolean',
            'entity_flags' => 'array',
            'text_purged_at' => 'datetime',
            'attention_evaluated_at' => 'datetime',
            'created_at' => 'datetime',
        ];
    }
}
