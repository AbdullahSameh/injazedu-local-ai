<?php

namespace App\Filament\Support;

use App\Models\User;
use Illuminate\Database\Eloquent\Builder;
use Illuminate\Database\Query\Builder as QueryBuilder;
use Illuminate\Support\Facades\DB;

/**
 * TG-M2.1's screen readings (`specs/012-tg-m2-1-group-teams/contracts/group-teams.md` §5): who an
 * item or incident is assigned to, read from the assignee views (G6); who is on a group's team,
 * read from `moderation_team_intervals` (T3); and the "Mine" filter (S2). Nothing here decides an
 * assignment — every fact is a view's, and the methods below only batch the reads one query per
 * page and word them.
 */
final class TeamAssignment
{
    /**
     * The assignee view rows for these attention items, keyed by item id, with the moderator's
     * name — one query for a whole page.
     *
     * @param  array<int, int>  $itemIds
     * @return array<int, object>
     */
    public static function forItems(array $itemIds): array
    {
        return self::assignees('attention_item_assignee', 'attention_item_id', $itemIds);
    }

    /**
     * @param  array<int, int>  $incidentIds
     * @return array<int, object>
     */
    public static function forIncidents(array $incidentIds): array
    {
        return self::assignees('moderation_incident_assignee', 'incident_id', $incidentIds);
    }

    /**
     * Each chat's current team, as display names, keyed by chat id (S1's "Team: …").
     *
     * @param  array<int, int>  $chatIds
     * @return array<int, array<int, string>>
     */
    public static function currentTeams(array $chatIds): array
    {
        if ($chatIds === []) {
            return [];
        }

        $now = self::now();

        return DB::table('moderation_team_intervals as t')
            ->join('moderators as m', 'm.id', '=', 't.moderator_id')
            ->whereIn('t.telegram_chat_id', array_values(array_unique($chatIds)))
            ->where('t.valid_from', '<=', $now)
            ->where(fn (QueryBuilder $q) => $q->whereNull('t.valid_to')->orWhere('t.valid_to', '>', $now))
            ->orderBy('m.display_name')
            ->get(['t.telegram_chat_id', 'm.display_name'])
            ->groupBy('telegram_chat_id')
            ->map(fn ($rows) => $rows->pluck('display_name')->unique()->values()->all())
            ->all();
    }

    /**
     * The team's names at one past instant — the incident page's "Team at flagging" (S3).
     *
     * @return array<int, string>
     */
    public static function teamNamesAt(int $chatId, \DateTimeInterface $t): array
    {
        $at = $t->format('Y-m-d H:i:s.uP');

        return DB::table('moderation_team_intervals as t')
            ->join('moderators as m', 'm.id', '=', 't.moderator_id')
            ->where('t.telegram_chat_id', $chatId)
            ->where('t.valid_from', '<=', $at)
            ->where(fn (QueryBuilder $q) => $q->whereNull('t.valid_to')->orWhere('t.valid_to', '>', $at))
            ->orderBy('m.display_name')
            ->pluck('m.display_name')
            ->unique()
            ->values()
            ->all();
    }

    /**
     * S1: the assignee and how they took it. Otherwise, while the row is still live, "Team: …"
     * or "No team"; once it is closed, "Not taken by the team" — the current team is not who
     * should take a row that has already ended (amended 2026-10-21).
     *
     * @param  array<int, string>  $teamNames
     */
    public static function label(?object $assignee, array $teamNames, bool $live = true): string
    {
        if ($assignee !== null && $assignee->assigned_moderator_id !== null) {
            return $assignee->display_name.' · '.self::viaLabel((string) $assignee->assigned_via);
        }

        if (! $live) {
            return __('Not taken by the team');
        }

        if ($teamNames !== []) {
            return __('Team: :names', ['names' => implode(', ', $teamNames)]);
        }

        return __('No team');
    }

    /**
     * The badge colour beside `label()`: taken, waiting on a team, nobody to take it, or ended
     * untaken.
     *
     * @param  array<int, string>  $teamNames
     */
    public static function color(?object $assignee, array $teamNames, bool $live = true): string
    {
        if ($assignee !== null && $assignee->assigned_moderator_id !== null) {
            return 'success';
        }

        return ! $live || $teamNames !== [] ? 'gray' : 'danger';
    }

