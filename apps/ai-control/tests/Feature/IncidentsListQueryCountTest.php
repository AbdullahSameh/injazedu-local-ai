<?php

namespace Tests\Feature;

use App\Filament\Resources\Incidents\Pages\ListIncidents;
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
 * The Incidents list reads each row's status, assignee and team once per page, never once per row
 * (2026-11-11: on production a 10-row page made 146 queries, 70 of them the same state lookup at
 * ~25 ms each, because `moderation_incident_state` takes ~23 ms to plan). The rows still show what
 * the views say, and an act from the list shows its new status at once.
 */
class IncidentsListQueryCountTest extends TestCase
{
    use DatabaseTransactions;

    private function makeChat(): TelegramChat
    {
        return TelegramChat::forceCreate([
            'chat_id' => -random_int(10_000_000, 2_000_000_000),
            'chat_type' => 'group',
            'title' => 'Speed Group',
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

    private function makeMember(string $name, TelegramChat $chat): Moderator
    {
        $moderator = Moderator::create([
            'telegram_user_id' => $this->makeIdentity()->id,
            'display_name' => $name,
        ]);
        ModeratorGroupAssignment::create([
            'telegram_chat_id' => $chat->id,
            'moderator_id' => $moderator->id,
            'assignment_role' => 'primary',
            'valid_from' => now()->subDay()->format('Y-m-d H:i:s.u'),
        ]);

        return $moderator;
    }

    private function makeIncident(TelegramChat $chat, int $messageId): ModerationIncident
    {
        $updateId = DB::table('telegram_updates')->insertGetId([
            'bot_id' => random_int(10_000_000, 2_000_000_000),
            'update_id' => random_int(10_000_000, 2_000_000_000),
            'update_type' => 'message',
            'chat_id' => $chat->chat_id,
            'payload' => json_encode(['message' => []]),
            'received_at' => now(),
        ]);
        $message = TelegramMessage::forceCreate([
            'telegram_chat_id' => $chat->id,
            'message_id' => $messageId,
            'telegram_user_id' => $this->makeIdentity()->id,
            'sent_at' => now()->subHours(2),
            'is_service' => false,
            'is_from_moderator' => false,
            'original_text' => 'إعلان',
            'normalized_text' => 'إعلان',
            'entity_flags' => [],
            'source_update_id' => $updateId,
        ]);

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

    private function signInAs(?Moderator $moderator): User
    {
        $user = User::factory()->create(['is_panel_operator' => true]);
        $moderator?->forceFill(['user_id' => $user->id])->save();
        $this->actingAs($user->fresh());

        return $user->fresh();
    }

    public function test_a_page_reads_states_assignees_and_teams_once_not_per_row(): void
    {
        $chat = $this->makeChat();
        $ahmed = $this->makeMember('Ahmed', $chat);
        $incidents = collect(range(1, 6))->map(fn (int $id): ModerationIncident => $this->makeIncident($chat, $id));
        $user = $this->signInAs(null);
        $this->assertTrue($incidents[1]->resolve($user, 'handled in the group'));
        $ahmedsUser = User::factory()->create(['is_panel_operator' => true]);
        $ahmed->forceFill(['user_id' => $ahmedsUser->id])->save();
        $this->assertTrue($incidents[2]->acknowledge($ahmedsUser->fresh()));

        // The first render only: the assertions below may re-read rows on their own.
        DB::flushQueryLog();
        DB::enableQueryLog();
        $page = Livewire::test(ListIncidents::class);
        $queries = collect(DB::getQueryLog())->pluck('query');
        DB::disableQueryLog();

        foreach (['moderation_incident_state', 'moderation_incident_assignee', 'moderation_team_intervals'] as $view) {
            $reads = $queries->filter(fn (string $sql): bool => str_contains($sql, 'from "'.$view.'"'))->count();
            $this->assertLessThanOrEqual(1, $reads, "{$view} was read {$reads} times for one page of rows");
        }

        $page->assertCanSeeTableRecords($incidents->all())
            ->assertTableColumnStateSet('status', 'open', $incidents[0])
            ->assertTableColumnStateSet('status', 'resolved', $incidents[1])
            ->assertTableColumnStateSet('status', 'acknowledged', $incidents[2])
            ->assertTableColumnStateSet('assigned', __('Team: :names', ['names' => 'Ahmed']), $incidents[0])
            ->assertTableColumnStateSet('assigned', __('Not taken by the team'), $incidents[1])
            ->assertTableColumnStateSet('assigned', 'Ahmed · '.__('via panel acknowledge'), $incidents[2])
            ->assertTableActionVisible('acknowledge_incident', $incidents[0])
            ->assertTableActionHidden('acknowledge_incident', $incidents[1])
            ->assertTableActionHidden('resolve_incident', $incidents[1]);
    }

    public function test_an_act_from_the_list_shows_its_new_status_at_once(): void
    {
        $chat = $this->makeChat();
        $ahmed = $this->makeMember('Ahmed', $chat);
        $incident = $this->makeIncident($chat, 1);
        $this->signInAs($ahmed);

        Livewire::test(ListIncidents::class)
            ->assertTableColumnStateSet('status', 'open', $incident)
            ->assertTableColumnStateSet('assigned', __('Team: :names', ['names' => 'Ahmed']), $incident)
            ->callTableAction('acknowledge_incident', $incident)
            ->assertTableColumnStateSet('status', 'acknowledged', $incident)
            ->assertTableColumnStateSet('assigned', 'Ahmed · '.__('via panel acknowledge'), $incident)
            ->assertTableActionHidden('acknowledge_incident', $incident)
            ->assertTableActionVisible('resolve_incident', $incident);
    }
}
