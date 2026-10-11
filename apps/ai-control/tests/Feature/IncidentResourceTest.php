<?php

namespace Tests\Feature;

use App\Filament\Resources\Incidents\Pages\ListIncidents;
use App\Filament\Resources\Incidents\Pages\ViewIncident;
use App\Models\ModerationIncident;
use App\Models\Moderator;
use App\Models\TelegramChat;
use App\Models\TelegramMessage;
use App\Models\TelegramUser;
use App\Models\User;
use Illuminate\Foundation\Testing\DatabaseTransactions;
use Illuminate\Support\Facades\DB;
use Livewire\Livewire;
use Tests\TestCase;

/**
 * T052 (US5): the list's filters (status, category, severity, group, responsible moderator,
 * detection date) narrow correctly; the **Unassigned** badge; the Age/took column; the view
 * page's six sections; the evidence trail's order, fixed kind labels and captured-event ids; a
 * missing timing reading "no evidence"; a purged anchor showing "Text removed" with everything
 * else intact; the bot-not-administrator and channel-sender notices' conditions; the model note;
 * and `dir="auto"` on Arabic fields (`control-panel-incidents.md` §1, FR-067...FR-077, SC-017).
 */
class IncidentResourceTest extends TestCase
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
            'title' => 'Incident Group',
            'is_monitored' => true,
            'bot_status' => 'administrator',
        ], $overrides));
    }

    private function makeCapturedUpdate(TelegramChat $chat, string $updateType = 'message'): int
    {
        return DB::table('telegram_updates')->insertGetId([
            'bot_id' => random_int(10_000_000, 2_000_000_000),
            'update_id' => random_int(10_000_000, 2_000_000_000),
            'update_type' => $updateType,
            'chat_id' => $chat->chat_id,
            'payload' => json_encode(['message' => []]),
            'received_at' => now(),
        ]);
    }

    private function makeMessage(TelegramChat $chat, int $messageId, array $overrides = []): TelegramMessage
    {
        $senderId = $overrides['telegram_user_id']
            ?? (array_key_exists('sender_chat_id', $overrides)
                ? null
                : TelegramUser::forceCreate([
                    'tg_user_id' => random_int(10_000_000, 2_000_000_000),
                    'is_bot' => false,
                ])->id);

        return TelegramMessage::forceCreate(array_merge([
            'telegram_chat_id' => $chat->id,
            'message_id' => $messageId,
            'telegram_user_id' => $senderId,
            'sent_at' => now()->subHours(2),
            'is_service' => false,
            'is_from_moderator' => false,
            'original_text' => 'spam text',
            'normalized_text' => 'spam text',
            'entity_flags' => [],
            'source_update_id' => $this->makeCapturedUpdate($chat),
        ], $overrides));
    }

    private function makeIncident(TelegramChat $chat, TelegramMessage $message, array $overrides = []): ModerationIncident
    {
        return ModerationIncident::forceCreate(array_merge([
            'telegram_chat_id' => $chat->id,
            'telegram_message_id' => $message->message_id,
            'opened_at' => $message->sent_at,
            'detected_at' => now()->subHour(),
            'source' => 'operator',
            'opened_by_user_id' => 1,
            'category' => 'SPAM_OR_AD',
            'severity' => 'low',
        ], $overrides));
    }

    private function makeModerator(string $displayName = 'Owner'): Moderator
    {
        $identity = TelegramUser::forceCreate([
            'tg_user_id' => random_int(10_000_000, 2_000_000_000),
            'is_bot' => false,
        ]);

        return Moderator::create([
            'telegram_user_id' => $identity->id,
            'display_name' => $displayName,
        ]);
    }

    private function insertAction(array $overrides): void
    {
        DB::table('moderation_actions')->insert(array_merge([
            'detail' => json_encode([]),
        ], $overrides));
    }

    public function test_the_list_filters_narrow_correctly(): void
    {
        $this->actingAsPanelOperator();
        $chatA = $this->makeChat(['title' => 'Group A']);
        $chatB = $this->makeChat(['title' => 'Group B']);
        $moderator = $this->makeModerator('Filter Moderator');

        $matching = $this->makeIncident($chatA, $this->makeMessage($chatA, 1), [
            'category' => 'ABUSE',
            'severity' => 'high',
            'responsible_moderator_id' => $moderator->id,
            'detected_at' => now()->subDays(2),
        ]);
        $otherCategory = $this->makeIncident($chatA, $this->makeMessage($chatA, 2), [
            'category' => 'OTHER',
            'severity' => 'high',
            'responsible_moderator_id' => $moderator->id,
            'detected_at' => now()->subDays(2),
        ]);
        $otherGroup = $this->makeIncident($chatB, $this->makeMessage($chatB, 1), [
            'category' => 'ABUSE',
            'severity' => 'high',
            'responsible_moderator_id' => $moderator->id,
            'detected_at' => now()->subDays(2),
        ]);
        $otherModerator = $this->makeIncident($chatA, $this->makeMessage($chatA, 3), [
            'category' => 'ABUSE',
            'severity' => 'high',
            'detected_at' => now()->subDays(2),
        ]);
        $outsideDateRange = $this->makeIncident($chatA, $this->makeMessage($chatA, 4), [
            'category' => 'ABUSE',
            'severity' => 'high',
            'responsible_moderator_id' => $moderator->id,
            'detected_at' => now()->subDays(20),
        ]);

        Livewire::test(ListIncidents::class)
            ->filterTable('category', 'ABUSE')
            ->filterTable('severity', 'high')
            ->filterTable('telegram_chat_id', $chatA->id)
            ->filterTable('responsible_moderator_id', $moderator->id)
            ->filterTable('detected_at', [
                'from' => now()->subDays(5)->toDateString(),
                'until' => now()->toDateString(),
            ])
            ->assertCanSeeTableRecords([$matching])
            ->assertCanNotSeeTableRecords([$otherCategory, $otherGroup, $otherModerator, $outsideDateRange]);
    }

    public function test_the_status_filter_narrows_by_the_derived_state(): void
    {
        $operator = $this->actingAsPanelOperator();
        $chat = $this->makeChat();

        $open = $this->makeIncident($chat, $this->makeMessage($chat, 1));
        $resolved = $this->makeIncident($chat, $this->makeMessage($chat, 2));
        $resolved->resolve($operator, 'Confirmed.');

        Livewire::test(ListIncidents::class)
            ->filterTable('status', 'open')
            ->assertCanSeeTableRecords([$open])
            ->assertCanNotSeeTableRecords([$resolved]);
    }

    public function test_unassigned_badge_when_no_responsible_moderator(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $incident = $this->makeIncident($chat, $this->makeMessage($chat, 1), [
            'responsible_moderator_id' => null,
        ]);

        Livewire::test(ListIncidents::class)
            ->assertCanSeeTableRecords([$incident])
            ->assertSeeText('Unassigned');
    }

    public function test_age_shows_a_human_duration_while_open(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $incident = $this->makeIncident($chat, $this->makeMessage($chat, 1), [
            'detected_at' => now()->subHours(3),
        ]);

        Livewire::test(ListIncidents::class)
            ->assertCanSeeTableRecords([$incident])
            ->assertSeeText('3h');
    }

    public function test_age_took_reads_acted_before_flagging_for_a_pre_flag_resolution(): void
    {
        $operator = $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $message = $this->makeMessage($chat, 1, ['sent_at' => now()->subHours(3)]);
        $incident = $this->makeIncident($chat, $message, ['detected_at' => now()->subHour()]);

        // A ban dated after posting but before flagging (the first clarification).
        $this->insertAction([
            'telegram_chat_id' => $chat->id,
            'action_type' => 'ban',
            'action_strength' => 'enforcement',
            'occurred_at' => now()->subHours(2),
            'subject_telegram_user_id' => $message->telegram_user_id,
            'source_update_id' => $this->makeCapturedUpdate($chat, 'chat_member'),
        ]);

        Livewire::test(ListIncidents::class)
            ->assertCanSeeTableRecords([$incident])
            ->assertSeeText('acted before flagging');
    }

    public function test_the_view_page_has_all_six_sections(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $incident = $this->makeIncident($chat, $this->makeMessage($chat, 1));

        Livewire::test(ViewIncident::class, ['record' => $incident->getKey()])
            ->assertSeeText('What was posted')
            ->assertSeeText('When')
            ->assertSeeText('Why flagged')
            ->assertSeeText('Who handled it')
            ->assertSeeText('How long')
            ->assertSeeText('Corrected?');
    }

    public function test_the_evidence_trail_lists_every_row_with_fixed_labels_and_captured_ids(): void
    {
        $operator = $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $message = $this->makeMessage($chat, 1, ['sent_at' => now()->subHours(3)]);
        $incident = $this->makeIncident($chat, $message, ['detected_at' => now()->subHours(2)]);
        $moderator = $this->makeModerator('Reacting Mod');

        $reactionUpdateId = $this->makeCapturedUpdate($chat, 'message_reaction');
        $this->insertAction([
            'telegram_chat_id' => $chat->id,
            'action_type' => 'reaction',
            'action_strength' => 'acknowledgement',
            'occurred_at' => now()->subHour(),
            'actor_telegram_user_id' => $moderator->telegram_user_id,
            'actor_moderator_id' => $moderator->id,
            'target_message_id' => $message->message_id,
            'source_update_id' => $reactionUpdateId,
        ]);

        $banUpdateId = $this->makeCapturedUpdate($chat, 'chat_member');
        $this->insertAction([
            'telegram_chat_id' => $chat->id,
            'action_type' => 'ban',
            'action_strength' => 'enforcement',
            'occurred_at' => now()->subMinutes(30),
            'subject_telegram_user_id' => $message->telegram_user_id,
            'source_update_id' => $banUpdateId,
        ]);

        $test = Livewire::test(ViewIncident::class, ['record' => $incident->getKey()])
            ->assertSeeText('Reaction')
            ->assertSeeText('Banned')
            ->assertSeeText('Reacting Mod')
            ->assertSeeText("captured event #{$reactionUpdateId}")
            ->assertSeeText("captured event #{$banUpdateId}");

        $test->assertDontSeeText('Expelled');
    }

    public function test_a_missing_timing_reads_no_evidence_never_zero(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $incident = $this->makeIncident($chat, $this->makeMessage($chat, 1));

        Livewire::test(ViewIncident::class, ['record' => $incident->getKey()])
            ->assertSeeText('no evidence')
            ->assertDontSeeText('0 seconds');
    }

    public function test_a_purged_anchor_shows_text_removed_with_everything_else_intact(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $message = $this->makeMessage($chat, 1, [
            'original_text' => null,
            'text_purged_at' => now(),
        ]);
        $incident = $this->makeIncident($chat, $message);

        Livewire::test(ViewIncident::class, ['record' => $incident->getKey()])
            ->assertSeeText('Text removed')
            ->assertSeeText('When')
            ->assertSeeText('Who handled it');
    }

    public function test_the_bot_not_administrator_notice_appears_only_when_not_administrator(): void
    {
        $this->actingAsPanelOperator();

        $notAdmin = $this->makeChat(['bot_status' => 'member']);
        $incidentA = $this->makeIncident($notAdmin, $this->makeMessage($notAdmin, 1));
        Livewire::test(ViewIncident::class, ['record' => $incidentA->getKey()])
            ->assertSeeText('The bot is not currently an administrator');

        $admin = $this->makeChat(['bot_status' => 'administrator']);
        $incidentB = $this->makeIncident($admin, $this->makeMessage($admin, 1));
        Livewire::test(ViewIncident::class, ['record' => $incidentB->getKey()])
            ->assertDontSeeText('The bot is not currently an administrator');
    }

    public function test_the_channel_sender_notice_appears_only_for_a_channel_sent_anchor(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();

        $channelSent = $this->makeMessage($chat, 1, [
            'sender_chat_id' => -random_int(10_000_000, 2_000_000_000),
            'telegram_user_id' => null,
        ]);
        $incidentA = $this->makeIncident($chat, $channelSent);
        Livewire::test(ViewIncident::class, ['record' => $incidentA->getKey()])
            ->assertSeeText('sent on behalf of a channel');

        $ordinary = $this->makeMessage($chat, 2);
        $incidentB = $this->makeIncident($chat, $ordinary);
        Livewire::test(ViewIncident::class, ['record' => $incidentB->getKey()])
            ->assertDontSeeText('sent on behalf of a channel');
    }

    /**
     * TG-M5 D1: the placeholder line is gone — replaced by the model's view of the anchor
     * message (`ModelViewDisplayTest` covers the full "why flagged" behaviour).
     */
    public function test_the_model_classification_note_is_replaced_by_the_models_view(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $incident = $this->makeIncident($chat, $this->makeMessage($chat, 1));

        Livewire::test(ViewIncident::class, ['record' => $incident->getKey()])
            ->assertSeeText('operator-assigned')
            ->assertDontSeeText('No model classification — arrives with TG-M5');
    }

    public function test_arabic_fields_carry_dir_auto(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat(['title' => 'مجموعة اختبار']);
        $message = $this->makeMessage($chat, 1, ['original_text' => 'رسالة عربية']);
        $incident = $this->makeIncident($chat, $message);

        Livewire::test(ListIncidents::class)
            ->assertSee('dir="auto"', false);

        Livewire::test(ViewIncident::class, ['record' => $incident->getKey()])
            ->assertSee('dir="auto"', false);
    }
}
