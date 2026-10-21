<?php

namespace App\Filament\Pages;

use App\Filament\Pages\Concerns\AttentionMetrics;
use App\Filament\Pages\Concerns\ClassificationMetrics;
use App\Filament\Resources\Incidents\Actions\OpenIncidentAction;
use App\Filament\Support\ModelView;
use App\Filament\Support\TeamAssignment;
use App\Models\AttentionItem;
use App\Models\Moderator;
use App\Models\TelegramChat;
use App\Models\TelegramMessage;
use App\Support\PanelLocale;
use BackedEnum;
use Carbon\CarbonInterval;
use Closure;
use Filament\Actions\Action;
use Filament\Actions\ActionGroup;
use Filament\Forms\Components\Select;
use Filament\Pages\Page;
use Filament\Support\Icons\Heroicon;
use Filament\Tables\Columns\TextColumn;
use Filament\Tables\Concerns\InteractsWithTable;
use Filament\Tables\Contracts\HasTable;
use Filament\Tables\Filters\Filter;
use Filament\Tables\Table;
use Illuminate\Database\Eloquent\Builder;
use Illuminate\Support\Carbon;
use Illuminate\Support\Collection;
use Illuminate\Support\Facades\Auth;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Str;
use UnitEnum;

/**
 * One screen showing every question still waiting, newest first (sortable: one click on "Waiting"
 * shows the longest-waiting first — P1 as amended 2026-10-17), with a live waiting time
 * (`control-panel-attention.md` §1, T050-T052). A custom page with a table, not a resource: the
 * only writes an attention item ever takes are dismiss and hand-open (Phase 6), both actions —
 * never operator-created CRUD (D-TG-93).
 *
 * The table is scoped to `status = 'open'` — an answered, dismissed or expired item has left the
 * "still waiting" picture by definition (`data-model.md` §3); this milestone's figures table
 * (Phase 8) is where every status is counted.
 *
 * Phase 6 (US4) adds the rule set's corrections: dismiss row actions and one hand-open header
 * action, both going through `AttentionItem::closeIfOpen()` / a guarded create so the invariant
 * holds from `tinker` too. **No bulk action anywhere** — dismissing twenty items with one click is
 * how a false-positive count stops meaning anything (`control-panel-attention.md` §2 P5).
 *
 * TG-M5.3 (`specs/011-tg-m5-3-attention-judgement/contracts/dismissal-reasons.md` K1-K4) makes it
 * three dismiss row actions: "Member discussion" sits between the two originals, on an item of any
 * source, and all three share one confirmation that states each reason's meaning (K2).
 *
 * TG-M2.1 (`specs/012-tg-m2-1-group-teams/contracts/group-teams.md` §5): "Responsible" becomes
 * **Assigned** — read from `attention_item_assignee`, never computed here (S1) — and a **Mine**
 * filter is on by default for a moderator's own account (S2). A dismissal by a linked account
 * records its moderator (C1).
 */
class LiveAttentionQueue extends Page implements HasTable
{
    use AttentionMetrics;
    use ClassificationMetrics;
    use InteractsWithTable;

    /**
     * Q1: the page's "Model's view" labels, keyed by item id — one query for every row on the
     * page (`classificationLabelsForItems`, C6), never one per row.
     *
     * @var array<int, object>|null
     */
    private ?array $modelsViewLabels = null;

    protected static string|BackedEnum|null $navigationIcon = Heroicon::OutlinedQueueList;

    public static function getNavigationGroup(): string|UnitEnum|null
    {
        return __('Moderation Intelligence');
    }

    public static function getNavigationLabel(): string
    {
        return __('Live Attention Queue');
    }

    public function getTitle(): string
    {
        return __('Live Attention Queue');
    }

    /**
     * The figures table's period filter (T074), typed and read by the operator in
     * `Asia/Riyadh` calendar days (FR-060, D-TG-56) — the store stays UTC; only the boundary is
     * converted, once, in `periodBounds()`.
     */
    public string $periodFrom = '';

    public string $periodTo = '';

    public function mount(): void
    {
        $this->periodTo = now('Asia/Riyadh')->toDateString();
        $this->periodFrom = now('Asia/Riyadh')->subDays(29)->toDateString();
    }

