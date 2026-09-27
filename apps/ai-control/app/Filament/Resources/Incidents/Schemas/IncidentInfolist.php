<?php

namespace App\Filament\Resources\Incidents\Schemas;

use App\Filament\Resources\Incidents\Support\IncidentDisplay;
use App\Models\ModerationIncident;
use App\Models\User;
use Filament\Infolists\Components\RepeatableEntry;
use Filament\Infolists\Components\RepeatableEntry\TableColumn;
use Filament\Infolists\Components\TextEntry;
use Filament\Schemas\Components\Section;
use Filament\Schemas\Schema;
use Illuminate\Support\Carbon;

/**
 * The six questions of `control-panel-incidents.md` §1.2, on one page: what was posted, when,
 * why flagged, who handled it (the evidence trail, T055), how long, and corrected. Every moment
 * is read from the incident's own row or from `moderation_incident_state` — never computed here
 * (lifecycle contract N6) — and rendered in `Asia/Riyadh`.
 */
class IncidentInfolist
{
    public static function configure(Schema $schema): Schema
    {
        return $schema->components([
            Section::make('What was posted')
                ->schema([
                    TextEntry::make('anchor_text')
                        ->label('Message')
                        ->getStateUsing(
                            fn (ModerationIncident $record): string => $record->anchorMessage()
                                ?->original_text ?? 'Text removed'
                        )
                        ->extraAttributes(['dir' => 'auto'])
                        ->columnSpanFull(),
                    TextEntry::make('media_kind')
                        ->label('Media')
                        ->getStateUsing(
                            fn (ModerationIncident $record): string => $record->anchorMessage()
                                ?->media_kind ?? '—'
                        ),
                    TextEntry::make('entity_flags')
                        ->label('Entities')
                        ->getStateUsing(fn (ModerationIncident $record): string => self::entityFlagsSummary($record)),
                ])
                ->columns(2),

            Section::make('When')
                ->schema([
                    TextEntry::make('posted')
                        ->getStateUsing(fn (ModerationIncident $record): string => self::formatMoment($record->opened_at)),
                    TextEntry::make('flagged')
                        ->getStateUsing(fn (ModerationIncident $record): string => self::formatMoment($record->detected_at)),
                    TextEntry::make('first_acknowledgement')
                        ->label('First acknowledgement')
                        ->getStateUsing(
                            fn (ModerationIncident $record): string => self::formatMoment(
                                self::instant($record->state()?->first_acknowledgement_at)
                            )
                        ),
                    TextEntry::make('resolved_or_closed')
                        ->label('Resolved or closed')
                        ->getStateUsing(fn (ModerationIncident $record): string => self::resolvedOrClosedMoment($record)),
                ])
                ->columns(4),

            Section::make('Why flagged')
                ->schema([
                    TextEntry::make('opened_by')
                        ->label('Opened by')
                        ->getStateUsing(
                            fn (ModerationIncident $record): string => User::find($record->opened_by_user_id)
                                ?->name ?? '—'
                        ),
                    TextEntry::make('category'),
                    TextEntry::make('severity'),
                    TextEntry::make('classification')
                        ->label('Classification')
                        ->getStateUsing(fn (): string => 'operator-assigned'),
                    TextEntry::make('model_note')
                        ->label('Model')
                        ->getStateUsing(fn (): string => 'No model classification — arrives with TG-M5')
                        ->columnSpanFull(),
                ])
                ->columns(4),

            Section::make('Who handled it')
                ->schema([self::evidenceTrail()]),

            Section::make('How long')
                ->schema([
                    TextEntry::make('acknowledgement_time')
                        ->label('Acknowledgement time')
                        ->getStateUsing(
                            fn (ModerationIncident $record): string => IncidentDisplay::timingDisplay(
                                self::instant($record->state()?->first_acknowledgement_at),
                                $record->detected_at,
                            )
                        ),
                    TextEntry::make('confirmation_time')
                        ->label('Handling-confirmation time')
                        ->getStateUsing(
                            fn (ModerationIncident $record): string => IncidentDisplay::timingDisplay(
                                self::instant($record->state()?->first_confirmation_at),
                                $record->detected_at,
                            )
                        ),
                    TextEntry::make('enforcement_time')
                        ->label('Observed-enforcement time')
                        ->getStateUsing(
                            fn (ModerationIncident $record): string => IncidentDisplay::timingDisplay(
                                self::instant($record->state()?->first_enforcement_at),
                                $record->detected_at,
                            )
                        ),
                    TextEntry::make('detection_latency')
                        ->label('Detection latency (system figure)')
                        ->getStateUsing(
                            fn (ModerationIncident $record): string => IncidentDisplay::humanDuration(
                                (float) $record->detected_at->diffInSeconds($record->opened_at)
                            )
                        ),
                ])
                ->columns(4),

            Section::make('Corrected?')
                ->schema([
                    TextEntry::make('false_positive')
                        ->label('False-positive closure')
                        ->getStateUsing(fn (ModerationIncident $record): string => self::correctedText($record)),
                ]),

            TextEntry::make('outcome')
                ->label('Outcome')
                ->getStateUsing(function (ModerationIncident $record): string {
                    $state = $record->state();

                    return IncidentDisplay::outcomeLabel(
                        IncidentDisplay::outcome(
                            $state?->status ?? 'open',
                            $record->detected_at,
                            self::instant($state?->resolved_at),
                        )
                    );
                }),
        ]);
    }

