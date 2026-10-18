<?php

namespace Tests\Feature;

use App\Filament\Pages\ClassificationAccuracy;
use App\Filament\Pages\LiveAttentionQueue;
use App\Models\AttentionItem;
use App\Models\TelegramChat;
use App\Models\TelegramMessage;
use App\Models\TelegramUser;
use App\Models\User;
use Filament\Actions\ActionGroup;
use Illuminate\Foundation\Testing\DatabaseTransactions;
use Illuminate\Support\Facades\DB;
use Livewire\Livewire;
use Tests\TestCase;

/**
 * Step 2 of `docs/plan/telegram/tg-day-one-investigation-and-link-rule-plan.md` (operator
 * decisions 2026-10-18), on the Live Attention Queue:
 * - **"Answered by a member"** (`member_answered`): a fourth dismissal reason, through the same
 *   guarded write, counted in its own breakdown part.
 * - **One dropdown per row**: the four dismissals and Open incident, so the table stays narrow.
 *   It is still one confirmation (K2) and there is still no bulk action (P5).
 * - **Replies**: a display-only column. It counts direct replies from other members (never a
 *   moderator's, never the asker's own) and says whether the asker replied back to one. It never
 *   closes, hides or sorts anything.
 */
class AttentionQueueStepTwoTest extends TestCase
{
    use DatabaseTransactions;

    private function actingAsPanelOperator(): User
    {
        $user = User::factory()->create(['is_panel_operator' => true]);
        $this->actingAs($user);

        return $user;
    }

    private function makeChat(): TelegramChat
    {
        return TelegramChat::forceCreate([
            'chat_id' => -random_int(10_000_000, 2_000_000_000),
            'chat_type' => 'group',
            'title' => 'Step Two Group',
            'is_monitored' => true,
        ]);
    }

    private function makePerson(): TelegramUser
    {
        return TelegramUser::forceCreate([
            'tg_user_id' => random_int(10_000_000, 2_000_000_000),
            'is_bot' => false,
        ]);
    }

    private function makeMessage(
        TelegramChat $chat,
        TelegramUser $sender,
        int $messageId,
        ?int $replyTo = null,
        bool $fromModerator = false,
    ): TelegramMessage {
        $updateId = DB::table('telegram_updates')->insertGetId([
            'bot_id' => random_int(10_000_000, 2_000_000_000),
            'update_id' => random_int(10_000_000, 2_000_000_000),
            'update_type' => 'message',
            'chat_id' => $chat->chat_id,
            'payload' => json_encode(['message' => []]),
            'received_at' => now(),
        ]);

        return TelegramMessage::forceCreate([
            'telegram_chat_id' => $chat->id,
            'message_id' => $messageId,
            'telegram_user_id' => $sender->id,
            'sent_at' => now()->subMinutes(30 - $messageId),
            'reply_to_message_id' => $replyTo,
            'is_service' => false,
            'is_from_moderator' => $fromModerator,
            'original_text' => 'نص',
            'normalized_text' => 'نص',
            'entity_flags' => '{}',
            'source_update_id' => $updateId,
        ]);
    }

    private function makeItem(TelegramChat $chat, TelegramMessage $anchor): AttentionItem
    {
        return AttentionItem::forceCreate([
            'telegram_chat_id' => $chat->id,
            'telegram_message_id' => $anchor->message_id,
            'opened_at' => $anchor->sent_at,
            'source' => 'rule',
            'rule_version' => 1,
            'status' => 'open',
        ]);
    }

    public function test_answered_by_a_member_records_its_reason_account_and_moment(): void
    {
        $user = $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $item = $this->makeItem($chat, $this->makeMessage($chat, $this->makePerson(), 1));

        Livewire::test(LiveAttentionQueue::class)
            ->callTableAction('dismiss_member_answered', $item)
            ->assertCanNotSeeTableRecords([$item->fresh()]);

        $item->refresh();
        $this->assertSame('dismissed', $item->status);
        $this->assertSame('member_answered', $item->close_reason);
        $this->assertSame($user->id, $item->closed_by_user_id);
        $this->assertNotNull($item->closed_at);
    }

    public function test_every_dismissal_confirmation_states_the_four_meanings(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $item = $this->makeItem($chat, $this->makeMessage($chat, $this->makePerson(), 1));

        foreach (['dismiss_not_a_question', 'dismiss_member_discussion', 'dismiss_member_answered', 'dismiss_message_removed'] as $action) {
            Livewire::test(LiveAttentionQueue::class)
                ->mountTableAction($action, $item)
                ->assertMountedActionModalSee([
                    'Not a real question: not a question or request at all; nothing to answer.',
                    'Member discussion: a real question or discussion between members; no moderator was needed.',
                    'Answered by a member: a real question another member answered well enough; no moderator answer was needed.',
                    'Message removed: your own judgement that the message is gone. Telegram reports no deletion.',
                ]);
        }

        $this->assertSame('open', $item->fresh()->status);
    }

    public function test_the_row_actions_are_one_dropdown_and_there_is_no_bulk_action(): void
    {
        $this->actingAsPanelOperator();

        $table = Livewire::test(LiveAttentionQueue::class)->instance()->getTable();
        $recordActions = array_values($table->getRecordActions());

        $this->assertCount(1, $recordActions);
        $this->assertInstanceOf(ActionGroup::class, $recordActions[0]);
        $this->assertSame(
            ['dismiss_not_a_question', 'dismiss_member_discussion', 'dismiss_member_answered', 'dismiss_message_removed', 'open_incident'],
            array_map(fn ($action): string => $action->getName(), array_values($recordActions[0]->getActions())),
        );
        $this->assertSame([], $table->getToolbarActions());
    }

    public function test_the_replies_column_counts_other_members_and_says_when_the_asker_replied_back(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $asker = $this->makePerson();
        $member = $this->makePerson();
        $moderator = $this->makePerson();

        $question = $this->makeMessage($chat, $asker, 1);
        $item = $this->makeItem($chat, $question);
        $this->makeMessage($chat, $member, 2, replyTo: 1);
        $this->makeMessage($chat, $moderator, 3, replyTo: 1, fromModerator: true);
        $this->makeMessage($chat, $asker, 4, replyTo: 1);
        $this->makeMessage($chat, $asker, 5, replyTo: 2);

        $quiet = $this->makeItem($chat, $this->makeMessage($chat, $this->makePerson(), 10));

        Livewire::test(LiveAttentionQueue::class)
            ->assertTableColumnStateSet('replies', 'Member replies: 1 · the asker replied back', $item)
            ->assertTableColumnStateSet('replies', '—', $quiet)
            ->assertCanSeeTableRecords([$item, $quiet]);

        $this->assertSame('open', $item->fresh()->status);
    }

    public function test_classification_accuracy_counts_answered_by_a_member_in_its_own_part(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $item = $this->makeItem($chat, $this->makeMessage($chat, $this->makePerson(), 1));
        $item->closeIfOpen('dismissed', [
            'close_reason' => 'member_answered',
            'closed_at' => now(),
            'closed_by_user_id' => auth()->id(),
        ]);

        $html = Livewire::test(ClassificationAccuracy::class)
            ->set('chatId', (string) $chat->id)
            ->html();

        $this->assertStringContainsString('answered by a member 1', $html);
    }
}
