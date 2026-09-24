<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;

/**
 * One question waiting for an answer, or the record of one that got one
 * (`contracts/attention-rules.md`, `data-model.md` §1, revision 0005).
 *
 * The table is owned by Alembic — this model never migrates it (config/database.php: "Alembic
 * owns this schema"). Every transition out of `open` — answered, dismissed, expired — is the
 * same guarded write, `UPDATE … WHERE id = ? AND status = 'open'` (contract §4 C8, §6 G2): the
 * guard is simultaneously the concurrency control, the write-once rule, and the reason
 * re-running any step is harmless. `closeIfOpen()` lives here, not in a Filament action, so the
 * invariant holds from `tinker` too — mirroring `ModeratorGroupAssignment::handover()` and
 * `ModelProfile::save()`.
 */
class AttentionItem extends Model
{
    protected $table = 'attention_items';

    public $timestamps = false;

    /**
     * The fields "open item by hand" (Phase 6, T057) creates a row with. Every terminal
     * transition still goes through `closeIfOpen()`'s raw `update()` below, which bypasses mass
     * assignment entirely — this list exists for the one legitimate `create()` call, mirroring
     * `ModeratorGroupAssignment::$fillable`.
     */
    protected $fillable = [
        'telegram_chat_id',
        'telegram_message_id',
        'message_thread_id',
        'opened_at',
        'source',
        'rule_version',
        'responsible_moderator_id',
        'status',
    ];

    protected function casts(): array
    {
        return [
            'opened_at' => 'datetime',
            'first_response_at' => 'datetime',
            'closed_at' => 'datetime',
            'created_at' => 'datetime',
        ];
    }

    public function chat(): BelongsTo
    {
        return $this->belongsTo(TelegramChat::class, 'telegram_chat_id');
    }

    public function responsibleModerator(): BelongsTo
    {
        return $this->belongsTo(Moderator::class, 'responsible_moderator_id');
    }

    public function respondingModerator(): BelongsTo
    {
        return $this->belongsTo(Moderator::class, 'first_response_moderator_id');
    }

    /**
     * The burst's earliest message — this item's own anchor `(telegram_chat_id,
     * telegram_message_id)`, `fk_attention_message`'s target — read for the Live Attention
     * Queue's Question column (`control-panel-attention.md` §1). A plain query, not an Eloquent
     * relation: the join key is composite and `telegram_messages`' primary key plays no part in
     * it, which a `belongsTo`/`hasOne` cannot express directly. Always finds a row (the FK
     * guarantees it); `original_text` alone may be `NULL` once TG-M10's purge reaches it
     * (`data-model.md` §4) — the caller renders that case, not this method.
     */
    public function anchorMessage(): ?TelegramMessage
    {
        return TelegramMessage::query()
            ->where('telegram_chat_id', $this->telegram_chat_id)
            ->where('message_id', $this->telegram_message_id)
            ->first();
    }

    /**
     * The one guarded write every terminal transition uses (contract §4 C8, §6 G2): `$attrs`
     * carries the fields particular to the transition (e.g. `first_response_at` for an answer,
     * `close_reason` for a dismissal), `$status` is always set alongside them, and the `WHERE
     * status = 'open'` guard makes a second call — a double-submitted dismissal, a re-run of the
     * matcher, a message arriving after expiry — update zero rows rather than corrupt the first.
     *
     * Returns the number of rows affected: `1` on the transition that actually happened, `0` on
     * every later call. Never throws on the zero case — that is the expected, harmless outcome.
     */
    public function closeIfOpen(string $status, array $attrs = []): int
    {
        return static::query()
            ->where('id', $this->id)
            ->where('status', 'open')
            ->update([...$attrs, 'status' => $status]);
    }
}
