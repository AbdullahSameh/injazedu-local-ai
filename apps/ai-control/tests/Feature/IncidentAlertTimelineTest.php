<?php

namespace Tests\Feature;

use App\Filament\Resources\Incidents\Pages\ViewIncident;
use App\Filament\Resources\Incidents\Support\IncidentDisplay;
use App\Filament\Support\TeamAssignment;
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
 * T532 (TG-M6, US2; `alerting.md` S4, S5): an incident resolved or closed from the alert group.
 * The timeline reads `alert_handled` as "Resolved (alert)" and `alert_false_positive` as "Not a
 * violation (alert)", each with its moderator; a false-positive closure from the alert names its
 * moderator although no panel account closed it; both kinds read "via alert" as an assignment.
 * The alert acts are seeded directly, as the Python pipeline writes them.
 *
 * T541/T543 (US4, S4): the incident page's "Alerts" section lists the incident's alerts with
 * their status and presses, and is absent when none fired.
 */
class IncidentAlertTimelineTest extends TestCase
{
    use DatabaseTransactions;

    private TelegramChat $chat;

    private ModerationIncident $incident;

    private Moderator $moderator;

    protected function setUp(): void
    {
        parent::setUp();
        $this->actingAs(User::factory()->create(['is_panel_operator' => true]));

        $this->chat = TelegramChat::forceCreate([
            'chat_id' => -random_int(10_000_000, 2_000_000_000),
            'chat_type' => 'supergroup',
            'title' => 'Alert Timeline Group',
            'is_monitored' => true,
            'bot_status' => 'administrator',
        ]);
        $message = TelegramMessage::forceCreate([
            'telegram_chat_id' => $this->chat->id,
            'message_id' => random_int(1, 2_000_000_000),
            'telegram_user_id' => TelegramUser::forceCreate([
                'tg_user_id' => random_int(10_000_000, 2_000_000_000),
                'is_bot' => false,
            ])->id,
            'sent_at' => now()->subHours(2),
            'is_service' => false,
            'is_from_moderator' => false,
            'original_text' => 'spam text',
            'normalized_text' => 'spam text',
            'entity_flags' => [],
            'source_update_id' => $this->captured('message'),
        ]);
        $this->incident = ModerationIncident::forceCreate([
            'telegram_chat_id' => $this->chat->id,
            'telegram_message_id' => $message->message_id,
            'opened_at' => $message->sent_at,
            'detected_at' => now()->subHour(),
            'source' => 'operator',
            'opened_by_user_id' => 1,
            'category' => 'SPAM_OR_AD',
            'severity' => 'medium',
        ]);
        $identity = TelegramUser::forceCreate([
            'tg_user_id' => random_int(10_000_000, 2_000_000_000),
            'is_bot' => false,
        ]);
        $this->moderator = Moderator::create([
            'telegram_user_id' => $identity->id,
            'display_name' => 'Alert Mod',
        ]);
        DB::table('moderators')->where('id', $this->moderator->id)
            ->update(['created_at' => now()->subDays(30)]);
        ModeratorGroupAssignment::create([
            'telegram_chat_id' => $this->chat->id,
            'moderator_id' => $this->moderator->id,
            'assignment_role' => 'primary',
            'valid_from' => now()->subDays(30)->format('Y-m-d H:i:s.u'),
        ]);
    }

    private function captured(string $type): int
    {
        return DB::table('telegram_updates')->insertGetId([
            'bot_id' => random_int(10_000_000, 2_000_000_000),
            'update_id' => random_int(10_000_000, 2_000_000_000),
            'update_type' => $type,
            'chat_id' => $type === 'callback_query' ? null : $this->chat->chat_id,
            'payload' => json_encode([$type => []]),
            'received_at' => now(),
        ]);
    }

    private function alertAct(string $kind): void
    {
        $ruleId = DB::table('alert_rules')->insertGetId([
            'trigger' => 'incident_flagged',
            'telegram_chat_id' => $this->chat->id,
            'is_enabled' => false,
        ]);
        $alertId = DB::table('alerts')->insertGetId([
            'alert_rule_id' => $ruleId,
            'trigger' => 'incident_flagged',
            'telegram_chat_id' => $this->chat->id,
            'subject_type' => 'incident',
            'subject_id' => $this->incident->id,
            'repeat_index' => 0,
            'dedupe_key' => $ruleId.':incident:'.$this->incident->id.':0',
            'rule_values' => json_encode([]),
            'qualified_at' => now()->subHour(),
            'delivery_status' => 'sent',
            'sent_chat_id' => -random_int(10_000_000, 2_000_000_000),
            'sent_message_id' => random_int(1, 2_000_000_000),
        ]);
        DB::table('moderation_actions')->insert([
            'telegram_chat_id' => $this->chat->id,
            'action_type' => $kind,
            'action_strength' => $kind === 'alert_handled' ? 'confirmation' : null,
            'occurred_at' => now()->subMinutes(30),
            'actor_telegram_user_id' => $this->moderator->telegram_user_id,
            'actor_moderator_id' => $this->moderator->id,
            'moderation_incident_id' => $this->incident->id,
            'alert_id' => $alertId,
            'source_update_id' => $this->captured('callback_query'),
            'detail' => json_encode([]),
        ]);
    }