    public static function viaLabel(string $via): string
    {
        return match ($via) {
            'reply' => __('via reply'),
            'dismissal' => __('via dismissal'),
            'reaction' => __('via reaction'),
            'ban', 'expulsion', 'restriction' => __('via a ban or restriction'),
            'panel_acknowledge' => __('via panel acknowledge'),
            'panel_resolve' => __('via panel resolve'),
            'panel_false_positive' => __('via Not a violation'),
            default => $via,
        };
    }

    /**
     * The moderator linked to this panel account (revision 0009), if any — whose acts are
     * credited (C1) and whose "Mine" is on by default (S2).
     */
    public static function linkedModeratorId(?User $user): ?int
    {
        $id = $user?->moderator?->id;

        return $id !== null ? (int) $id : null;
    }

    /**
     * S2: rows assigned to `$moderatorId`, plus unassigned rows whose group has them on its current
     * team. `$view`/`$key` name the assignee view and its id column; `$table` is the listed table.
     */
    public static function applyMine(
        Builder $query,
        string $table,
        string $view,
        string $key,
        int $moderatorId,
    ): Builder {
        $now = self::now();

        return $query->where(function (Builder $q) use ($table, $view, $key, $moderatorId, $now): void {
            $q->whereIn("{$table}.id", fn (QueryBuilder $sub) => $sub->select($key)
                ->from($view)
                ->where('assigned_moderator_id', $moderatorId))
                ->orWhere(function (Builder $unassigned) use ($table, $view, $key, $moderatorId, $now): void {
                    $unassigned
                        ->whereIn("{$table}.id", fn (QueryBuilder $sub) => $sub->select($key)
                            ->from($view)
                            ->whereNull('assigned_moderator_id'))
                        ->whereIn("{$table}.telegram_chat_id", fn (QueryBuilder $sub) => $sub
                            ->select('telegram_chat_id')
                            ->from('moderation_team_intervals')
                            ->where('moderator_id', $moderatorId)
                            ->where('valid_from', '<=', $now)
                            ->where(fn (QueryBuilder $c) => $c->whereNull('valid_to')
                                ->orWhere('valid_to', '>', $now)));
                });
        });
    }

    /**
     * The moderators a period's per-moderator figures list: anyone on a team at some instant of
     * `[$from, $to)`, plus anyone who acted in it — an answer, a dismissal or recorded evidence —
     * so covering from outside a team is never left off the table.
     *
     * @return array<int, int>
     */
    public static function moderatorsActiveIn(\DateTimeInterface $from, \DateTimeInterface $to): array
    {
        $rows = DB::select(
            <<<'SQL'
            SELECT moderator_id FROM moderation_team_intervals
            WHERE valid_from < :to1 AND (valid_to IS NULL OR valid_to > :from1)
            UNION
            SELECT first_response_moderator_id FROM attention_items
            WHERE first_response_moderator_id IS NOT NULL
              AND opened_at >= :from2 AND opened_at < :to2
            UNION
            SELECT closed_by_moderator_id FROM attention_items
            WHERE closed_by_moderator_id IS NOT NULL
              AND opened_at >= :from3 AND opened_at < :to3
            UNION
            SELECT actor_moderator_id FROM moderation_actions
            WHERE actor_moderator_id IS NOT NULL
              AND occurred_at >= :from4 AND occurred_at < :to4
            SQL,
            [
                'from1' => $from, 'to1' => $to,
                'from2' => $from, 'to2' => $to,
                'from3' => $from, 'to3' => $to,
                'from4' => $from, 'to4' => $to,
            ],
        );

        return array_map(fn (object $row): int => (int) $row->moderator_id, $rows);
    }

    /**
     * "Now" for "current team", as the panel's own clock — the same `now()` every membership write
     * stamps (`ModeratorGroupAssignment`), formatted with microseconds and offset so a boundary
     * instant is never truncated onto the wrong side (D-TG-47).
     */
    private static function now(): string
    {
        return now()->format('Y-m-d H:i:s.uP');
    }

    /**
     * @param  array<int, int>  $ids
     * @return array<int, object>
     */
    private static function assignees(string $view, string $key, array $ids): array
    {
        if ($ids === []) {
            return [];
        }

        return DB::table("{$view} as a")
            ->leftJoin('moderators as m', 'm.id', '=', 'a.assigned_moderator_id')
            ->whereIn("a.{$key}", $ids)
            ->get([
                "a.{$key} as id",
                'a.assigned_moderator_id',
                'a.assigned_at',
                'a.assigned_via',
                'm.display_name',
            ])
            ->keyBy('id')
            ->all();
    }
}
