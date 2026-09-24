<?php

namespace Tests\Feature;

use App\Filament\Pages\LiveAttentionQueue;
use App\Models\AttentionItem;
use App\Models\Moderator;
use App\Models\TelegramChat;
use App\Models\TelegramMessage;
use App\Models\TelegramUser;
use App\Models\User;
use Illuminate\Foundation\Testing\DatabaseTransactions;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Queue;
use Livewire\Livewire;
use Tests\TestCase;

/**
 * T048-T049 (US3): the Live Attention Queue — the page loads, open items are ordered
 * longest-waiting first, an answered item leaves the waiting list, an unassigned group's item
 * shows the Unassigned marker rather than being blank or omitted, a purged question renders as
 * removed while keeping its timings, and the page carries none of the standing prohibitions
 * (`control-panel-attention.md` §1, §4, FR-057).
 */
class LiveAttentionQueueTest extends TestCase
{
    use DatabaseTransactions;

    private function actingAsPanelOperator(): void
    {
        $this->actingAs(User::factory()->create(['is_panel_operator' => true]));
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

    private function makeModerator(string $name = 'Responsible'): Moderator
    {
        $identity = TelegramUser::forceCreate([
            'tg_user_id' => random_int(10_000_000, 2_000_000_000),
            'is_bot' => false,
            'first_seen_at' => now(),
            'last_seen_at' => now(),
        ]);

        return Moderator::create([
            'telegram_user_id' => $identity->id,
            'display_name' => $name,
        ]);
    }

    /**
     * A throwaway `telegram_updates` row to satisfy `source_update_id`'s FK — nothing under test
     * here reads its payload, mirroring the Python suite's own `insert_message` fixture.
     */
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

    public function test_the_page_loads(): void
    {
        $this->actingAsPanelOperator();

        Livewire::test(LiveAttentionQueue::class)->assertSuccessful();
    }

    public function test_open_items_are_ordered_longest_waiting_first(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $student = $this->makeStudent();

        $longestWaiting = $this->makeItem(
            $chat,
            $this->makeMessage($chat, $student, 1, 'متى الاختبار؟', now()->subHours(3)),
        );
        $shortestWaiting = $this->makeItem(
            $chat,
            $this->makeMessage($chat, $student, 2, 'وين رابط الزوم', now()->subMinutes(5)),
        );

        Livewire::test(LiveAttentionQueue::class)
            ->assertCanSeeTableRecords([$longestWaiting, $shortestWaiting], inOrder: true);
    }

    public function test_an_answered_item_is_absent_from_the_waiting_list(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $student = $this->makeStudent();

        $open = $this->makeItem(
            $chat,
            $this->makeMessage($chat, $student, 1, 'متى الاختبار؟', now()->subMinutes(10)),
        );
        $answered = $this->makeItem(
            $chat,
            $this->makeMessage($chat, $student, 2, 'وين رابط الزوم', now()->subMinutes(20)),
            [
                'status' => 'answered',
                'first_response_message_id' => 999,
                'first_response_at' => now()->subMinutes(15),
                'first_response_kind' => 'group_message',
            ],
        );

        Livewire::test(LiveAttentionQueue::class)
            ->assertCanSeeTableRecords([$open])
            ->assertCanNotSeeTableRecords([$answered]);
    }

    public function test_an_item_whose_group_has_no_responsible_moderator_shows_the_unassigned_marker(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $student = $this->makeStudent();
        $moderator = $this->makeModerator('Named Responsible');

        $this->makeItem(
            $chat,
            $this->makeMessage($chat, $student, 1, 'متى الاختبار؟', now()->subMinutes(10)),
        );
        $this->makeItem(
            $chat,
            $this->makeMessage($chat, $student, 2, 'وين رابط الزوم', now()->subMinutes(5)),
            ['responsible_moderator_id' => $moderator->id],
        );

        $test = Livewire::test(LiveAttentionQueue::class);
        $test->assertSee('Unassigned');
        $test->assertSee('Named Responsible');
    }

    public function test_an_item_whose_question_text_was_purged_renders_as_removed_and_keeps_its_timings(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $student = $this->makeStudent();

        $message = $this->makeMessage($chat, $student, 1, 'متى الاختبار؟', now()->subMinutes(30));
        $message->forceFill(['original_text' => null, 'text_purged_at' => now()])->save();
        $item = $this->makeItem($chat, $message->fresh());

        Livewire::test(LiveAttentionQueue::class)
            ->assertTableColumnStateSet('question', 'Text removed', $item)
            ->assertTableColumnStateSet('opened_at', $item->opened_at, $item);
    }

    /** @return array<int, string> */
    private function forbiddenActionNames(): array
    {
        return ['derive', 'rederive', 'derive_messages', 'bulk_derive', 'sync', 'run_command'];
    }

    public function test_the_page_exposes_no_control_that_posts_calls_a_model_or_triggers_a_backfill(): void
    {
        $this->actingAsPanelOperator();
        Http::preventStrayRequests();
        Queue::fake();
        $chat = $this->makeChat();
        $student = $this->makeStudent();
        $this->makeItem(
            $chat,
            $this->makeMessage($chat, $student, 1, 'متى الاختبار؟', now()->subMinutes(1)),
        );

        $test = Livewire::test(LiveAttentionQueue::class);

        foreach ($this->forbiddenActionNames() as $name) {
            $test->assertTableActionDoesNotExist($name);
        }

        Http::assertNothingSent();
        Queue::assertNothingPushed();
    }
}
