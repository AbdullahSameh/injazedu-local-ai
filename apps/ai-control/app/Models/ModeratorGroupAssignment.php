<?php

namespace App\Models;

use DateTimeInterface;
use Illuminate\Database\Eloquent\Builder;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
use Illuminate\Support\Facades\DB;

/**
 * Ownership as history: a moderator bound to a chat in a role over a half-open interval
 * `[valid_from, valid_to)` (data-model.md §4, `contracts/moderator-ownership.md` §1).
 *
 * The table is owned by Alembic — this model never migrates it (config/database.php: "Alembic
 * owns this schema"). The handover — one transaction, close before open, one timestamp value
 * bound to both sides — lives on this model, not in a Filament action, mirroring
 * `ModelProfile::save()` so it holds from `tinker` too (D-TG-58).
 */
class ModeratorGroupAssignment extends Model
{
    protected $table = 'moderator_group_assignments';

    public $timestamps = false;

    /**
     * Microsecond precision, not Eloquent's default `Y-m-d H:i:s` — a whole-second-granularity
     * `valid_from`/`valid_to` can manufacture a false zero-width interval (`ck_assignment_
     * interval`) whenever two handovers land in the same wall-clock second, which is exactly the
     * kind of precision hazard `handover()` below exists to avoid (D-TG-47).
     */
    protected $dateFormat = 'Y-m-d H:i:s.u';

    protected $fillable = [
        'telegram_chat_id',
        'moderator_id',
        'assignment_role',
        'valid_from',
        'valid_to',
        'note',
    ];

    protected function casts(): array
    {
        return [
            'valid_from' => 'datetime',
            'valid_to' => 'datetime',
        ];
    }

    public function chat(): BelongsTo
    {
        return $this->belongsTo(TelegramChat::class, 'telegram_chat_id');
    }

    public function moderator(): BelongsTo
    {
        return $this->belongsTo(Moderator::class);
    }

    /**
     * The one current primary assignment per chat — mirrors `uq_assignment_one_current_primary`
     * and `assignments.py`'s `responsible_at` predicate at `t = now()` (D-TG-48).
     */
    public function scopeCurrentPrimary(Builder $query): Builder
    {
        return $query->where('assignment_role', 'primary')->whereNull('valid_to');
    }

    /**
     * `responsible_at(chat, t)`, mirrored from `app/application/moderation/assignments.py`'s
     * `responsible_at` (D-TG-48, `contracts/moderator-ownership.md` §3) — that is the single
     * Python definition; this scope must not drift from it. Half-open: `valid_from` inclusive,
     * `valid_to` exclusive. Never a backup — the role predicate excludes it (O4).
     */
    public function scopeResponsibleAt(Builder $query, int $telegramChatId, $t): Builder
    {
        // A raw DateTimeInterface bound straight into the query builder is formatted by the
        // *connection's* date format (`Y-m-d H:i:s`, no microseconds) rather than this model's,
        // which can put a boundary instant on the wrong side of a microsecond-precision
        // `valid_from`/`valid_to` — the same hazard `handover()` below guards against (D-TG-47).
        $at = $t instanceof DateTimeInterface ? $t->format('Y-m-d H:i:s.u') : $t;

        return $query
            ->where('telegram_chat_id', $telegramChatId)
            ->where('assignment_role', 'primary')
            ->where('valid_from', '<=', $at)
            ->where(function (Builder $q) use ($at) {
                $q->whereNull('valid_to')->orWhere('valid_to', '>', $at);
            });
    }

    /**
     * A change of primary owner (`contracts/moderator-ownership.md` §2, D-TG-47, Finding 2):
     * close the incumbent, open the successor, one transaction, one **PHP** `now()` value bound
     * to both `valid_to` and `valid_from` — never two separate `now()` calls, which is the
     * PHP-side hazard that leaves a ~10 ms hole with zero owners that no constraint detects.
     *
     * "Opening a first owner" (a chat that has never had one) is the same protocol with the
     * close affecting zero rows, so this method also serves as `open_assignment`.
     */
    public static function handover(
        int $telegramChatId,
        int $moderatorId,
        ?string $note = null,
    ): self {
        // Pre-formatted to a string, not left as a Carbon instance: the bulk `update()` below
        // goes through the query builder rather than `setAttribute()`, so it would otherwise be
        // serialized using the *connection's* date format (`Y-m-d H:i:s`, no microseconds)
        // instead of this model's `$dateFormat` above — and truncating either side breaks "one
        // value, bound to both sides" (D-TG-47) even though only one `now()` call is made.
        $at = now()->format('Y-m-d H:i:s.u');

        return DB::transaction(function () use ($telegramChatId, $moderatorId, $note, $at): self {
            static::query()
                ->currentPrimary()
                ->where('telegram_chat_id', $telegramChatId)
                ->update(['valid_to' => $at]);

            return static::create([
                'telegram_chat_id' => $telegramChatId,
                'moderator_id' => $moderatorId,
                'assignment_role' => 'primary',
                'valid_from' => $at,
                'note' => $note,
            ]);
        });
    }
}
