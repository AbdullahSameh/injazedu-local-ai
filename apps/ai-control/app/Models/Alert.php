<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
use Illuminate\Database\Eloquent\Relations\HasMany;
use LogicException;

/**
 * One alert the evaluator fired (TG-M6, `specs/013-tg-m6-alerts/data-model.md` §3). The panel only
 * reads alerts: firing, delivery and edits are the Python workers' (D-TG-228, `alerting.md` S6), so
 * `booted()` throws on create, update and delete, from `tinker` too, as `ModerationAction` does.
 *
 * `telegram_chat_id` is the **source** group, never the destination. `subject_id` points at
 * `attention_items`, `moderation_incidents` or `telegram_chats` by `subject_type`.
 *
 * The table is owned by Alembic — this model never migrates it.
 */
class Alert extends Model
{
    protected $table = 'alerts';

    public $timestamps = false;

    /** §3.1: the delivery statuses, with their English labels (translated on read). */
    public const STATUSES = [
        'pending' => 'Pending',
        'sending' => 'Sending',
        'sent' => 'Sent',
        'failed' => 'Failed',
        'suppressed' => 'Suppressed (quiet hours)',
        'not_sent' => 'Not sent',
    ];

    /** `ck_alerts_not_sent`'s reasons. */
    public const NOT_SENT_REASONS = [
        'no_destination' => 'No destination',
        'subject_ended' => 'Ended before sending',
    ];

    protected function casts(): array
    {
        return [
            'episode_at' => 'datetime',
            'rule_values' => 'array',
            'qualified_at' => 'datetime',
            'fired_at' => 'datetime',
            'last_error_at' => 'datetime',
            'delivered_at' => 'datetime',
            'final_at' => 'datetime',
            'last_edit_at' => 'datetime',
            'created_at' => 'datetime',
            'excerpt_shown' => 'boolean',
            'repeat_index' => 'integer',
            'attempts' => 'integer',
        ];
    }

    protected static function booted(): void
    {
        foreach (['creating', 'updating', 'deleting'] as $event) {
            static::$event(function (): void {
                throw new LogicException('alerts are read-only in the panel');
            });
        }
    }

    public function rule(): BelongsTo
    {
        return $this->belongsTo(AlertRule::class, 'alert_rule_id');
    }

    /** The source group the subject lives in. */
    public function chat(): BelongsTo
    {
        return $this->belongsTo(TelegramChat::class, 'telegram_chat_id');
    }

    /** The button acts recorded for presses on this alert (`moderation_actions.alert_id`). */
    public function acts(): HasMany
    {
        return $this->hasMany(ModerationAction::class, 'alert_id');
    }

    /**
     * The status as the history reads it: the status word, with the reason for `not_sent` or the
     * provider's error category for `failed`. An error category is a code, never a message text.
     */
    public function statusText(): string
    {
        $status = __(self::STATUSES[$this->delivery_status] ?? $this->delivery_status);

        if ($this->delivery_status === 'not_sent' && $this->not_sent_reason !== null) {
            return $status.' · '.__(self::NOT_SENT_REASONS[$this->not_sent_reason] ?? $this->not_sent_reason);
        }
        if ($this->delivery_status === 'failed' && $this->last_error_category !== null) {
            return $status.' · '.$this->last_error_category;
        }

        return $status;
    }

    /** "k of N" for a repeat, "first" for index 0. */
    public function repeatText(): string
    {
        if ($this->repeat_index === 0) {
            return __('First');
        }
        $max = $this->rule_values['max_repeats'] ?? null;

        return $max !== null
            ? __(':k of :n', ['k' => $this->repeat_index, 'n' => $max])
            : (string) $this->repeat_index;
    }
}
