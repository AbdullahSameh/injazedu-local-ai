<?php

namespace Tests\Feature;

use App\Filament\Pages\LiveAttentionQueue;
use App\Filament\Resources\Incidents\Pages\ListIncidents;
use App\Filament\Resources\Incidents\Pages\ViewIncident;
use App\Filament\Support\TeamAssignment;
use App\Models\AttentionItem;
use App\Models\ModerationIncident;
use App\Models\Moderator;
use App\Models\ModeratorGroupAssignment;
use App\Models\TelegramChat;
use App\Models\TelegramMessage;
use App\Models\TelegramUser;
use App\Models\User;
use Illuminate\Foundation\Testing\DatabaseTransactions;
use Illuminate\Support\Facades\DB;
use Livewire\Livewire;
use Tests\TestCase;

/**
 * TG-M2.1's screens (`specs/012-tg-m2-1-group-teams/contracts/group-teams.md` C1, S1-S2, F1-F3):
 * the Assigned column reads the assignee views, "Mine" is on by default for a moderator's own
 * account, and a panel act by a linked account is credited to its moderator. The figures are read
 * through the pages' own methods, which quote the Python SQL.
 */
class TeamAssignmentPanelTest extends TestCase
{
    use DatabaseTransactions;

    private function makeChat(string $title = 'Team Group'): TelegramChat
    {
        return TelegramChat::forceCreate([
            'chat_id' => -random_int(10_000_000, 2_000_000_000),
            'chat_type' => 'group',
            'title' => $title,
            'is_monitored' => true,
            'bot_status' => 'administrator',
        ]);
    }

    private function makeIdentity(): TelegramUser
    {
        return TelegramUser::forceCreate([
            'tg_user_id' => random_int(10_000_000, 2_000_000_000),
            'is_bot' => false,
        ]);
    }

    /**
     * A moderator on `$chats`' teams since a day ago, created a week ago so the membership's start
     * follows the declaration (T4) — written directly, as a fixture, not through `addMember`.
     */
    private function makeMember(string $name, TelegramChat ...$chats): Moderator
    {
        $moderator = Moderator::create([
            'telegram_user_id' => $this->makeIdentity()->id,
            'display_name' => $name,
        ]);
        foreach ($chats as $chat) {
            ModeratorGroupAssignment::create([
                'telegram_chat_id' => $chat->id,
                'moderator_id' => $moderator->id,
                'assignment_role' => 'primary',
                'valid_from' => now()->subDay()->format('Y-m-d H:i:s.u'),
            ]);
        }

        return $moderator;
    }

    private function signInAs(?Moderator $moderator): User
    {
        $user = User::factory()->create(['is_panel_operator' => true]);
        $moderator?->forceFill(['user_id' => $user->id])->save();
        $this->actingAs($user->fresh());

        return $user;
    }

    private function makeUpdate(TelegramChat $chat, string $type = 'message'): int
    {
        return DB::table('telegram_updates')->insertGetId([
            'bot_id' => random_int(10_000_000, 2_000_000_000),
            'update_id' => random_int(10_000_000, 2_000_000_000),
            'update_type' => $type,
            'chat_id' => $chat->chat_id,
            'payload' => json_encode([$type => []]),
            'received_at' => now(),
        ]);
    }

    private function makeMessage(TelegramChat $chat, int $messageId, \DateTimeInterface $sentAt): TelegramMessage
    {
        return TelegramMessage::forceCreate([
            'telegram_chat_id' => $chat->id,
            'message_id' => $messageId,
            'telegram_user_id' => $this->makeIdentity()->id,
            'sent_at' => $sentAt,
            'is_service' => false,
            'is_from_moderator' => false,
            'original_text' => 'متى الاختبار؟',
            'normalized_text' => 'متى الاختبار؟',
            'entity_flags' => [],
            'source_update_id' => $this->makeUpdate($chat),
        ]);
    }

    private function makeItem(TelegramChat $chat, int $messageId, array $overrides = []): AttentionItem
    {
        $message = $this->makeMessage($chat, $messageId, now()->subMinutes(10));

        return AttentionItem::forceCreate(array_merge([
            'telegram_chat_id' => $chat->id,
            'telegram_message_id' => $message->message_id,
            'opened_at' => $message->sent_at,
            'source' => 'rule',
            'rule_version' => 1,
            'status' => 'open',
        ], $overrides));
    }

    private function react(Moderator $moderator, TelegramChat $chat, int $targetMessageId): void
    {
        DB::table('moderation_actions')->insert([
            'telegram_chat_id' => $chat->id,
            'action_type' => 'reaction',
            'action_strength' => 'acknowledgement',
            'occurred_at' => now()->subMinutes(5),
            'actor_telegram_user_id' => $moderator->telegram_user_id,
            'actor_moderator_id' => $moderator->id,
            'target_message_id' => $targetMessageId,
            'source_update_id' => $this->makeUpdate($chat, 'message_reaction'),
            'detail' => json_encode([]),
        ]);
    }

