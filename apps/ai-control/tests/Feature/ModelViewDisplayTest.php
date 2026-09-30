<?php

namespace Tests\Feature;

use App\Filament\Pages\LiveAttentionQueue;
use App\Filament\Resources\Incidents\Pages\ListIncidents;
use App\Filament\Resources\Incidents\Pages\ViewIncident;
use App\Models\AttentionItem;
use App\Models\MessageClassification;
use App\Models\MessageClassificationAttempt;
use App\Models\ModelProfile;
use App\Models\ModerationIncident;
use App\Models\TelegramChat;
use App\Models\TelegramMessage;
use App\Models\User;
use Illuminate\Foundation\Testing\DatabaseTransactions;
use Illuminate\Support\Facades\DB;
use Livewire\Livewire;
use Tests\TestCase;

/**
 * T072 (US7, `control-panel-classification.md` §2.1-§2.3, §5): the Live Attention Queue's one
 * new column reads C6 for the row's item and falls back to the anchor's §5 status without
 * touching order, ageing or actions; the incidents list gains **Opened by** (column and filter);
 * the incident detail's "why flagged" answers each of the three cases in §2.3's table; TG-M4's
 * "No model classification — arrives with TG-M5" line is gone; a confidence is always
 * "self-reported confidence", never `%`, "probability", "chance" or "likelihood" (FR-052...FR-056,
 * W1-W2).
 */
