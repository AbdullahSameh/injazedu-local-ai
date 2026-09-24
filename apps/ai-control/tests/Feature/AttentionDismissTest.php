<?php

namespace Tests\Feature;

use App\Filament\Pages\LiveAttentionQueue;
use App\Models\AttentionItem;
use App\Models\TelegramChat;
use App\Models\TelegramMessage;
use App\Models\TelegramUser;
use App\Models\User;
use Illuminate\Foundation\Testing\DatabaseTransactions;
use Illuminate\Support\Facades\DB;
use Livewire\Livewire;
use Tests\TestCase;

/**
 * T053 (US4): dismissing an open item records the reason, the panel account and the moment; a
 * dismissed item leaves the unanswered count and contributes no response time; a
 * double-submitted dismissal updates zero rows the second time and does not corrupt the first;
 * a later moderator message does not reopen or close it (`control-panel-attention.md` §2,
 * FR-047, FR-048, contract §4 C8).
 */
class AttentionDismissTest extends TestCase
{
    use DatabaseTransactions;

    private function actingAsPanelOperator(): User
    {
        $user = User::factory()->create(['is_panel_operator' => true]);
        $this->actingAs($user);

        return $user;
    }

    private function makeChat(array $overrides = []): TelegramChat
    {
        return TelegramChat::forceCreate(array_merge([
            'chat_id' => -random_int(10_000_000, 2_000_000_000),
            'chat_type' => 'group',
            'title' => 'Attention Group',
            'is_monitored' => true,
        ], $overrides));
    }

    private function makeStudent(): TelegramUser
    {
        return TelegramUser::forceCreate([
            'tg_user_id' => random_int(10_000_000, 2_000_000_000),
            'is_bot' => false,
            'first_seen_at' => now(),
            'last_seen_at' => now(),
        ]);
    }

    private function makeCapturedUpdate(TelegramChat $chat): int
    {
        return DB::table('telegram_updates')->insertGetId([
            'bot_id' => random_int(10_000_000, 2_000_000_000),
            'update_id' => random_int(10_000_000, 2_000_000_000),
            'update_type' => 'message',
            'chat_id' => $chat->chat_id,
            'payload' => json_encode(['message' => []]),
            'received_at' => now(),
        ]);
    }

    private function makeMessage(
        TelegramChat $chat,
        TelegramUser $sender,
        int $messageId,
        \DateTimeInterface $sentAt,
    ): TelegramMessage {
        return TelegramMessage::forceCreate([
            'telegram_chat_id' => $chat->id,
            'message_id' => $messageId,
            'telegram_user_id' => $sender->id,
            'sent_at' => $sentAt,
            'is_service' => false,
            'is_from_moderator' => false,
            'original_text' => 'متى الاختبار؟',
            'normalized_text' => 'متي الاختبار؟',
            'entity_flags' => '{}',
            'source_update_id' => $this->makeCapturedUpdate($chat),
        ]);
    }

    private function makeItem(TelegramChat $chat, TelegramMessage $message, array $overrides = []): AttentionItem
    {
        return AttentionItem::forceCreate(array_merge([
            'telegram_chat_id' => $chat->id,
            'telegram_message_id' => $message->message_id,
            'opened_at' => $message->sent_at,
            'source' => 'rule',
            'rule_version' => 1,
            'status' => 'open',
        ], $overrides));
    }

    public function test_dismissing_not_a_question_records_the_reason_account_and_moment(): void
    {
        $user = $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $item = $this->makeItem($chat, $this->makeMessage($chat, $this->makeStudent(), 1, now()->subMinutes(10)));

        Livewire::test(LiveAttentionQueue::class)
            ->callTableAction('dismiss_not_a_question', $item);

        $item->refresh();
        $this->assertSame('dismissed', $item->status);
        $this->assertSame('not_a_question', $item->close_reason);
        $this->assertSame($user->id, $item->closed_by_user_id);
        $this->assertNotNull($item->closed_at);
    }

    public function test_dismissing_message_removed_records_that_reason(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $item = $this->makeItem($chat, $this->makeMessage($chat, $this->makeStudent(), 1, now()->subMinutes(10)));

        Livewire::test(LiveAttentionQueue::class)
            ->callTableAction('dismiss_message_removed', $item);

        $item->refresh();
        $this->assertSame('dismissed', $item->status);
        $this->assertSame('message_removed', $item->close_reason);
    }

    public function test_a_dismissed_item_stops_ageing_and_leaves_the_unanswered_count(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $item = $this->makeItem($chat, $this->makeMessage($chat, $this->makeStudent(), 1, now()->subMinutes(10)));

        $unansweredBefore = AttentionItem::query()->whereIn('status', ['open', 'expired'])->count();

        Livewire::test(LiveAttentionQueue::class)
            ->callTableAction('dismiss_not_a_question', $item)
            ->assertCanNotSeeTableRecords([$item->fresh()]);

        $unansweredAfter = AttentionItem::query()->whereIn('status', ['open', 'expired'])->count();
        $this->assertSame($unansweredBefore - 1, $unansweredAfter);
        $this->assertNull($item->fresh()->first_response_at);
    }

    public function test_a_double_submitted_dismissal_updates_zero_rows_the_second_time(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $item = $this->makeItem($chat, $this->makeMessage($chat, $this->makeStudent(), 1, now()->subMinutes(10)));

        $first = $item->closeIfOpen('dismissed', [
            'close_reason' => 'not_a_question',
            'closed_at' => now(),
            'closed_by_user_id' => auth()->id(),
        ]);
        $firstClosedAt = $item->fresh()->closed_at;

        $second = $item->closeIfOpen('dismissed', [
            'close_reason' => 'message_removed',
            'closed_at' => now()->addMinute(),
            'closed_by_user_id' => auth()->id(),
        ]);

        $this->assertSame(1, $first);
        $this->assertSame(0, $second);
        $item->refresh();
        $this->assertSame('not_a_question', $item->close_reason);
        $this->assertEquals($firstClosedAt, $item->closed_at);
    }

    public function test_a_later_moderator_message_does_not_reopen_or_close_a_dismissed_item(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $item = $this->makeItem($chat, $this->makeMessage($chat, $this->makeStudent(), 1, now()->subMinutes(10)));

        $item->closeIfOpen('dismissed', [
            'close_reason' => 'not_a_question',
            'closed_at' => now(),
            'closed_by_user_id' => auth()->id(),
        ]);

        // What a matched moderator reply would attempt to write, mirroring `close_item`'s guard
        // (contract §4 C8) — updates zero rows because status is no longer 'open'.
        $rows = $item->closeIfOpen('answered', [
            'first_response_message_id' => 999,
            'first_response_at' => now(),
            'first_response_kind' => 'group_message',
        ]);

        $this->assertSame(0, $rows);
        $this->assertSame('dismissed', $item->fresh()->status);
    }
}