    protected string $view = 'filament.pages.live-attention-queue';

    /**
     * K2: the one confirmation every dismiss action shows, so the operator reads all three meanings
     * whichever button they pressed. "Message removed" stays the operator's own judgement (P7).
     */
    private const DISMISS_CONFIRMATION = 'Not a real question: not a question or request at all; nothing to answer. '
        .'Member discussion: a real question or discussion between members; no moderator was needed. '
        .'Answered by a member: a real question another member answered well enough; no moderator answer was needed. '
        .'Message removed: your own judgement that the message is gone. Telegram reports no deletion.';

    /**
     * The Replies column's facts, keyed by item id — one query for every row on the page, never
     * one per row (as `$modelsViewLabels`).
     *
     * @var array<int, object>|null
     */
    private ?array $replyFacts = null;

    /**
     * TG-M2.1 S1: the page's assignee rows and its groups' current teams, filled once per page.
     *
     * @var array<int, object>|null
     */
    private ?array $assignees = null;

    /** @var array<int, array<int, string>>|null */
    private ?array $teams = null;

    public function table(Table $table): Table
    {
        return $table
            ->query(AttentionItem::query()->where('status', 'open'))
            ->columns([
                TextColumn::make('chat.title')
                    ->label(__('Group'))
                    ->placeholder(__('(untitled)'))
                    ->extraAttributes(['dir' => 'auto']),
                // Truncated `original_text` of the burst's earliest message
                // (`control-panel-attention.md` §1) — a plain query via `anchorMessage()`, not a
                // relation the table can eager-load, since the join key is composite (P1-scale
                // queue, not a candidate for premature optimisation).
                TextColumn::make('question')
                    ->label(__('Question'))
                    ->getStateUsing(
                        fn (AttentionItem $record): string => $record->anchorMessage()?->original_text
                            ?? __('Text removed')
                    )
                    ->limit(80)
                    ->extraAttributes(['dir' => 'auto']),
                // TG-M2.1 S1: who took it and how, else the team still to take it, else "No team"
                // — never blank, so a coverage gap reads as a fact on the screen (A2).
                TextColumn::make('assigned')
                    ->label(__('Assigned'))
                    ->getStateUsing(fn (AttentionItem $record): string => $this->assignedFor($record))
                    ->color(fn (AttentionItem $record): string => $this->assignedColorFor($record))
                    ->badge(),
                TextColumn::make('status')
                    ->label(__('Status'))
                    ->formatStateUsing(fn (string $state): string => __($state))
                    ->badge(),
                // TG-M5.1 (`control-panel-classification.md` Q3): who opened the item — the stored
                // `source`, labelled, never inferred. A model-opened item's prediction is the
                // "Model's view" column beside it.
                TextColumn::make('source')
                    ->label(__('Opened by'))
                    ->formatStateUsing(fn (string $state): string => match ($state) {
                        'rule' => __('Rule'),
                        'ai' => __('Model'),
                        'operator' => __('Operator'),
                        default => $state,
                    })
                    ->badge(),
                // `since()` formats via `Carbon::diffForHumans()` computed fresh on every render
                // — server-side, and correct again on the next `poll('15s')` tick without a
                // browser-clock ticker that would disagree with every other number by the
                // viewer's clock skew (P3).
                TextColumn::make('opened_at')
                    ->label(__('Waiting'))
                    ->since()
                    ->sortable(),
                // Q1-Q2: never filters, sorts or hides a row — a plain display column, read
                // after the row set is already decided.
                TextColumn::make('models_view')
                    ->label(__("Model's view"))
                    ->getStateUsing(fn (AttentionItem $record): string => $this->modelsViewFor($record))
                    ->extraAttributes(['dir' => 'auto']),
                // Step 2 (2026-10-18): what members said back, as context for the moderator's
                // own decision — display-only (Q1-Q2): it never closes, hides or sorts a row. A
                // member's reply never answers an item.
                TextColumn::make('replies')
                    ->label(__('Replies'))
                    ->getStateUsing(fn (AttentionItem $record): string => $this->repliesFor($record)),
            ])
            ->filters([
                // TG-M2.1 S2: a default, not access control — one click shows everything.
                Filter::make('mine')
                    ->label(__('Mine'))
                    ->toggle()
                    ->default(fn (): bool => TeamAssignment::linkedModeratorId(Auth::user()) !== null)
                    ->query(function (Builder $query): Builder {
                        $moderatorId = TeamAssignment::linkedModeratorId(Auth::user());

                        return $moderatorId === null ? $query : TeamAssignment::applyMine(
                            $query, 'attention_items', 'attention_item_assignee', 'attention_item_id', $moderatorId,
                        );
                    }),
            ])
            ->recordActions([
                // Step 2 (2026-10-18): one dropdown per row keeps the table narrow. Each action
                // inside is unchanged; still no bulk action (P5).
                ActionGroup::make([
                    // All four go through the same guarded write (contract §4 C8) — a
                    // double-submitted dismissal updates zero rows and leaves the first intact.
                    Action::make('dismiss_not_a_question')
                        ->label(__('Not a real question'))
                        ->icon(Heroicon::OutlinedXCircle)
                        ->color('gray')
                        ->requiresConfirmation()
                        ->modalDescription(__(self::DISMISS_CONFIRMATION))
                        ->action(fn (AttentionItem $record) => self::dismiss($record, 'not_a_question')),
                    // TG-M5.3 K1, K4: a real question or discussion between members that needed
                    // no moderator — offered whatever opened the item.
                    Action::make('dismiss_member_discussion')
                        ->label(__('Member discussion'))
                        ->icon(Heroicon::OutlinedChatBubbleLeftRight)
                        ->color('gray')
                        ->requiresConfirmation()
                        ->modalDescription(__(self::DISMISS_CONFIRMATION))
                        ->action(fn (AttentionItem $record) => self::dismiss($record, 'member_discussion')),
                    // Step 2: a real question another member answered well enough — the moderator's
                    // judgement, never inferred from a reply.
                    Action::make('dismiss_member_answered')
                        ->label(__('Answered by a member'))
                        ->icon(Heroicon::OutlinedChatBubbleBottomCenterText)
                        ->color('gray')
                        ->requiresConfirmation()
                        ->modalDescription(__(self::DISMISS_CONFIRMATION))
                        ->action(fn (AttentionItem $record) => self::dismiss($record, 'member_answered')),
                    // P7: "message removed" is the operator's own judgement, never presented as a
                    // platform fact — Telegram reports no deletion in groups. The standing
                    // footnote saying so lives on the page view, not on this action.
                    Action::make('dismiss_message_removed')
                        ->label(__('Message removed'))
                        ->icon(Heroicon::OutlinedTrash)
                        ->color('gray')
                        ->requiresConfirmation()
                        ->modalDescription(__(self::DISMISS_CONFIRMATION))
                        ->action(fn (AttentionItem $record) => self::dismiss($record, 'message_removed')),
                    // TG-M4 (FR-072, D-TG-125): opens against the item's own anchor message. The
                    // item itself is never touched — no attention-item write is any part of
                    // opening an incident (lifecycle contract I7).
                    OpenIncidentAction::forQueueRow(),
                ])
                    ->label(__('Actions'))
                    ->icon(Heroicon::OutlinedEllipsisVertical)
                    ->tooltip(__('Actions')),
            ])
            ->headerActions([
                // P6: prevented in the form — the option list already excludes a message that
                // anchors an item, and the rule below rejects one anyway if the page went stale.
                // `uq_attention_anchor` remains the backstop the database would enforce either way.
                Action::make('open_item_by_hand')
                    ->label(__('Open item by hand'))
                    ->icon(Heroicon::OutlinedPlusCircle)
                    ->schema([
                        Select::make('telegram_message_id')
                            ->label(__('Message'))
                            ->helperText(__('Only messages that do not already anchor an item are listed.'))
                            ->options(fn (): array => self::openableMessageOptions())
                            ->searchable()
                            ->required()
                            ->rule(fn (): Closure => function (string $attribute, $value, Closure $fail): void {
                                $message = TelegramMessage::find($value);
                                if ($message === null) {
                                    $fail(__('That message no longer exists.'));

                                    return;
                                }
                                $alreadyAnchors = AttentionItem::query()
                                    ->where('telegram_chat_id', $message->telegram_chat_id)
                                    ->where('telegram_message_id', $message->message_id)
                                    ->exists();
                                if ($alreadyAnchors) {
                                    $fail(__('This message already anchors an attention item.'));
                                }
                            }),
                    ])
                    ->action(fn (array $data) => self::openByHand((int) $data['telegram_message_id'])),
            ])
            ->defaultSort('opened_at', 'desc')
            ->poll('15s')
            ->emptyStateHeading(__('Nothing waiting'))
            ->emptyStateDescription(
                __('Every question that opened an item has been answered, dismissed, or has expired.')
            );
    }

