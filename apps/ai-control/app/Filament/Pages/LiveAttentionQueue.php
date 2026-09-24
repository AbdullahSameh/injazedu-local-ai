<?php

namespace App\Filament\Pages;

use App\Filament\Pages\Concerns\AttentionMetrics;
use App\Models\AttentionItem;
use App\Models\Moderator;
use App\Models\ModeratorGroupAssignment;
use App\Models\TelegramChat;
use App\Models\TelegramMessage;
use BackedEnum;
use Carbon\CarbonInterval;
use Closure;
use Filament\Actions\Action;
use Filament\Forms\Components\Select;
use Filament\Pages\Page;
use Filament\Support\Icons\Heroicon;
use Filament\Tables\Columns\TextColumn;
use Filament\Tables\Concerns\InteractsWithTable;
use Filament\Tables\Contracts\HasTable;
use Filament\Tables\Table;
use Illuminate\Support\Carbon;
use Illuminate\Support\Collection;
use Illuminate\Support\Facades\Auth;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Str;
use UnitEnum;

/**
 * One screen showing every question still waiting, oldest first, with a live waiting time
 * (`control-panel-attention.md` §1, T050-T052). A custom page with a table, not a resource: the
 * only writes an attention item ever takes are dismiss and hand-open (Phase 6), both actions —
 * never operator-created CRUD (D-TG-93).
 *
 * The table is scoped to `status = 'open'` — an answered, dismissed or expired item has left the
 * "still waiting" picture by definition (`data-model.md` §3); this milestone's figures table
 * (Phase 8) is where every status is counted.
 *
 * Phase 6 (US4) adds the rule set's corrections: two dismiss row actions and one hand-open
 * header action, both going through `AttentionItem::closeIfOpen()` / a guarded create so the
 * invariant holds from `tinker` too. **No bulk action anywhere** — dismissing twenty items with
 * one click is how a false-positive count stops meaning anything
 * (`control-panel-attention.md` §2 P5).
 */
class LiveAttentionQueue extends Page implements HasTable
{
    use AttentionMetrics;
    use InteractsWithTable;

    protected static string|BackedEnum|null $navigationIcon = Heroicon::OutlinedQueueList;

    protected static string|UnitEnum|null $navigationGroup = 'Moderation Intelligence';

    protected static ?string $navigationLabel = 'Live Attention Queue';

    protected static ?string $title = 'Live Attention Queue';

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

    public function table(Table $table): Table
    {
        return $table
            ->query(AttentionItem::query()->where('status', 'open'))
            ->columns([
                TextColumn::make('chat.title')
                    ->label('Group')
                    ->placeholder('(untitled)')
                    ->extraAttributes(['dir' => 'auto']),
                // Truncated `original_text` of the burst's earliest message
                // (`control-panel-attention.md` §1) — a plain query via `anchorMessage()`, not a
                // relation the table can eager-load, since the join key is composite (P1-scale
                // queue, not a candidate for premature optimisation).
                TextColumn::make('question')
                    ->label('Question')
                    ->getStateUsing(
                        fn (AttentionItem $record): string => $record->anchorMessage()?->original_text
                            ?? 'Text removed'
                    )
                    ->limit(80)
                    ->extraAttributes(['dir' => 'auto']),
                // Never blank, never omitted (A2): NULL is a real answer, surfaced as a badge so
                // a coverage gap reads as a fact on the screen, not as missing data.
                TextColumn::make('responsibleModerator.display_name')
                    ->label('Responsible')
                    ->placeholder('Unassigned')
                    ->badge(),
                TextColumn::make('status')
                    ->badge(),
                // `since()` formats via `Carbon::diffForHumans()` computed fresh on every render
                // — server-side, and correct again on the next `poll('15s')` tick without a
                // browser-clock ticker that would disagree with every other number by the
                // viewer's clock skew (P3).
                TextColumn::make('opened_at')
                    ->label('Waiting')
                    ->since(),
            ])
            ->recordActions([
                // Both go through the same guarded write (contract §4 C8) — a double-submitted
                // dismissal updates zero rows and leaves the first one intact.
                Action::make('dismiss_not_a_question')
                    ->label('Not a real question')
                    ->icon(Heroicon::OutlinedXCircle)
                    ->color('gray')
                    ->requiresConfirmation()
                    ->action(fn (AttentionItem $record) => self::dismiss($record, 'not_a_question')),
                // P7: "message removed" is the operator's own judgement, never presented as a
                // platform fact — Telegram reports no deletion in groups. The standing footnote
                // saying so lives on the page view, not on this action.
                Action::make('dismiss_message_removed')
                    ->label('Message removed')
                    ->icon(Heroicon::OutlinedTrash)
                    ->color('gray')
                    ->requiresConfirmation()
                    ->action(fn (AttentionItem $record) => self::dismiss($record, 'message_removed')),
            ])
            ->headerActions([
                // P6: prevented in the form — the option list already excludes a message that
                // anchors an item, and the rule below rejects one anyway if the page went stale.
                // `uq_attention_anchor` remains the backstop the database would enforce either way.
                Action::make('open_item_by_hand')
                    ->label('Open item by hand')
                    ->icon(Heroicon::OutlinedPlusCircle)
                    ->schema([
                        Select::make('telegram_message_id')
                            ->label('Message')
                            ->helperText('Only messages that do not already anchor an item are listed.')
                            ->options(fn (): array => self::openableMessageOptions())
                            ->searchable()
                            ->required()
                            ->rule(fn (): Closure => function (string $attribute, $value, Closure $fail): void {
                                $message = TelegramMessage::find($value);
                                if ($message === null) {
                                    $fail('That message no longer exists.');

                                    return;
                                }
                                $alreadyAnchors = AttentionItem::query()
                                    ->where('telegram_chat_id', $message->telegram_chat_id)
                                    ->where('telegram_message_id', $message->message_id)
                                    ->exists();
                                if ($alreadyAnchors) {
                                    $fail('This message already anchors an attention item.');
                                }
                            }),
                    ])
                    ->action(fn (array $data) => self::openByHand((int) $data['telegram_message_id'])),
            ])
            ->defaultSort('opened_at', 'asc')
            ->poll('15s')
            ->emptyStateHeading('Nothing waiting')
            ->emptyStateDescription(
                'Every question that opened an item has been answered, dismissed, or has expired.'
            );
    }

