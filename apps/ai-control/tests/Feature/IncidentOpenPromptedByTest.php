<?php

namespace Tests\Feature;

use App\Filament\Pages\LiveAttentionQueue;
use App\Filament\Resources\Incidents\Pages\ListIncidents;
use App\Models\AttentionItem;
use App\Models\MessageClassification;
use App\Models\ModelProfile;
use App\Models\ModerationIncident;
use App\Models\TelegramChat;
use App\Models\TelegramMessage;
use App\Models\User;
use Illuminate\Database\QueryException;
use Illuminate\Foundation\Testing\DatabaseTransactions;
use Illuminate\Support\Facades\DB;
use Livewire\Livewire;
use Tests\TestCase;

/**
 * T057 (US5): `ModerationIncident::openOn(..., promptedByClassificationId:)` writes
 * `prompted_by_classification_id` and leaves `message_classification_id` NULL with
 * `source='operator'` — a list-prompted flag is still fully operator-opened
 * (`ck_incident_operator_labels`); the Incidents list's and the Live Attention Queue's own row
 * actions write no prompted-by (they are independent flags); a prompted-by naming another
 * message's prediction is refused by the database (`fk_incident_prompted_by`, probe 9 E2/E3,
 * FR-043, FR-044).
 */
class IncidentOpenPromptedByTest extends TestCase
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
            'title' => 'Prompted Group',
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

    private function makeMessage(TelegramChat $chat, int $messageId): TelegramMessage
    {
        return TelegramMessage::forceCreate([
            'telegram_chat_id' => $chat->id,
            'message_id' => $messageId,
            'sent_at' => now()->subMinutes(10),
            'is_service' => false,
            'is_from_moderator' => false,
            'original_text' => 'advert text',
            'normalized_text' => 'advert text',
            'entity_flags' => '{}',
            'source_update_id' => $this->makeCapturedUpdate($chat),
        ]);
    }

    private function makeModerationProfile(): ModelProfile
    {
        return ModelProfile::forceCreate([
            'name' => 'test-moderation-'.random_int(1, 1_000_000),
            'provider' => 'ollama',
            'base_url' => 'http://host.docker.internal:11434/v1',
            'model' => 'gemma4:e2b-it-qat',
            'role' => 'moderation',
            'params' => json_encode(['reasoning_effort' => 'none']),
            'is_active' => false,
        ]);
    }

    private function makeClassification(TelegramChat $chat, TelegramMessage $message): MessageClassification
    {
        return MessageClassification::forceCreate([
            'telegram_chat_id' => $chat->id,
            'telegram_message_id' => $message->message_id,
            'model_profile_id' => $this->makeModerationProfile()->id,
            'prompt_version' => 'classify_v1',
            'taxonomy_version' => 1,
            'category' => 'SPAM_OR_AD',
            'needs_response' => false,
            'needs_moderation' => true,
            'severity' => 'low',
            'confidence' => '0.720',
            'path' => 'live',
            'route' => 'possible_violation',
            'route_reason' => 'uncertain',
            'confidence_floor' => '0.600',
            'incident_threshold' => '0.850',
            'is_current' => true,
        ]);
    }

    public function test_open_on_with_prompted_by_writes_it_and_leaves_message_classification_id_null(): void
    {
        $operator = $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $message = $this->makeMessage($chat, 1);
        $classification = $this->makeClassification($chat, $message);

        $incident = ModerationIncident::openOn(
            $message,
            'SPAM_OR_AD',
            'low',
            $operator,
            promptedByClassificationId: $classification->id,
        );

        $this->assertNotNull($incident);
        $this->assertSame('operator', $incident->source);
        $this->assertSame($classification->id, $incident->prompted_by_classification_id);
        $this->assertNull($incident->message_classification_id);
        $this->assertSame($operator->id, $incident->opened_by_user_id);
    }

    public function test_the_incidents_lists_own_action_writes_no_prompted_by(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $message = $this->makeMessage($chat, 1);

        Livewire::test(ListIncidents::class)
            ->callTableAction('open_incident', data: [
                'telegram_message_id' => $message->id,
                'category' => 'SPAM_OR_AD',
                'severity' => 'low',
            ])
            ->assertHasNoTableActionErrors();

        $incident = ModerationIncident::query()
            ->where('telegram_chat_id', $chat->id)
            ->where('telegram_message_id', $message->message_id)
            ->firstOrFail();
        $this->assertNull($incident->prompted_by_classification_id);
    }

    public function test_the_live_attention_queues_own_action_writes_no_prompted_by(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $message = $this->makeMessage($chat, 1);
        $item = AttentionItem::forceCreate([
            'telegram_chat_id' => $chat->id,
            'telegram_message_id' => $message->message_id,
            'opened_at' => $message->sent_at,
            'source' => 'rule',
            'rule_version' => 1,
            'status' => 'open',
        ]);

        Livewire::test(LiveAttentionQueue::class)
            ->callTableAction('open_incident', $item, data: [
                'category' => 'SPAM_OR_AD',
                'severity' => 'low',
            ])
            ->assertHasNoTableActionErrors();

        $incident = ModerationIncident::query()
            ->where('telegram_chat_id', $chat->id)
            ->where('telegram_message_id', $message->message_id)
            ->firstOrFail();
        $this->assertNull($incident->prompted_by_classification_id);
    }

    public function test_a_prompted_by_naming_another_messages_prediction_is_refused(): void
    {
        $operator = $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $message = $this->makeMessage($chat, 1);
        $otherMessage = $this->makeMessage($chat, 2);
        $classificationOfOtherMessage = $this->makeClassification($chat, $otherMessage);

        $this->expectException(QueryException::class);

        ModerationIncident::openOn(
            $message,
            'SPAM_OR_AD',
            'low',
            $operator,
            promptedByClassificationId: $classificationOfOtherMessage->id,
        );
    }
}