    /**
     * FR-051, FR-052: records who dismissed the item, when, and why, through the guarded write
     * every terminal transition uses (contract §4 C8). Zero rows updated — a second dismissal, a
     * closed item — is the expected, harmless outcome, not an error. TG-M2.1 C1: the moderator
     * linked to the account is recorded at write time, so the dismissal is their act.
     */
    private static function dismiss(AttentionItem $record, string $reason): void
    {
        $record->closeIfOpen('dismissed', [
            'close_reason' => $reason,
            'closed_at' => now(),
            'closed_by_user_id' => Auth::id(),
            'closed_by_moderator_id' => TeamAssignment::linkedModeratorId(Auth::user()),
        ]);
    }

    /**
     * S1: the Assigned column's words, from the page's assignee rows and current teams.
     */
    private function assignedFor(AttentionItem $record): string
    {
        $this->loadAssignment();

        return TeamAssignment::label(
            $this->assignees[$record->id] ?? null,
            $this->teams[$record->telegram_chat_id] ?? [],
            $record->status === 'open',
        );
    }

    private function assignedColorFor(AttentionItem $record): string
    {
        $this->loadAssignment();

        return TeamAssignment::color(
            $this->assignees[$record->id] ?? null,
            $this->teams[$record->telegram_chat_id] ?? [],
            $record->status === 'open',
        );
    }

