<?php

namespace Tests\Feature;

use App\Filament\Pages\PossibleViolations;
use App\Filament\Resources\Incidents\Pages\ListIncidents;
use App\Filament\Resources\Incidents\Pages\ViewIncident;
use App\Models\MessageClassification;
use App\Models\ModelProfile;
use App\Models\ModerationIncident;
use App\Models\TelegramChat;
use App\Models\TelegramMessage;
use App\Models\TelegramUser;
use App\Models\User;
use Illuminate\Foundation\Testing\DatabaseTransactions;
use Illuminate\Support\Facades\DB;
use Livewire\Livewire;
use Tests\TestCase;

/**
 * The no-links rule and the advert guard on the panel
 * (`docs/plan/telegram/tg-day-one-investigation-and-link-rule-plan.md` Step 1): a rule-opened
 * incident reads "Link rule" wherever the opener is shown, the "Opened by" filter offers it, and
 * a prediction listed for having no outside-contact signal says so under "Why listed". Every label
 * is read from the stored `source` / `route_reason`, never computed.
 */
class IncidentLinkRuleTest extends TestCase
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
            'title' => 'Link Rule Group',
            'is_monitored' => true,
            'bot_status' => 'administrator',
        ]);
    }

    private function makeMessage(TelegramChat $chat, int $messageId, string $text): TelegramMessage
    {
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
            'telegram_user_id' => TelegramUser::forceCreate([
                'tg_user_id' => random_int(10_000_000, 2_000_000_000),
                'is_bot' => false,
            ])->id,
            'sent_at' => now()->subHours(2),
            'is_service' => false,
            'is_from_moderator' => false,
            'original_text' => $text,
            'normalized_text' => $text,
            'entity_flags' => ['has_url' => true, 'has_phone' => false, 'has_mention' => false, 'forwarded' => false],
            'source_update_id' => $updateId,
        ]);
    }

    private function makeIncident(TelegramChat $chat, TelegramMessage $message, string $source): ModerationIncident
    {
        return ModerationIncident::forceCreate([
            'telegram_chat_id' => $chat->id,
            'telegram_message_id' => $message->message_id,
            'opened_at' => $message->sent_at,
            'detected_at' => now()->subHour(),
            'source' => $source,
            'opened_by_user_id' => $source === 'operator' ? 1 : null,
            'rule_version' => $source === 'rule' ? 1 : null,
            'category' => 'OTHER',
            'severity' => 'low',
        ]);
    }

    public function test_the_list_labels_a_rule_incident_and_filters_by_it(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $rule = $this->makeIncident($chat, $this->makeMessage($chat, 1, 'rule link text'), 'rule');
        $operator = $this->makeIncident($chat, $this->makeMessage($chat, 2, 'operator text'), 'operator');

        Livewire::test(ListIncidents::class)
            ->assertSeeText('Link rule')
            ->filterTable('source', 'rule')
            ->assertCanSeeTableRecords([$rule])
            ->assertCanNotSeeTableRecords([$operator]);
    }

    public function test_the_view_page_says_the_link_rule_opened_it(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $incident = $this->makeIncident($chat, $this->makeMessage($chat, 1, 'rule link text'), 'rule');

        Livewire::test(ViewIncident::class, ['record' => $incident->getKey()])
            ->assertSeeText('Opened by the link rule')
            ->assertDontSeeText('operator-assigned');
    }

    public function test_a_prediction_without_a_contact_signal_says_why_it_is_listed(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $message = $this->makeMessage($chat, 1, 'request for collections');
        $profile = ModelProfile::forceCreate([
            'name' => 'test-moderation-'.random_int(1, 1_000_000),
            'provider' => 'ollama',
            'base_url' => 'http://host.docker.internal:11434/v1',
            'model' => 'gemma4:e2b-it-qat',
            'role' => 'moderation',
            'params' => json_encode(['reasoning_effort' => 'none']),
            'is_active' => true,
        ]);
        MessageClassification::forceCreate([
            'telegram_chat_id' => $chat->id,
            'telegram_message_id' => $message->message_id,
            'model_profile_id' => $profile->id,
            'prompt_version' => 'classify_v2',
            'taxonomy_version' => 1,
            'category' => 'SPAM_OR_AD',
            'needs_response' => false,
            'needs_moderation' => true,
            'severity' => 'medium',
            'confidence' => '0.950',
            'path' => 'live',
            'route' => 'possible_violation',
            'route_reason' => 'no_contact_signal',
            'confidence_floor' => '0.600',
            'incident_threshold' => '0.850',
            'is_current' => true,
        ]);

        Livewire::test(PossibleViolations::class)
            ->assertSeeText('No link, phone or handle')
            ->assertDontSeeText('Uncertain');
    }
}