    /**
     * T055: every row of `moderation_incident_evidence` for this incident, ordered
     * `(occurred_at, source_rank, evidence_id)` — the trail's own order — with the fixed kind
     * labels of `control-panel-incidents.md` §5 P17, actor resolution per lifecycle contract A3,
     * the affected member for membership kinds, and the captured event id or "panel". Notes and
     * reasons are shown exactly as the operator's own words.
     */
    private static function evidenceTrail(): RepeatableEntry
    {
        return RepeatableEntry::make('evidence')
            ->label('Evidence trail')
            ->hiddenLabel()
            ->getStateUsing(
                fn (ModerationIncident $record): array => $record->evidence()
                    ->map(fn (object $row): array => [
                        'kind' => IncidentDisplay::kindLabel($row->kind),
                        'strength' => IncidentDisplay::strengthLabel($row->strength, $row->kind),
                        'actor' => IncidentDisplay::actorLabel($row),
                        'affected_member' => IncidentDisplay::affectedMember($row) ?? '—',
                        'moment' => self::formatMoment(self::instant($row->occurred_at)),
                        'source' => $row->source_update_id !== null
                            ? "captured event #{$row->source_update_id}"
                            : 'panel',
                        'note' => $row->note ?? '—',
                    ])
                    ->all()
            )
            ->table([
                TableColumn::make('Kind'),
                TableColumn::make('Strength'),
                TableColumn::make('Actor'),
                TableColumn::make('Affected member'),
                TableColumn::make('Moment'),
                TableColumn::make('Source'),
                TableColumn::make('Note'),
            ])
            ->schema([
                TextEntry::make('kind'),
                TextEntry::make('strength'),
                TextEntry::make('actor'),
                TextEntry::make('affected_member'),
                TextEntry::make('moment'),
                TextEntry::make('source'),
                TextEntry::make('note')->extraAttributes(['dir' => 'auto']),
            ]);
    }

    private static function entityFlagsSummary(ModerationIncident $record): string
    {
        $flags = $record->anchorMessage()?->entity_flags ?? [];
        $present = array_keys(array_filter($flags));

        return $present === [] ? '—' : implode(', ', $present);
    }

    private static function resolvedOrClosedMoment(ModerationIncident $record): string
    {
        $state = $record->state();

        return self::formatMoment(self::instant($state?->resolved_at ?? $state?->closed_at));
    }

    /**
     * "not closed as a false positive" when it never was; otherwise when, by whom and the
     * operator's own reason (`control-panel-incidents.md` §1.2's "Corrected?"). Label review
     * arrives with TG-M8.
     */
    private static function correctedText(ModerationIncident $record): string
    {
        $state = $record->state();

        if ($state === null || $state->closed_at === null) {
            return 'not closed as a false positive';
        }

        $closedBy = User::find($state->closed_by_user_id)?->name ?? 'a panel account';

        return sprintf(
            '%s, by %s — %s',
            self::formatMoment(self::instant($state->closed_at)),
            $closedBy,
            $state->close_reason ?? '—',
        );
    }

    private static function formatMoment(?Carbon $moment): string
    {
        if ($moment === null) {
            return '—';
        }

        return $moment->setTimezone('Asia/Riyadh')->format('Y-m-d H:i');
    }

    private static function instant(mixed $value): ?Carbon
    {
        return $value === null ? null : Carbon::parse($value);
    }
}