    private function loadAssignment(): void
    {
        if ($this->assignees !== null) {
            return;
        }

        $records = $this->getTable()->getRecords();
        $collection = method_exists($records, 'getCollection') ? $records->getCollection() : $records;
        $this->assignees = TeamAssignment::forItems($collection->pluck('id')->all());
        $this->teams = TeamAssignment::currentTeams($collection->pluck('telegram_chat_id')->all());
    }

    /**
     * Q1: C6's label for the item — category and self-reported confidence for the earliest
     * message the model judged needs an answer, or the earliest it classified at all; where the
     * item has no classified message, the anchor's own §5 status. `$modelsViewLabels` is filled
     * once, from every item id on the current page, the first time any row asks (T074).
     */
    private function modelsViewFor(AttentionItem $record): string
    {
        $this->modelsViewLabels ??= $this->classificationLabelsForItems(
            $this->currentPageItemIds()
        );

        $label = $this->modelsViewLabels[$record->id] ?? null;

        if ($label !== null) {
            return __($label->category).' · '.ModelView::confidence($label->confidence);
        }

        return ModelView::status($record->telegram_chat_id, $record->telegram_message_id);
    }

    /**
     * Step 2: "Member replies: n", plus "the asker replied back" when the asker replied to one of
     * them; "—" when no other member replied. Read from `replyFactsForItems`, filled once per page.
     */
    private function repliesFor(AttentionItem $record): string
    {
        $this->replyFacts ??= self::replyFactsForItems($this->currentPageItemIds());
        $facts = $this->replyFacts[$record->id] ?? null;

        if ($facts === null || (int) $facts->member_replies === 0) {
            return '—';
        }

        $text = __('Member replies: :count', ['count' => (int) $facts->member_replies]);

        return $facts->asker_replied ? $text.' · '.__('the asker replied back') : $text;
    }