    /**
     * FR-051, FR-052: records who dismissed the item, when, and why, through the guarded write
     * every terminal transition uses (contract §4 C8). Zero rows updated — a second dismissal, a
     * closed item — is the expected, harmless outcome, not an error.
     */
    private static function dismiss(AttentionItem $record, string $reason): void
    {
        $record->closeIfOpen('dismissed', [
            'close_reason' => $reason,
            'closed_at' => now(),
            'closed_by_user_id' => Auth::id(),
        ]);
    }

    /**
     * FR-054: `source='operator'`, `rule_version=NULL`, `opened_at` from the chosen message's
     * own `sent_at` — never `now()`. `responsible_moderator_id` is snapshotted the same way a
     * rule-opened item's is (contract §5 A1), via TG-M2's own `responsibleAt` scope, not a
     * second definition of it. The anchor message's `attention_item_id` is stamped so a direct
     * reply to it resolves through the same matcher a rule-opened item's does (contract §4 (a)),
     * and `attention_evaluated_at` so the sweep never revisits it.
     */
    private static function openByHand(int $telegramMessageId): void
    {
        $message = TelegramMessage::findOrFail($telegramMessageId);

        $responsibleModeratorId = ModeratorGroupAssignment::query()
            ->responsibleAt($message->telegram_chat_id, $message->sent_at)
            ->value('moderator_id');

        $item = AttentionItem::create([
            'telegram_chat_id' => $message->telegram_chat_id,
            'telegram_message_id' => $message->message_id,
            'message_thread_id' => $message->message_thread_id,
            'opened_at' => $message->sent_at,
            'source' => 'operator',
            'rule_version' => null,
            'responsible_moderator_id' => $responsibleModeratorId,
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
                    Str::limit($message->original_text ?? '(text removed)', 60),
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
                ['label' => $chat->title ?? '(untitled)'],
                $this->attentionFrtStats($from, $to, null, $chat->id),
                $this->attentionUnansweredStats($from, $to, null, $chat->id),
                ['oldest_waiting_s' => $this->attentionOldestWaitingSeconds($chat->id)],
            ))
            ->values();
    }

    /**
     * T074: one row per moderator responsible for any item opened in the period — from
     * `attention_items.responsible_moderator_id`, the snapshot taken when each item opened, so a
     * later handover never moves a figure from the moderator who was actually responsible at the
     * time (M-A4, contract §5 A4). A NULL `responsible_moderator_id` has no isolating figure in
     * the contract (§2-§3's `:moderator` parameter means "no filter", not "filter for NULL"), so
     * unassigned items are left out of this table rather than inventing an arithmetic the
     * contract does not define.
     */
    public function figuresByModerator(): Collection
    {
        [$from, $to] = $this->periodBounds();

        $moderatorIds = DB::table('attention_items')
            ->where('opened_at', '>=', $from)
            ->where('opened_at', '<', $to)
            ->whereNotNull('responsible_moderator_id')
            ->distinct()
            ->pluck('responsible_moderator_id');

        return Moderator::query()
            ->whereIn('id', $moderatorIds)
            ->orderBy('display_name')
            ->get()
            ->map(fn (Moderator $moderator): array => array_merge(
                ['label' => $moderator->display_name],
                $this->attentionFrtStats($from, $to, $moderator->id, null),
                $this->attentionUnansweredStats($from, $to, $moderator->id, null),
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
            return 'no data';
        }

        return CarbonInterval::seconds((int) round($seconds))->cascade()->forHumans(['short' => true]);
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
            return sprintf(
                'Fewer than %d answered (n=%d)',
                $this->attentionPercentileMinSamples(),
                $frt['answered'],
            );
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
