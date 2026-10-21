<?php

namespace App\Models;

use DateTimeInterface;
use Illuminate\Database\Eloquent\Builder;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;

/**
 * Ownership as history, held by a team: a moderator bound to a chat in a role over a half-open
 * interval `[valid_from, valid_to)` (data-model.md §4, `contracts/moderator-ownership.md` §1, amended
 * by TG-M2.1's `specs/012-tg-m2-1-group-teams/contracts/group-teams.md` §1). A `primary` row is a team
 * membership, and several can be current in one group (T1); one moderator is current in a group
 * at most once (T2, `uq_assignment_one_current_membership`).
 *
 * The table is owned by Alembic — this model never migrates it (config/database.php: "Alembic
 * owns this schema"). Every write — add (T4), end and replace (T5) — lives on this model, not in a
 * Filament action, mirroring `ModelProfile::save()` so it holds from `tinker` too (D-TG-58). Python's
 * `assignments.py` holds the same rules; "on the team" itself is defined once, by the view
 * `moderation_team_intervals`, which `teamAt()` reads.
 */
class ModeratorGroupAssignment extends Model
{
    protected $table = 'moderator_group_assignments';

    public $timestamps = false;

    /**
     * Microsecond precision, not Eloquent's default `Y-m-d H:i:s` — a whole-second-granularity
     * `valid_from`/`valid_to` can manufacture a false zero-width interval (`ck_assignment_
     * interval`) whenever two writes land in the same wall-clock second, which is exactly the
     * kind of precision hazard `replaceWith()` below exists to avoid (D-TG-47).
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
     * Current team memberships — `primary` rows with no `valid_to` (T1). Several per chat.
     */
    public function scopeCurrentMembers(Builder $query): Builder
    {
        return $query->where('assignment_role', 'primary')->whereNull('valid_to');
    }

    /**
     * `team_at(chat, t)` (T3): the moderator ids on the chat's team at `$t`, sorted, read from the
     * one definition, `moderation_team_intervals` — which also follows a chat migration one hop.
     * Half-open: `valid_from` included, `valid_to` excluded. Empty — never today's team — when no
     * interval covers `$t` (O2).
     *
     * @return array<int, int>
     */
    public static function teamAt(int $telegramChatId, DateTimeInterface|string $t): array
    {
        // A raw DateTimeInterface bound straight into the query builder is formatted by the
        // *connection's* date format (no microseconds), which can put a boundary instant on the
        // wrong side of a microsecond-precision `valid_from`/`valid_to` (D-TG-47).
        $at = $t instanceof DateTimeInterface ? $t->format('Y-m-d H:i:s.uP') : $t;

        return DB::table('moderation_team_intervals')
            ->where('telegram_chat_id', $telegramChatId)
            ->where('valid_from', '<=', $at)
            ->where(fn ($q) => $q->whereNull('valid_to')->orWhere('valid_to', '>', $at))
            ->distinct()
            ->orderBy('moderator_id')
            ->pluck('moderator_id')
            ->map(fn ($id): int => (int) $id)
            ->all();
    }

    /**
     * T4: adds `$moderatorId` to the chat's team from `$since` (default: now). Nobody else's
     * membership is touched. Refused — `MembershipRefused`, nothing written — for an inactive
     * moderator, a start in the future or before the moderator was declared (D-TG-207), and one
     * that would overlap that moderator's own interval in this group.
     */
    public static function addMember(
        int $telegramChatId,
        int $moderatorId,
        ?DateTimeInterface $since = null,
        ?string $note = null,
        string $role = 'primary',
    ): self {
        // UTC before formatting: the stored string carries no offset, and a "since" picked in
        // Asia/Riyadh would otherwise land three hours off.
        $now = now()->utc();
        $from = Carbon::instance($since ?? $now)->utc();

        return DB::transaction(function () use ($telegramChatId, $moderatorId, $from, $now, $note, $role): self {
            static::refuseUnlessOpenable($telegramChatId, $moderatorId, $from, $now);

            return static::create([
                'telegram_chat_id' => $telegramChatId,
                'moderator_id' => $moderatorId,
                'assignment_role' => $role,
                'valid_from' => $from->format('Y-m-d H:i:s.u'),
                'note' => $note,
            ]);
        });
    }

    /**
     * T5: ends this membership now. Returns whether it was current — an ended row is left exactly
     * as it is.
     */
    public function end(): bool
    {
        $updated = static::query()
            ->where('id', $this->id)
            ->whereNull('valid_to')
            ->update(['valid_to' => now()->utc()->format('Y-m-d H:i:s.u')]);

        $this->refresh();

        return $updated === 1;
    }

    /**
     * T5, the handover protocol of `contracts/moderator-ownership.md` §2 for one member: close this
     * membership, open the successor's, one transaction, one **PHP** `now()` value bound to both
     * `valid_to` and `valid_from` — never two `now()` calls, which is the PHP-side hazard that
     * leaves a hole no constraint detects. Every other member of the team is untouched.
     */
    public function replaceWith(int $successorId, ?string $note = null): self
    {
        // Pre-formatted to a string, not left as a Carbon instance: the bulk `update()` below goes
        // through the query builder rather than `setAttribute()`, so it would otherwise be
        // serialized using the *connection's* date format (no microseconds) instead of this
        // model's `$dateFormat` — and truncating either side breaks "one value, bound to both
        // sides" (D-TG-47) even though only one `now()` call is made.
        $now = now()->utc();
        $at = $now->format('Y-m-d H:i:s.u');

        return DB::transaction(function () use ($successorId, $note, $now, $at): self {
            $closed = static::query()
                ->where('id', $this->id)
                ->whereNull('valid_to')
                ->update(['valid_to' => $at]);
            if ($closed !== 1) {
                throw new MembershipRefused('not_current');
            }

            static::refuseUnlessOpenable($this->telegram_chat_id, $successorId, $now, $now);

            return static::create([
                'telegram_chat_id' => $this->telegram_chat_id,
                'moderator_id' => $successorId,
                'assignment_role' => 'primary',
                'valid_from' => $at,
                'note' => $note,
            ]);
        });
    }

    /**
     * T4's refusals, inside the caller's transaction. An unknown moderator is left to the foreign
     * key, which refuses it with the same rollback.
     */
    private static function refuseUnlessOpenable(
        int $telegramChatId,
        int $moderatorId,
        Carbon $from,
        Carbon $now,
    ): void {
        $moderator = Moderator::find($moderatorId);
        if ($moderator === null) {
            return;
        }
        if (! $moderator->is_active) {
            throw new MembershipRefused('inactive');
        }
        if ($from->greaterThan($now)) {
            throw new MembershipRefused('future');
        }
        if ($moderator->created_at !== null && $from->lessThan($moderator->created_at)) {
            throw new MembershipRefused('before_declared');
        }

        $overlaps = static::query()
            ->where('telegram_chat_id', $telegramChatId)
            ->where('moderator_id', $moderatorId)
            ->where(fn (Builder $q) => $q->whereNull('valid_to')
                ->orWhere('valid_to', '>', $from->format('Y-m-d H:i:s.u')))
            ->exists();
        if ($overlaps) {
            throw new MembershipRefused('overlap');
        }
    }
}