class ModelViewDisplayTest extends TestCase
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
            'title' => 'Model View Group',
            'is_monitored' => true,
        ], $overrides));
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

    private function makeMessage(TelegramChat $chat, int $messageId, array $overrides = []): TelegramMessage
    {
        return TelegramMessage::forceCreate(array_merge([
            'telegram_chat_id' => $chat->id,
            'message_id' => $messageId,
            'sent_at' => now()->subMinutes(10),
            'is_service' => false,
            'is_from_moderator' => false,
            'original_text' => 'spam text',
            'normalized_text' => 'spam text',
            'entity_flags' => [],
            'source_update_id' => $this->makeCapturedUpdate($chat),
        ], $overrides));
    }

    private function makeModerationProfile(array $overrides = []): ModelProfile
    {
        return ModelProfile::forceCreate(array_merge([
            'name' => 'test-moderation-'.random_int(1, 1_000_000),
            'provider' => 'ollama',
            'base_url' => 'http://host.docker.internal:11434/v1',
            'model' => 'gemma4:e2b-it-qat',
            'role' => 'moderation',
            'params' => json_encode(['reasoning_effort' => 'none']),
            'is_active' => true,
        ], $overrides));
    }

    private function makeClassification(
        TelegramChat $chat,
        TelegramMessage $message,
        array $overrides = [],
    ): MessageClassification {
        return MessageClassification::forceCreate(array_merge([
            'telegram_chat_id' => $chat->id,
            'telegram_message_id' => $message->message_id,
            'model_profile_id' => $this->makeModerationProfile()->id,
            'prompt_version' => 'classify_v1',
            'taxonomy_version' => 1,
            'category' => 'SPAM_OR_AD',
            'needs_response' => false,
            'needs_moderation' => true,
            'severity' => 'low',
            'confidence' => '0.930',
            'path' => 'live',
            'route' => 'incident',
            'route_reason' => null,
            'confidence_floor' => '0.600',
            'incident_threshold' => '0.850',
            'is_current' => true,
        ], $overrides));
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

    public function test_the_queue_column_shows_c6s_label_for_a_classified_item(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $message = $this->makeMessage($chat, 1);
        $item = $this->makeItem($chat, $message);
        $this->makeClassification($chat, $message, [
            'needs_response' => true,
            'route' => 'possible_violation',
            'route_reason' => 'uncertain',
        ]);

        Livewire::test(LiveAttentionQueue::class)
            ->assertSeeText('SPAM_OR_AD')
            ->assertSeeText('self-reported confidence');
    }

    public function test_the_queue_column_falls_back_to_the_anchors_status_when_unclassified(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();

        $excludedMessage = $this->makeMessage($chat, 1);
        $this->makeItem($chat, $excludedMessage);
        MessageClassificationAttempt::forceCreate([
            'telegram_chat_id' => $chat->id,
            'telegram_message_id' => $excludedMessage->message_id,
            'path' => 'live',
            'outcome' => 'excluded',
            'reason' => 'moderator',
        ]);

        $failedMessage = $this->makeMessage($chat, 2);
        $this->makeItem($chat, $failedMessage);
        MessageClassificationAttempt::forceCreate([
            'telegram_chat_id' => $chat->id,
            'telegram_message_id' => $failedMessage->message_id,
            'path' => 'live',
            'outcome' => 'failed',
            'reason' => 'model_truncated',
            'model_profile_id' => $this->makeModerationProfile()->id,
        ]);

        $unclassifiedMessage = $this->makeMessage($chat, 3);
        $this->makeItem($chat, $unclassifiedMessage);

        $test = Livewire::test(LiveAttentionQueue::class);
        $test->assertSeeText("Not sent to the model — moderator's message");
        $test->assertSeeText('The model could not classify this message — answer cut off');
        $test->assertSeeText('Not classified yet — awaiting the model, or recorded before classification began.');
    }

    public function test_the_queue_column_reports_no_active_model_first(): void
    {
        $this->actingAsPanelOperator();
        $this->makeModerationProfile(['is_active' => false]);
        $chat = $this->makeChat();
        $message = $this->makeMessage($chat, 1);
        $this->makeItem($chat, $message);

        Livewire::test(LiveAttentionQueue::class)
            ->assertSeeText('No classification model is active.');
    }

    public function test_the_queue_columns_order_ageing_and_actions_are_unchanged(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();

        $longestWaiting = $this->makeItem($chat, $this->makeMessage($chat, 1, [
            'sent_at' => now()->subHours(3),
        ]));
        $shortestWaiting = $this->makeItem($chat, $this->makeMessage($chat, 2, [
            'sent_at' => now()->subMinutes(5),
        ]));

        Livewire::test(LiveAttentionQueue::class)
            ->assertCanSeeTableRecords([$longestWaiting, $shortestWaiting], inOrder: true)
            ->assertTableActionExists('dismiss_not_a_question')
            ->assertTableActionExists('dismiss_message_removed');
    }

    public function test_the_incidents_list_shows_opened_by_and_the_filter_narrows(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();

        $operatorMessage = $this->makeMessage($chat, 1);
        $operatorIncident = ModerationIncident::forceCreate([
            'telegram_chat_id' => $chat->id,
            'telegram_message_id' => $operatorMessage->message_id,
            'opened_at' => $operatorMessage->sent_at,
            'detected_at' => now(),
            'source' => 'operator',
            'opened_by_user_id' => 1,
            'category' => 'SPAM_OR_AD',
            'severity' => 'low',
        ]);

        $aiMessage = $this->makeMessage($chat, 2);
        $aiClassification = $this->makeClassification($chat, $aiMessage);
        $aiIncident = ModerationIncident::forceCreate([
            'telegram_chat_id' => $chat->id,
            'telegram_message_id' => $aiMessage->message_id,
            'opened_at' => $aiMessage->sent_at,
            'detected_at' => now(),
            'source' => 'ai',
            'opened_by_user_id' => null,
            'category' => $aiClassification->category,
            'severity' => $aiClassification->severity,
            'message_classification_id' => $aiClassification->id,
        ]);

        Livewire::test(ListIncidents::class)
            ->assertSeeText('Operator')
            ->assertSeeText('Model')
            ->filterTable('source', 'ai')
            ->assertCanSeeTableRecords([$aiIncident])
            ->assertCanNotSeeTableRecords([$operatorIncident]);
    }

    public function test_why_flagged_for_an_independent_operator_flag(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $message = $this->makeMessage($chat, 1);
        $this->makeModerationProfile();
        $incident = ModerationIncident::forceCreate([
            'telegram_chat_id' => $chat->id,
            'telegram_message_id' => $message->message_id,
            'opened_at' => $message->sent_at,
            'detected_at' => now(),
            'source' => 'operator',
            'opened_by_user_id' => 1,
            'category' => 'SPAM_OR_AD',
            'severity' => 'low',
        ]);

        Livewire::test(ViewIncident::class, ['record' => $incident->getKey()])
            ->assertSeeText('operator-assigned')
            ->assertSeeText('Not classified yet — awaiting the model, or recorded before classification began.')
            ->assertDontSeeText('Flagged from the possible-violations list')
            ->assertDontSeeText('No model classification — arrives with TG-M5');
    }

    public function test_why_flagged_for_a_list_prompted_flag(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $message = $this->makeMessage($chat, 1);
        $listing = $this->makeClassification($chat, $message, [
            'route' => 'possible_violation',
            'route_reason' => 'uncertain',
            'confidence' => '0.720',
        ]);
        $incident = ModerationIncident::forceCreate([
            'telegram_chat_id' => $chat->id,
            'telegram_message_id' => $message->message_id,
            'opened_at' => $message->sent_at,
            'detected_at' => now(),
            'source' => 'operator',
            'opened_by_user_id' => 1,
            'category' => 'SPAM_OR_AD',
            'severity' => 'low',
            'prompted_by_classification_id' => $listing->id,
        ]);

        Livewire::test(ViewIncident::class, ['record' => $incident->getKey()])
            ->assertSeeText('Flagged from the possible-violations list')
            ->assertSeeText($listing->modelProfile->name)
            ->assertSeeText('0.720')
            ->assertSeeText('self-reported confidence');
    }

    public function test_why_flagged_for_a_model_opened_incident(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $message = $this->makeMessage($chat, 1);
        $prediction = $this->makeClassification($chat, $message, [
            'confidence' => '0.930',
        ]);
        $incident = ModerationIncident::forceCreate([
            'telegram_chat_id' => $chat->id,
            'telegram_message_id' => $message->message_id,
            'opened_at' => $message->sent_at,
            'detected_at' => now(),
            'source' => 'ai',
            'opened_by_user_id' => null,
            'category' => $prediction->category,
            'severity' => $prediction->severity,
            'message_classification_id' => $prediction->id,
        ]);

        Livewire::test(ViewIncident::class, ['record' => $incident->getKey()])
            ->assertSeeText('Opened by the model')
            ->assertSeeText("the model's")
            ->assertSeeText($prediction->modelProfile->name)
            ->assertSeeText('classify_v1')
            ->assertSeeText('0.930')
            ->assertSeeText('self-reported confidence')
            ->assertDontSeeText('No model classification — arrives with TG-M5');
    }

    public function test_no_confidence_is_ever_a_percentage_probability_chance_or_likelihood(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $message = $this->makeMessage($chat, 1);
        $prediction = $this->makeClassification($chat, $message);
        $incident = ModerationIncident::forceCreate([
            'telegram_chat_id' => $chat->id,
            'telegram_message_id' => $message->message_id,
            'opened_at' => $message->sent_at,
            'detected_at' => now(),
            'source' => 'ai',
            'opened_by_user_id' => null,
            'category' => $prediction->category,
            'severity' => $prediction->severity,
            'message_classification_id' => $prediction->id,
        ]);

        $html = Livewire::test(ViewIncident::class, ['record' => $incident->getKey()])->html();

        $this->assertDoesNotMatchRegularExpression('/self-reported confidence\s*%/i', $html);
        $this->assertDoesNotMatchRegularExpression('/probability/i', $html);
        $this->assertDoesNotMatchRegularExpression('/\bchance\b/i', $html);
        $this->assertDoesNotMatchRegularExpression('/likelihood/i', $html);
    }
}