    public function test_a_reaction_by_a_team_member_shows_them_as_assigned(): void
    {
        $this->signInAs(null);
        $chat = $this->makeChat();
        $this->makeMember('Ahmed', $chat);
        $zainab = $this->makeMember('Zainab', $chat);
        $item = $this->makeItem($chat, 1);
        $this->react($zainab, $chat, 1);

        Livewire::test(LiveAttentionQueue::class)
            ->assertTableColumnStateSet('assigned', 'Zainab · '.__('via reaction'), $item);
    }

    public function test_mine_is_on_by_default_for_a_linked_moderator_and_off_for_the_operator(): void
    {
        $mine = $this->makeChat('Mine');
        $theirs = $this->makeChat('Theirs');
        $ahmed = $this->makeMember('Ahmed', $mine);
        $this->makeMember('Zainab', $theirs);
        $myItem = $this->makeItem($mine, 1);
        $theirItem = $this->makeItem($theirs, 1);

        $this->signInAs($ahmed);
        Livewire::test(LiveAttentionQueue::class)
            ->assertCanSeeTableRecords([$myItem])
            ->assertCanNotSeeTableRecords([$theirItem])
            ->filterTable('mine', false)
            ->assertCanSeeTableRecords([$myItem, $theirItem]);

        $this->signInAs(null);
        Livewire::test(LiveAttentionQueue::class)
            ->assertCanSeeTableRecords([$myItem, $theirItem]);
    }

    public function test_mine_keeps_an_item_a_colleague_took_out_of_my_view(): void
    {
        $chat = $this->makeChat();
        $ahmed = $this->makeMember('Ahmed', $chat);
        $zainab = $this->makeMember('Zainab', $chat);
        $takenByZainab = $this->makeItem($chat, 1);
        $stillOpen = $this->makeItem($chat, 2);
        $this->react($zainab, $chat, 1);

        $this->signInAs($ahmed);
        Livewire::test(LiveAttentionQueue::class)
            ->assertCanSeeTableRecords([$stillOpen])
            ->assertCanNotSeeTableRecords([$takenByZainab]);
    }

    public function test_a_linked_dismissal_records_its_moderator_and_assigns_the_item(): void
    {
        $chat = $this->makeChat();
        $ahmed = $this->makeMember('Ahmed', $chat);
        $item = $this->makeItem($chat, 1);
        $this->signInAs($ahmed);

        Livewire::test(LiveAttentionQueue::class)
            ->callTableAction('dismiss_member_discussion', $item);

        $item->refresh();
        $this->assertSame('dismissed', $item->status);
        $this->assertSame($ahmed->id, (int) $item->closed_by_moderator_id);
        $assignee = DB::table('attention_item_assignee')->where('attention_item_id', $item->id)->first();
        $this->assertSame($ahmed->id, (int) $assignee->assigned_moderator_id);
        $this->assertSame('dismissal', $assignee->assigned_via);
    }

    public function test_an_unlinked_operators_dismissal_assigns_nobody(): void
    {
        $chat = $this->makeChat();
        $this->makeMember('Ahmed', $chat);
        $item = $this->makeItem($chat, 1);
        $this->signInAs(null);

        Livewire::test(LiveAttentionQueue::class)
            ->callTableAction('dismiss_not_a_question', $item);

        $this->assertNull($item->refresh()->closed_by_moderator_id);
        $this->assertNull(
            DB::table('attention_item_assignee')->where('attention_item_id', $item->id)->value('assigned_moderator_id')
        );
    }

    public function test_a_linked_acknowledgement_is_credited_and_assigns_the_incident(): void
    {
        $chat = $this->makeChat();
        $ahmed = $this->makeMember('Ahmed', $chat);
        $message = $this->makeMessage($chat, 1, now()->subHours(2));
        $incident = ModerationIncident::forceCreate([
            'telegram_chat_id' => $chat->id,
            'telegram_message_id' => $message->message_id,
            'opened_at' => $message->sent_at,
            'detected_at' => now()->subHour(),
            'source' => 'operator',
            'opened_by_user_id' => 1,
            'category' => 'SPAM_OR_AD',
            'severity' => 'low',
        ]);
        $user = $this->signInAs($ahmed);

        $this->assertTrue($incident->acknowledge($user->fresh()));

        $this->assertSame($ahmed->id, (int) DB::table('moderation_actions')
            ->where('moderation_incident_id', $incident->id)
            ->value('actor_moderator_id'));
        Livewire::test(ListIncidents::class)
            ->assertCanSeeTableRecords([$incident])
            ->assertTableColumnStateSet('assigned', 'Ahmed · '.__('via panel acknowledge'), $incident);
    }