    /**
     * Direct replies to any of each item's burst messages (the C1/C6 membership join) from someone
     * other than a moderator and the asker, and whether the asker replied to one of those replies.
     * Counts of stored facts only — nothing here decides an item's state.
     *
     * @param  array<int, int>  $itemIds
     * @return array<int, object>
     */
    private static function replyFactsForItems(array $itemIds): array
    {
        if ($itemIds === []) {
            return [];
        }

        $rows = DB::select(
            <<<'SQL'
            WITH items AS (
                SELECT ai.id, ai.telegram_chat_id, ai.telegram_message_id, q.telegram_user_id AS asker
                FROM attention_items ai
                JOIN telegram_messages q
                  ON q.telegram_chat_id = ai.telegram_chat_id AND q.message_id = ai.telegram_message_id
                WHERE ai.id = ANY(?::bigint[])
            ),
            replies AS (
                SELECT DISTINCT i.id AS item_id, r.telegram_chat_id, r.message_id, i.asker
                FROM items i
                JOIN telegram_messages m
                  ON m.telegram_chat_id = i.telegram_chat_id
                 AND (m.attention_item_id = i.id OR m.message_id = i.telegram_message_id)
                JOIN telegram_messages r
                  ON r.telegram_chat_id = i.telegram_chat_id AND r.reply_to_message_id = m.message_id
                WHERE NOT r.is_from_moderator
                  AND r.telegram_user_id IS DISTINCT FROM i.asker
            )
            SELECT item_id,
                   count(*) AS member_replies,
                   bool_or(EXISTS (
                       SELECT 1 FROM telegram_messages b
                       WHERE b.telegram_chat_id = replies.telegram_chat_id
                         AND b.reply_to_message_id = replies.message_id
                         AND b.telegram_user_id = replies.asker
                   )) AS asker_replied
            FROM replies
            GROUP BY item_id
            SQL,
            ['{'.implode(',', array_map('intval', $itemIds)).'}'],
        );

        return collect($rows)->keyBy('item_id')->all();
    }

    /**
     * The current page's item ids — a paginator's `toArray()` is its metadata, not its rows, so
     * the underlying collection is unwrapped first (mirroring Filament's own `getTableRecords()`).
     *
     * @return array<int, int>
     */
    private function currentPageItemIds(): array
    {
        $records = $this->getTable()->getRecords();
        $collection = method_exists($records, 'getCollection') ? $records->getCollection() : $records;

        return $collection->pluck('id')->all();
    }

    /**
     * FR-054: `source='operator'`, `rule_version=NULL`, `opened_at` from the chosen message's
     * own `sent_at` — never `now()`. Assigned to nobody, like every new item (TG-M2.1 G1). The
     * anchor message's `attention_item_id` is stamped so a direct reply to it resolves through the
     * same matcher a rule-opened item's does (contract §4 (a)), and `attention_evaluated_at` so the
     * sweep never revisits it.
     */
    private static function openByHand(int $telegramMessageId): void
    {
        $message = TelegramMessage::findOrFail($telegramMessageId);

        $item = AttentionItem::create([
            'telegram_chat_id' => $message->telegram_chat_id,
            'telegram_message_id' => $message->message_id,
            'message_thread_id' => $message->message_thread_id,
            'opened_at' => $message->sent_at,
            'source' => 'operator',
            'rule_version' => null,
            'status' => 'open',
        ]);

        $message->forceFill([
            'attention_item_id' => $item->id,
            'attention_evaluated_at' => $message->attention_evaluated_at ?? now(),
        ])->save();
    }

    /**
     * Recent messages that do not already anchor an attention item, for the hand-open picker —
     * a composite exclusion (`telegram_chat_id`, `message_id`), never `message_id` alone: two
     * groups' messages share the same numbering (research Finding 2, D-TG-71).
     *
     * @return array<int, string>
     */
    private static function openableMessageOptions(): array
    {
        return TelegramMessage::query()
            ->whereNotExists(function ($query): void {
                $query->select(DB::raw(1))
                    ->from('attention_items')
                    ->whereColumn('attention_items.telegram_chat_id', 'telegram_messages.telegram_chat_id')
                    ->whereColumn('attention_items.telegram_message_id', 'telegram_messages.message_id');
            })
            ->orderByDesc('sent_at')
            ->limit(200)
            ->get()
            ->mapWithKeys(fn (TelegramMessage $message): array => [
                $message->id => sprintf(
                    '#%d — %s',
                    $message->message_id,
                    Str::limit($message->original_text ?? __('(text removed)'), 60),
                ),
            ])
            ->all();
    }

