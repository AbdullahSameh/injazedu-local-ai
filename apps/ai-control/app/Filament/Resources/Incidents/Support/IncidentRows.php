<?php

namespace App\Filament\Resources\Incidents\Support;

use App\Filament\Support\TeamAssignment;
use App\Models\ModerationIncident;
use Illuminate\Support\Collection;
use WeakMap;

/**
 * The Incidents list's per-page reads (2026-11-11): each row's state, assignee and group team are
 * read once for the whole page, right after the page's rows are fetched (`Builder::afterQuery()`),
 * instead of once per column and action on every row. On production a 10-row page had made 146
 * queries, most of them a view that takes ~20 ms to plan.
 *
 * Nothing here decides anything: the rows are the views' own (`moderation_incident_state`,
 * `moderation_incident_assignee`, `moderation_team_intervals`), worded by `TeamAssignment`. An
 * incident that was not fetched with a page (a single record resolved for an action, say) is read
 * directly, as before.
 */
final class IncidentRows
{
    /** @var WeakMap<ModerationIncident, array{assignee: ?object, team: array<int, string>}>|null */
    private static ?WeakMap $assignment = null;

    /**
     * @param  Collection<int, ModerationIncident>  $incidents
     * @return Collection<int, ModerationIncident>
     */
    public static function preload(Collection $incidents): Collection
    {
        if ($incidents->isEmpty()) {
            return $incidents;
        }

        ModerationIncident::preloadStates($incidents);
        $assignees = TeamAssignment::forIncidents($incidents->pluck('id')->all());
        $teams = TeamAssignment::currentTeams($incidents->pluck('telegram_chat_id')->all());

        foreach ($incidents as $incident) {
            self::map()[$incident] = [
                'assignee' => $assignees[$incident->id] ?? null,
                'team' => $teams[$incident->telegram_chat_id] ?? [],
            ];
        }

        return $incidents;
    }

    /**
     * S1's words for the Assigned column.
     */
    public static function assignedLabel(ModerationIncident $incident): string
    {
        ['assignee' => $assignee, 'team' => $team] = self::assignment($incident);

        return TeamAssignment::label($assignee, $team, $incident->isLive());
    }

    public static function assignedColor(ModerationIncident $incident): string
    {
        ['assignee' => $assignee, 'team' => $team] = self::assignment($incident);

        return TeamAssignment::color($assignee, $team, $incident->isLive());
    }

    /**
     * @return array{assignee: ?object, team: array<int, string>}
     */
    private static function assignment(ModerationIncident $incident): array
    {
        if (self::map()->offsetExists($incident)) {
            return self::map()[$incident];
        }

        return [
            'assignee' => TeamAssignment::forIncidents([$incident->id])[$incident->id] ?? null,
            'team' => TeamAssignment::currentTeams([$incident->telegram_chat_id])[$incident->telegram_chat_id] ?? [],
        ];
    }

    /**
     * Keyed by the model instance, so an entry lives exactly as long as its row and never reaches
     * another request (or another page's fresh instances) in a long-running worker.
     *
     * @return WeakMap<ModerationIncident, array{assignee: ?object, team: array<int, string>}>
     */
    private static function map(): WeakMap
    {
        return self::$assignment ??= new WeakMap;
    }
}
