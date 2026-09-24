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
 * T054 (US4): a hand-opened item is `source='operator'` with a NULL rule version, dated from
 * the chosen message's own `sent_at`, and behaves identically thereafter; opening a second item
 * against a message that already anchors one is prevented in the form, with
 * `uq_attention_anchor` as the backstop (`control-panel-attention.md` §2 P6,
 * `contracts/attention-rules.md` §5 A1, FR-049…FR-051).
 */
class AttentionManualAddTest extends TestCase
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
        ?string $text,
        \DateTimeInterface $sentAt,
    ): TelegramMessage {
        return TelegramMessage::forceCreate([
            'telegram_chat_id' => $chat->id,
            'message_id' => $messageId,
            'telegram_user_id' => $sender->id,
            'sent_at' => $sentAt,
            'is_service' => false,
            'is_from_moderator' => false,
            'original_text' => $text,
            'normalized_text' => $text,
            'entity_flags' => '{}',
            'source_update_id' => $this->makeCapturedUpdate($chat),
        ]);
    }

    public function test_a_hand_opened_item_is_operator_sourced_with_no_rule_version_and_dated_from_the_message(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $message = $this->makeMessage($chat, $this->makeStudent(), 1, 'مش شغال الرابط', now()->subMinutes(30));

        Livewire::test(LiveAttentionQueue::class)
            ->callTableAction('open_item_by_hand', data: ['telegram_message_id' => $message->id]);

        $item = AttentionItem::query()
            ->where('telegram_chat_id', $chat->id)
            ->where('telegram_message_id', $message->message_id)
            ->firstOrFail();

        $this->assertSame('operator', $item->source);
        $this->assertNull($item->rule_version);
        $this->assertSame('open', $item->status);
        $this->assertEquals($message->sent_at, $item->opened_at);
    }

    public function test_a_hand_opened_item_behaves_identically_thereafter(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $message = $this->makeMessage($chat, $this->makeStudent(), 1, 'مش شغال الرابط', now()->subMinutes(30));

        Livewire::test(LiveAttentionQueue::class)
            ->callTableAction('open_item_by_hand', data: ['telegram_message_id' => $message->id]);

        $item = AttentionItem::query()
            ->where('telegram_chat_id', $chat->id)
            ->where('telegram_message_id', $message->message_id)
            ->firstOrFail();

        // Visible in the waiting queue and dismissable through the same guarded action as a
        // rule-opened item — nothing distinguishes it once open (contract §4 C8, §6 G1).
        Livewire::test(LiveAttentionQueue::class)
            ->assertCanSeeTableRecords([$item])
            ->callTableAction('dismiss_not_a_question', $item);

        $this->assertSame('dismissed', $item->fresh()->status);
    }

    public function test_opening_a_second_item_against_an_already_anchoring_message_is_prevented_in_the_form(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $message = $this->makeMessage($chat, $this->makeStudent(), 1, 'مش شغال الرابط', now()->subMinutes(30));

        $existing = AttentionItem::forceCreate([
            'telegram_chat_id' => $chat->id,
            'telegram_message_id' => $message->message_id,
            'opened_at' => $message->sent_at,
            'source' => 'rule',
            'rule_version' => 1,
            'status' => 'open',
        ]);

        Livewire::test(LiveAttentionQueue::class)
            ->callTableAction('open_item_by_hand', data: ['telegram_message_id' => $message->id])
            ->assertHasTableActionErrors(['telegram_message_id']);

        $this->assertSame(1, AttentionItem::query()
            ->where('telegram_chat_id', $chat->id)
            ->where('telegram_message_id', $message->message_id)
            ->count());
        $this->assertSame('open', $existing->fresh()->status);
    }
}