    private function makeIncident(TelegramChat $chat, int $messageId): ModerationIncident
    {
        $message = $this->makeMessage($chat, $messageId, now()->subHours(2));

        return ModerationIncident::forceCreate([
            'telegram_chat_id' => $chat->id,
            'telegram_message_id' => $message->message_id,
            'opened_at' => $message->sent_at,
            'detected_at' => now()->subHour(),
            'source' => 'operator',
            'opened_by_user_id' => 1,
            'category' => 'SPAM_OR_AD',
            'severity' => 'low',
        ]);
    }

    public function test_an_open_untaken_incident_names_its_team_and_a_closed_one_says_not_taken(): void
    {
        $chat = $this->makeChat();
        $this->makeMember('Ahmed', $chat);
        $open = $this->makeIncident($chat, 1);
        $resolved = $this->makeIncident($chat, 2);
        $user = $this->signInAs(null);
        // An unlinked operator resolves it: it closes, and nobody on the team took it.
        $this->assertTrue($resolved->resolve($user->fresh(), 'handled in the group'));

        Livewire::test(ListIncidents::class)
            ->assertTableColumnStateSet('assigned', __('Team: :names', ['names' => 'Ahmed']), $open)
            ->assertTableColumnStateSet('assigned', __('Not taken by the team'), $resolved);
        Livewire::test(ViewIncident::class, ['record' => $resolved->getKey()])
            ->assertSeeText(__('Not taken by the team'))
            ->assertDontSeeText(__('Not yet — the first team member to act takes it'));
        Livewire::test(ViewIncident::class, ['record' => $open->getKey()])
            ->assertSeeText(__('Not yet — the first team member to act takes it'));
    }

    public function test_a_closed_untaken_incident_says_not_taken_even_with_no_team(): void
    {
        $chat = $this->makeChat();
        $open = $this->makeIncident($chat, 1);
        $resolved = $this->makeIncident($chat, 2);
        $user = $this->signInAs(null);
        $this->assertTrue($resolved->resolve($user->fresh(), 'handled in the group'));

        Livewire::test(ListIncidents::class)
            ->assertTableColumnStateSet('assigned', __('No team'), $open)
            ->assertTableColumnStateSet('assigned', __('Not taken by the team'), $resolved);
    }

    public function test_the_label_says_not_taken_only_once_the_row_has_ended(): void
    {
        $this->assertSame(__('Team: :names', ['names' => 'Ahmed']), TeamAssignment::label(null, ['Ahmed']));
        $this->assertSame(__('No team'), TeamAssignment::label(null, []));
        $this->assertSame(__('Not taken by the team'), TeamAssignment::label(null, ['Ahmed'], false));
        $this->assertSame(__('Not taken by the team'), TeamAssignment::label(null, [], false));
        $this->assertSame('gray', TeamAssignment::color(null, [], false));
        $this->assertSame('danger', TeamAssignment::color(null, []));

        $taken = (object) ['assigned_moderator_id' => 7, 'display_name' => 'Zainab', 'assigned_via' => 'reply'];
        $this->assertSame('Zainab · '.__('via reply'), TeamAssignment::label($taken, [], false));
    }

    public function test_a_miss_counts_for_every_member_and_my_work_counts_what_i_took(): void
    {
        $this->signInAs(null);
        $chat = $this->makeChat();
        $ahmed = $this->makeMember('Ahmed', $chat);
        $zainab = $this->makeMember('Zainab', $chat);
        // Zainab takes the question with 👀 and nobody ever answers it.
        $this->makeItem($chat, 1, ['status' => 'expired', 'closed_at' => now()->subMinute()]);
        $this->react($zainab, $chat, 1);
        // The reaction landed before the expiry, so it assigns (G4).
        DB::table('moderation_actions')->where('target_message_id', 1)
            ->where('telegram_chat_id', $chat->id)
            ->update(['occurred_at' => now()->subMinutes(9)]);

        $rows = collect(Livewire::test(LiveAttentionQueue::class)->instance()->figuresByModerator())
            ->keyBy('label');

        $this->assertSame(1, $rows['Ahmed']['unanswered']);
        $this->assertSame(1, $rows['Zainab']['unanswered']);
        $this->assertSame(0, $rows['Ahmed']['work']['assigned']);
        $this->assertSame(1, $rows['Zainab']['work']['assigned']);
        $this->assertSame(1, $rows['Zainab']['work']['via_reaction']);
        $this->assertSame(1, $rows['Zainab']['work']['assigned_expired']);
    }
}
