<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\HasMany;
use Illuminate\Support\Facades\DB;
use Illuminate\Validation\ValidationException;

/**
 * A group or channel TG-M1 has captured events for (data-model.md §0, 0003_moderation_ingest).
 *
 * The table is owned by Alembic — this model never migrates it (config/database.php: "Alembic
 * owns this schema"). Groups are discovered by capture, never typed in here: fillable is
 * limited to the three columns the panel may actually change (FR-046).
 *
 * TG-M6 (`specs/013-tg-m6-alerts/contracts/alerting.md` D1-D2, S2): the panel also sets and clears
 * `is_alert_destination`, only through `useAsAlertDestination()` and `stopUsingAsAlertDestination()`.
 * The destination is never measured and a measured chat is never the destination: `booted()`
 * refuses both orders as a sentence, and `ck_chat_destination_not_monitored` backs it.
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
            'is_alert_destination' => 'boolean',
            'bot_can_delete' => 'boolean',
            'bot_status_at' => 'datetime',
            'last_event_at' => 'datetime',
            'injaz_course_id' => 'integer',
        ];
    }

    /** FR-571: the bot is in the chat, as a member or an administrator (D5). */
    public const DESTINATION_STANDINGS = ['member', 'administrator'];

    protected static function booted(): void
    {
        static::saving(function (TelegramChat $chat): void {
            if ($chat->is_monitored && $chat->is_alert_destination) {
                throw ValidationException::withMessages([
                    'is_monitored' => __('This chat is the alert destination, which is never measured. Stop using it as the destination first.'),
                ]);
            }
        });
    }

    /** The one chat alerts are posted to, or null (D1). */
    public static function alertDestination(): ?self
    {
        return self::query()->where('is_alert_destination', true)->first();
    }

    /** Moderators press the alert's buttons in a group; a supergroup is the advice (L7). */
    public const DESTINATION_TYPES = ['group', 'supergroup'];

    /** FR-571: only an unmeasured group the bot is in may become the destination. */
    public function canBeAlertDestination(): bool
    {
        return ! $this->is_monitored
            && ! $this->is_alert_destination
            && $this->migrated_to_chat_id === null
            && in_array($this->chat_type, self::DESTINATION_TYPES, true)
            && in_array($this->bot_status, self::DESTINATION_STANDINGS, true);
    }

    /**
     * D1: makes this chat the destination in one transaction, so a previous destination stops
     * being one at the same instant and there is never more than one.
     */
    public function useAsAlertDestination(): void
    {
        if (! $this->canBeAlertDestination()) {
            throw ValidationException::withMessages([
                'is_alert_destination' => match (true) {
                    (bool) $this->is_monitored => __('A measured group can never be the alert destination.'),
                    $this->migrated_to_chat_id !== null => __('This group became a supergroup. Use its new row instead.'),
                    default => __('Only a group the bot is in, as a member or an administrator, can be the alert destination.'),
                },
            ]);
        }

        DB::transaction(function (): void {
            self::query()
                ->where('is_alert_destination', true)
                ->whereKeyNot($this->getKey())
                ->update(['is_alert_destination' => false]);
            $this->forceFill(['is_alert_destination' => true])->save();
        });
    }

    /** Clears the destination: every pending alert becomes `not_sent / no_destination` (D4). */
    public function stopUsingAsAlertDestination(): void
    {
        $this->forceFill(['is_alert_destination' => false])->save();
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
