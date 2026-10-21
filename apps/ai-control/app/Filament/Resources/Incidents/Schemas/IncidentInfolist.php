<?php

namespace App\Filament\Resources\Incidents\Schemas;

use App\Filament\Resources\Incidents\Support\IncidentDisplay;
use App\Filament\Support\ModelView;
use App\Filament\Support\TeamAssignment;
use App\Models\MessageClassification;
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
            Section::make(__('What was posted'))
                ->schema([
                    TextEntry::make('anchor_text')
                        ->label(__('Message'))
                        ->getStateUsing(
                            fn (ModerationIncident $record): string => $record->anchorMessage()
                                ?->original_text ?? __('Text removed')
                        )
                        ->extraAttributes(['dir' => 'auto'])
                        ->columnSpanFull(),
                    TextEntry::make('media_kind')
                        ->label(__('Media'))
                        ->getStateUsing(
                            fn (ModerationIncident $record): string => $record->anchorMessage()
                                ?->media_kind ?? '—'
                        ),
                    TextEntry::make('entity_flags')
                        ->label(__('Entities'))
                        ->getStateUsing(fn (ModerationIncident $record): string => self::entityFlagsSummary($record)),
                ])
                ->columns(2),

            Section::make(__('When'))
                ->schema([
                    TextEntry::make('posted')
                        ->label(__('Posted'))
                        ->getStateUsing(fn (ModerationIncident $record): string => self::formatMoment($record->opened_at)),
                    TextEntry::make('flagged')
                        ->label(__('Flagged'))
                        ->getStateUsing(fn (ModerationIncident $record): string => self::formatMoment($record->detected_at)),
                    TextEntry::make('first_acknowledgement')
                        ->label(__('First acknowledgement'))
                        ->getStateUsing(
                            fn (ModerationIncident $record): string => self::formatMoment(
                                self::instant($record->state()?->first_acknowledgement_at)
                            )
                        ),
                    TextEntry::make('resolved_or_closed')
                        ->label(__('Resolved or closed'))
                        ->getStateUsing(fn (ModerationIncident $record): string => self::resolvedOrClosedMoment($record)),
                ])
                ->columns(4),

            Section::make(__('Why flagged'))
                ->schema([
                    TextEntry::make('opened_by')
                        ->label(__('Opened by'))
                        ->getStateUsing(
                            fn (ModerationIncident $record): string => match ($record->source) {
                                'ai' => __('Opened by the model'),
                                'rule' => __('Opened by the link rule'),
                                default => User::find($record->opened_by_user_id)?->name ?? '—',
                            }
                        ),
                    TextEntry::make('category')
                        ->label(__('Category'))
                        ->formatStateUsing(fn (string $state): string => __($state)),
                    TextEntry::make('severity')
                        ->label(__('Severity'))
                        ->formatStateUsing(fn (string $state): string => __($state)),
                    TextEntry::make('classification')
                        ->label(__('Classification'))
                        ->getStateUsing(
                            fn (ModerationIncident $record): string => match ($record->source) {
                                'ai' => __("the model's"),
                                'rule' => __("the link rule's: a link from a member"),
                                default => __('operator-assigned'),
                            }
                        ),
                    // §2.3, independent and list-prompted operator flags: The model's view of the
                    // anchor message — read (§5), never computed (P2).
                    TextEntry::make('models_view')
                        ->label(__("The model's view"))
                        ->getStateUsing(
                            fn (ModerationIncident $record): string => ModelView::status(
                                $record->telegram_chat_id,
                                $record->telegram_message_id,
                            )
                        )
                        ->visible(fn (ModerationIncident $record): bool => $record->source !== 'ai')
                        ->columnSpanFull(),
                    // §2.3, list-prompted only: the listing prediction's model and self-reported
                    // confidence (V2, FR-044).
                    TextEntry::make('list_prompted')
                        ->label(__('Flagged from the possible-violations list'))
                        ->getStateUsing(fn (ModerationIncident $record): string => self::listPromptedText($record))
                        ->visible(
                            fn (ModerationIncident $record): bool => $record->prompted_by_classification_id !== null
                        )
                        ->columnSpanFull(),
                    // §2.3, model-opened only: the opening prediction, in full — D1 (the
                    // TG-M4 placeholder line) is gone.
                    TextEntry::make('opening_prediction')
                        ->label(__('The opening prediction'))
                        ->getStateUsing(fn (ModerationIncident $record): string => self::openingPredictionText($record))
                        ->visible(fn (ModerationIncident $record): bool => $record->source === 'ai')
                        ->columnSpanFull(),
                ])
                ->columns(4),

            Section::make(__('Who handled it'))
                ->schema([
                    // TG-M2.1 S3: the team that counts this incident (the team at the flag) and
                    // the first team member who acted — both read, never computed (G6).
                    TextEntry::make('team_at_flagging')
                        ->label(__('Team at flagging'))
                        ->getStateUsing(fn (ModerationIncident $record): string => self::teamAtFlagging($record)),
                    TextEntry::make('assigned')
                        ->label(__('Assigned'))
                        ->getStateUsing(fn (ModerationIncident $record): string => self::assignedText($record)),
                    // TG-M4.1: who resolved it, how and when — the state view's resolving row,
                    // which may be a colleague of the assigned moderator (requirement 2).
                    TextEntry::make('resolved_by')
                        ->label(__('Resolved by'))
                        ->getStateUsing(fn (ModerationIncident $record): string => self::resolvedByText($record))
                        ->visible(fn (ModerationIncident $record): bool => $record->state()?->status === 'resolved'),
                    self::evidenceTrail()->columnSpanFull(),
                ])
                ->columns(3),

            Section::make(__('How long'))
                ->schema([
                    TextEntry::make('acknowledgement_time')
                        ->label(__('Acknowledgement time'))
                        ->getStateUsing(
                            fn (ModerationIncident $record): string => IncidentDisplay::timingDisplay(
                                self::instant($record->state()?->first_acknowledgement_at),
                                $record->detected_at,
                            )
                        ),
                    TextEntry::make('confirmation_time')
                        ->label(__('Handling-confirmation time'))
                        ->getStateUsing(
                            fn (ModerationIncident $record): string => IncidentDisplay::timingDisplay(
                                self::instant($record->state()?->first_confirmation_at),
                                $record->detected_at,
                            )
                        ),
                    TextEntry::make('enforcement_time')
                        ->label(__('Observed-enforcement time'))
                        ->getStateUsing(
                            fn (ModerationIncident $record): string => IncidentDisplay::timingDisplay(
                                self::instant($record->state()?->first_enforcement_at),
                                $record->detected_at,
                            )
                        ),
                    TextEntry::make('detection_latency')
                        ->label(__('Detection latency (system figure)'))
                        ->getStateUsing(
                            fn (ModerationIncident $record): string => IncidentDisplay::humanDuration(
                                (float) $record->detected_at->diffInSeconds($record->opened_at)
                            )
                        ),
                ])
                ->columns(4),

            Section::make(__('Corrected?'))
                ->schema([
                    TextEntry::make('false_positive')
                        ->label(__('False-positive closure'))
                        ->getStateUsing(fn (ModerationIncident $record): string => self::correctedText($record)),
                ]),

            TextEntry::make('outcome')
                ->label(__('Outcome'))
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
            ->label(__('Evidence trail'))
            ->hiddenLabel()
            ->getStateUsing(
                fn (ModerationIncident $record): array => $record->evidence()
                    ->map(fn (object $row): array => [
                        'kind' => IncidentDisplay::kindLabel($row->kind, $row->strength),
                        'strength' => IncidentDisplay::strengthLabel($row->strength, $row->kind),
                        'actor' => IncidentDisplay::actorLabel($row),
                        'affected_member' => IncidentDisplay::affectedMember($row) ?? '—',
                        'moment' => self::formatMoment(self::instant($row->occurred_at)),
                        'source' => $row->source_update_id !== null
                            ? __('captured event #:id', ['id' => $row->source_update_id])
                            : __('panel'),
                        'note' => $row->note ?? '—',
                    ])
                    ->all()
            )
            ->table([
                TableColumn::make(__('Kind')),
                TableColumn::make(__('Strength')),
                TableColumn::make(__('Actor')),
                TableColumn::make(__('Affected member')),
                TableColumn::make(__('Moment')),
                TableColumn::make(__('Source')),
                TableColumn::make(__('Note')),
            ])
            ->schema([
                TextEntry::make('kind')->label(__('Kind')),
                TextEntry::make('strength')->label(__('Strength')),
                TextEntry::make('actor')->label(__('Actor')),
                TextEntry::make('affected_member')->label(__('Affected member')),
                TextEntry::make('moment')->label(__('Moment')),
                TextEntry::make('source')->label(__('Source')),
                TextEntry::make('note')->label(__('Note'))->extraAttributes(['dir' => 'auto']),
            ]);
    }

    /**
     * §2.3: the listing prediction's model and self-reported confidence — read from
     * `prompted_by_classification_id`, never recomputed.
     */
    private static function listPromptedText(ModerationIncident $record): string
    {
        $prediction = MessageClassification::find($record->prompted_by_classification_id);

        if ($prediction === null) {
            return '—';
        }

        return __(':model, :confidence', [
            'model' => $prediction->modelProfile?->name ?? '—',
            'confidence' => ModelView::confidence($prediction->confidence),
        ]);
    }

    /**
     * §2.3: the prediction that opened the incident — category, severity, needs-response,
     * needs-moderation, self-reported confidence, model, instruction version, vocabulary version
     * and when it was made — read from `message_classification_id` (`ck_incident_ai_link`
     * guarantees it is set and points at this incident's own message).
     */
    private static function openingPredictionText(ModerationIncident $record): string
    {
        $prediction = MessageClassification::find($record->message_classification_id);

        if ($prediction === null) {
            return '—';
        }

        return __(':category · severity :severity · needs response: :needs_response · needs moderation: :needs_moderation · :confidence · model :model · instruction :prompt · vocabulary :taxonomy · :moment', [
            'category' => __($prediction->category),
            'severity' => __($prediction->severity),
            'needs_response' => $prediction->needs_response ? __('yes') : __('no'),
            'needs_moderation' => $prediction->needs_moderation ? __('yes') : __('no'),
            'confidence' => ModelView::confidence($prediction->confidence),
            'model' => $prediction->modelProfile?->name ?? '—',
            'prompt' => $prediction->prompt_version,
            'taxonomy' => (int) $prediction->taxonomy_version,
            'moment' => self::formatMoment($prediction->created_at),
        ]);
    }

    private static function entityFlagsSummary(ModerationIncident $record): string
    {
        $flags = $record->anchorMessage()?->entity_flags ?? [];
        $present = array_keys(array_filter($flags));

        return $present === [] ? '—' : implode(', ', $present);
    }

    /**
     * The resolving row of `moderation_incident_state` (S3): its actor by lifecycle contract
     * A3's order, its kind and its moment — read, never recomputed.
     */
    private static function resolvedByText(ModerationIncident $record): string
    {
        $state = $record->state();

        if ($state === null || $state->resolved_at === null) {
            return '—';
        }

        $actor = IncidentDisplay::actorLabel((object) [
            'actor_is_anonymous' => (bool) $state->resolved_by_anonymous,
            'actor_moderator_id' => $state->resolved_by_moderator_id,
            'actor_telegram_user_id' => $state->resolved_by_telegram_user_id,
            'panel_user_id' => $state->resolved_by_user_id,
        ]);

        return $actor.' · '.IncidentDisplay::kindLabel((string) $state->resolution_kind, $state->resolution_strength)
            .' · '.self::formatMoment(self::instant($state->resolved_at));
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
            return __('not closed as a false positive');
        }

        $closedBy = User::find($state->closed_by_user_id)?->name ?? __('a panel account');

        return __(':moment, by :user — :reason', [
            'moment' => self::formatMoment(self::instant($state->closed_at)),
            'user' => $closedBy,
            'reason' => $state->close_reason ?? '—',
        ]);
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

    private static function teamAtFlagging(ModerationIncident $record): string
    {
        $names = TeamAssignment::teamNamesAt($record->telegram_chat_id, $record->detected_at);

        return $names === [] ? __('No team') : implode(', ', $names);
    }

    private static function assignedText(ModerationIncident $record): string
    {
        $assignee = TeamAssignment::forIncidents([$record->id])[$record->id] ?? null;

        if ($assignee === null || $assignee->assigned_moderator_id === null) {
            return $record->isLive()
                ? __('Not yet — the first team member to act takes it')
                : __('Not taken by the team');
        }

        return $assignee->display_name.' · '.TeamAssignment::viaLabel((string) $assignee->assigned_via)
            .' · '.self::formatMoment(self::instant($assignee->assigned_at));
    }
}
