<?php

namespace App\Filament\Resources\Incidents\Support;

use App\Models\Moderator;
use App\Models\TelegramUser;
use App\Models\User;
use App\Support\PanelLocale;
use Carbon\CarbonInterval;
use Illuminate\Support\Carbon;

/**
 * Rendering helpers shared by the list table (T057), the view page's infolist (T054-T055) and
 * `standing-notices.blade.php` (T056) — every incident figure here is display-only: it reads
 * `moderation_incident_state` (or a value already derived from it) and formats it, never
 * recomputes a status (lifecycle contract N6). Kind and strength labels are the fixed vocabulary
 * of `control-panel-incidents.md` §5 P17 — none of them may ever contain a word implying a
 * deletion was observed (`IncidentWordingTest`).
 */
class IncidentDisplay
{
    private const KIND_LABELS = [
        'ban' => 'Banned',
        'expulsion' => 'Expelled from the group (not banned)',
        'restriction' => 'Restricted',
        'reversal' => 'Unban / restriction lifted — no effect',
        'reaction' => 'Reaction',
        'reply' => 'Direct reply',
        'panel_acknowledge' => 'Acknowledged (panel)',
        'panel_resolve' => 'Resolved (panel)',
        'panel_false_positive' => 'Not a violation (panel)',
    ];

    private const STRENGTH_LABELS = [
        'acknowledgement' => 'Acknowledgement',
        'enforcement' => 'Enforcement',
        'confirmation' => 'Confirmation',
    ];

    /**
     * P10, M18: `null` renders "no data" — never "0s" — for an aggregate figure. A single
     * incident's own timing goes through `timingDisplay()` instead, which renders "no evidence".
     */
    public static function humanDuration(?float $seconds): string
    {
        if ($seconds === null) {
            return __('no data');
        }

        return CarbonInterval::seconds((int) round($seconds))->cascade()->forHumans(['short' => PanelLocale::hasShortDurationUnits()]);
    }

    /**
     * M19: one incident's own timing — its earliest evidence of a kind minus `detected_at`. NULL
     * (that kind never arrived) renders "no evidence"; a negative difference (the evidence
     * predates the flag) renders "acted before flagging", never a duration.
     */
    public static function timingDisplay(?Carbon $first, Carbon $detectedAt): string
    {
        if ($first === null) {
            return __('no evidence');
        }

        $seconds = $first->getTimestamp() - $detectedAt->getTimestamp();

        if ($seconds < 0) {
            return __('acted before flagging');
        }

        return self::humanDuration($seconds);
    }

    /**
     * `control-panel-incidents.md` §1.1's Age/took column: `now() − detected_at` while still
     * open or acknowledged, `resolved_at − detected_at` once resolved, `closed_at − detected_at`
     * once closed as a false positive — "acted before flagging" when that difference is negative
     * (a resolution or closure dated before the flag, the first clarification).
     */
    public static function ageOrTook(?string $status, Carbon $detectedAt, ?Carbon $resolvedAt, ?Carbon $closedAt): string
    {
        $reference = match ($status) {
            'resolved' => $resolvedAt,
            'closed_false_positive' => $closedAt,
            default => now(),
        };

        if ($reference === null) {
            return __('no evidence');
        }

        $seconds = $reference->getTimestamp() - $detectedAt->getTimestamp();

        if ($seconds < 0) {
            return __('acted before flagging');
        }

        return self::humanDuration($seconds);
    }

    /**
     * `incident-metrics.md` §2 M4-M7, evaluated for exactly one incident rather than an
     * aggregate: the same precedence the SQL's `FILTER` clauses express, against the ceiling
     * `detected_at + config('moderation.incident_max_age_s')` seconds. Not a second definition of
     * *status* (S1 stays the view's alone) — this classifies an already-derived status against
     * the ceiling, exactly as the figures table will (Phase 8).
     */
    public static function outcome(string $status, Carbon $detectedAt, ?Carbon $resolvedAt): string
    {
        if ($status === 'closed_false_positive') {
            return 'false_positive';
        }

        $ceiling = $detectedAt->clone()->addSeconds((int) config('moderation.incident_max_age_s'));

        if ($resolvedAt !== null && $resolvedAt->lessThanOrEqualTo($ceiling)) {
            return 'handled';
        }

        if (now()->greaterThan($ceiling)) {
            return 'missed';
        }

        return 'within_window';
    }

    public static function outcomeLabel(string $outcome): string
    {
        return match ($outcome) {
            'handled' => __('Handled'),
            'missed' => __('Missed'),
            'within_window' => __('Within window'),
            'false_positive' => __('False positive'),
            default => $outcome,
        };
    }

    public static function kindLabel(string $kind): string
    {
        return __(self::KIND_LABELS[$kind] ?? $kind);
    }

    /**
     * §1.3: strength, or "no effect" for a reversal — the one kind whose null strength means
     * something happened but resolved nothing, as distinct from a closure's null strength.
     */
    public static function strengthLabel(?string $strength, string $kind): string
    {
        if ($strength !== null) {
            return __(self::STRENGTH_LABELS[$strength] ?? $strength);
        }

        return $kind === 'reversal' ? __('no effect') : '—';
    }

    /**
     * Lifecycle contract A3: a moderator through `actor_moderator_id`, an unmapped performer
     * through `actor_telegram_user_id`, an anonymous one through `actor_is_anonymous`, a panel
     * account through `panel_user_id`. Checked in that order because a captured row can carry
     * both `actor_telegram_user_id` and `actor_moderator_id` at once (the performer's own
     * identity plus their moderator mapping) — the moderator name is the more specific fact.
     */
    public static function actorLabel(object $evidenceRow): string
    {
        if ($evidenceRow->actor_is_anonymous) {
            return __('anonymous administrator');
        }

        if ($evidenceRow->actor_moderator_id !== null) {
            return Moderator::find($evidenceRow->actor_moderator_id)?->display_name ?? __('Moderator');
        }

        if ($evidenceRow->actor_telegram_user_id !== null) {
            return self::platformName($evidenceRow->actor_telegram_user_id);
        }

        if ($evidenceRow->panel_user_id !== null) {
            return User::find($evidenceRow->panel_user_id)?->name ?? __('Panel account');
        }

        return '—';
    }

    public static function affectedMember(object $evidenceRow): ?string
    {
        if ($evidenceRow->subject_telegram_user_id === null) {
            return null;
        }

        return self::platformName($evidenceRow->subject_telegram_user_id);
    }

    private static function platformName(int $telegramUserId): string
    {
        $user = TelegramUser::find($telegramUserId);

        if ($user === null) {
            return __('user #:id', ['id' => $telegramUserId]);
        }

        return $user->display_name ?? $user->username ?? __('user #:id', ['id' => $user->tg_user_id]);
    }
}