    /**
     * T074: the figures table's period, read from `$periodFrom`/`$periodTo` in `Asia/Riyadh`
     * calendar days and converted to the half-open `[from, to)` UTC bound `AttentionMetrics`'
     * queries expect (M2) — inclusive of the whole of `$periodTo`'s own day.
     *
     * @return array{0: Carbon, 1: Carbon}
     */
    private function periodBounds(): array
    {
        $from = Carbon::parse($this->periodFrom, 'Asia/Riyadh')->startOfDay()->utc();
        $to = Carbon::parse($this->periodTo, 'Asia/Riyadh')->addDay()->startOfDay()->utc();

        return [$from, $to];
    }

    /**
     * T074: one row per group with any item opened in the period — asked, answered, median,
     * p90 (or its suppression reason), max, unanswered count and share, and that group's own
     * oldest-still-waiting figure (§4 has no moderator scope, so that column is per-group only).
     */
    public function figuresByGroup(): Collection
    {
        [$from, $to] = $this->periodBounds();

        $chatIds = DB::table('attention_items')
            ->where('opened_at', '>=', $from)
            ->where('opened_at', '<', $to)
            ->distinct()
            ->pluck('telegram_chat_id');

        return TelegramChat::query()
            ->whereIn('id', $chatIds)
            ->orderBy('title')
            ->get()
            ->map(fn (TelegramChat $chat): array => array_merge(
                ['label' => $chat->title ?? __('(untitled)')],
                $this->attentionFrtStats($from, $to, null, $chat->id),
                $this->attentionUnansweredStats($from, $to, null, $chat->id),
                ['oldest_waiting_s' => $this->attentionOldestWaitingSeconds($chat->id)],
            ))
            ->values();
    }

    /**
     * TG-M2.1 (`group-teams.md` §4): one row per moderator on a team or acting in the period.
     * "My groups" is §2-§3 re-scoped to the items whose group had them on its team at `opened_at`
     * (F1) — a miss counts once for every member, and once in the group's row above (F2) — and
     * "My work" is what they themselves took and answered (F3).
     */
    public function figuresByModerator(): Collection
    {
        [$from, $to] = $this->periodBounds();

        return Moderator::query()
            ->whereIn('id', TeamAssignment::moderatorsActiveIn($from, $to))
            ->orderBy('display_name')
            ->get()
            ->map(fn (Moderator $moderator): array => array_merge(
                ['label' => $moderator->display_name],
                $this->attentionFrtStats($from, $to, $moderator->id, null),
                $this->attentionUnansweredStats($from, $to, $moderator->id, null),
                ['work' => $this->attentionWorkStats($from, $to, $moderator->id)],
            ))
            ->values();
    }

    /**
     * P10, M8: `null` renders "no data" — never "0s" — the difference between "nobody asked" and
     * "answered instantly". A real duration renders in human units (FR-060); the store stays UTC
     * throughout, this is display-only.
     */
    public function humanDuration(?float $seconds): string
    {
        if ($seconds === null) {
            return __('no data');
        }

        return CarbonInterval::seconds((int) round($seconds))->cascade()->forHumans(['short' => PanelLocale::hasShortDurationUnits()]);
    }

    /**
     * P10, M6: below `MODERATION_PERCENTILE_MIN_SAMPLES` this renders the suppression reason,
     * never a number built from too few points.
     *
     * @param  array{p90_frt: float|null, p90_suppressed: bool, answered: int}  $frt
     */
    public function p90Display(array $frt): string
    {
        if ($frt['p90_suppressed']) {
            return __('Fewer than :min answered (n=:n)', [
                'min' => $this->attentionPercentileMinSamples(),
                'n' => $frt['answered'],
            ]);
        }

        return $this->humanDuration($frt['p90_frt']);
    }

    /**
     * M9: the unanswered count is never shown as a bare number — always beside its share of
     * `opened`. `null` (nothing was asked) renders as a dash, not "0%".
     */
    public function shareDisplay(?float $share): string
    {
        return $share === null ? '—' : number_format($share * 100, 0).'%';
    }
}