    public function test_handled_from_the_alert_reads_resolved_alert_with_its_moderator(): void
    {
        $this->alertAct('alert_handled');

        $state = $this->incident->state();
        $this->assertSame('resolved', $state->status);
        $this->assertSame('alert_handled', $state->resolution_kind);

        Livewire::test(ViewIncident::class, ['record' => $this->incident->getKey()])
            ->assertSeeText(__('Resolved (alert)'))
            ->assertSeeText('Alert Mod · '.__('Resolved (alert)'));
    }

    public function test_not_a_violation_from_the_alert_names_its_moderator(): void
    {
        $this->alertAct('alert_false_positive');

        $state = $this->incident->state();
        $this->assertSame('closed_false_positive', $state->status);
        $this->assertNull($state->closed_by_user_id);

        Livewire::test(ViewIncident::class, ['record' => $this->incident->getKey()])
            ->assertSeeText(__('Not a violation (alert)'))
            ->assertSeeText(__(':moment, by :user — :reason', [
                'moment' => $this->localMoment($state->closed_at),
                'user' => 'Alert Mod',
                'reason' => __('Not a violation (alert)'),
            ]))
            ->assertDontSeeText(__('a panel account'));
    }

    public function test_the_alerts_section_lists_each_alert_with_its_status_and_presses(): void
    {
        $this->alertAct('alert_handled');
        $ruleId = (int) DB::table('alerts')->where('subject_id', $this->incident->id)->value('alert_rule_id');
        DB::table('alerts')->insert([
            'alert_rule_id' => $ruleId,
            'trigger' => 'incident_flagged',
            'telegram_chat_id' => $this->chat->id,
            'subject_type' => 'incident',
            'subject_id' => $this->incident->id,
            'repeat_index' => 1,
            'dedupe_key' => $ruleId.':incident:'.$this->incident->id.':1',
            'rule_values' => json_encode(['max_repeats' => 2]),
            'qualified_at' => now()->subHour(),
            'delivery_status' => 'not_sent',
            'not_sent_reason' => 'subject_ended',
        ]);

        Livewire::test(ViewIncident::class, ['record' => $this->incident->getKey()])
            ->assertSeeText(__('Alerts'))
            ->assertSeeText(__('Presses'))
            ->assertSeeText(__('Incident flagged'))
            ->assertSeeText(__('Sent'))
            ->assertSeeText(__('Not sent').' · '.__('Ended before sending'))
            ->assertSeeText(__(':k of :n', ['k' => 1, 'n' => 2]));
    }

    public function test_an_incident_with_no_alert_shows_no_alerts_section(): void
    {
        Livewire::test(ViewIncident::class, ['record' => $this->incident->getKey()])
            ->assertDontSeeText(__('Presses'));
    }

    public function test_both_alert_kinds_have_fixed_labels_and_read_via_alert(): void
    {
        $this->assertSame(__('Resolved (alert)'), IncidentDisplay::kindLabel('alert_handled', 'confirmation'));
        $this->assertSame(__('Not a violation (alert)'), IncidentDisplay::kindLabel('alert_false_positive'));
        foreach (['alert', 'alert_handled', 'alert_false_positive'] as $via) {
            $this->assertSame(__('via alert'), TeamAssignment::viaLabel($via));
        }
    }

    public function test_the_arabic_labels_carry_no_deletion_word(): void
    {
        app()->setLocale('ar');

        foreach (['Resolved (alert)', 'Not a violation (alert)'] as $key) {
            $arabic = __($key);
            $this->assertNotSame($key, $arabic);
            foreach (['حذف', 'حُذفت', 'أزال', 'إزالة'] as $word) {
                $this->assertStringNotContainsString($word, $arabic);
            }
        }
    }

    private function localMoment(string $instant): string
    {
        return \Illuminate\Support\Carbon::parse($instant)->setTimezone('Asia/Riyadh')->format('Y-m-d H:i');
    }
}
