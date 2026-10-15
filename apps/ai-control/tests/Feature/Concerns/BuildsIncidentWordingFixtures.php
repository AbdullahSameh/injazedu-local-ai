<?php

namespace Tests\Feature\Concerns;

use App\Models\MessageClassification;
use App\Models\ModelProfile;
use App\Models\ModerationIncident;
use App\Models\Moderator;
use App\Models\TelegramChat;
use App\Models\TelegramMessage;
use App\Models\TelegramUser;
use App\Models\User;
use Illuminate\Support\Facades\DB;

/**
 * The incident-wording fixture (T053, P17), shared by `IncidentWordingTest` and its Arabic twin
 * `IncidentWordingArabicTest` so both read the same screens.
 */
trait BuildsIncidentWordingFixtures
{
    protected function actingAsPanelOperator(): User
    {
        $user = User::factory()->create(['is_panel_operator' => true]);
        $this->actingAs($user);

        return $user;
    }

    protected function makeChat(): TelegramChat
    {
        return TelegramChat::forceCreate([
            'chat_id' => -random_int(10_000_000, 2_000_000_000),
            'chat_type' => 'group',
            'title' => 'Incident Group',
            'is_monitored' => true,
            'bot_status' => 'member',
        ]);
    }

    protected function makeCapturedUpdate(TelegramChat $chat, string $updateType): int
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

    protected function makeMessage(TelegramChat $chat, int $messageId): TelegramMessage
    {
        $senderId = TelegramUser::forceCreate([
            'tg_user_id' => random_int(10_000_000, 2_000_000_000),
            'is_bot' => false,
        ])->id;

        return TelegramMessage::forceCreate([
            'telegram_chat_id' => $chat->id,
            'message_id' => $messageId,
            'telegram_user_id' => $senderId,
            'sent_at' => now()->subHours(3),
            'is_service' => false,
            'is_from_moderator' => false,
            'original_text' => 'spam text',
            'normalized_text' => 'spam text',
            'entity_flags' => [],
            'source_update_id' => $this->makeCapturedUpdate($chat, 'message'),
        ]);
    }

    protected function makeModerationProfile(): ModelProfile
    {
        return ModelProfile::forceCreate([
            'name' => 'wording-moderation-'.random_int(1, 1_000_000),
            'provider' => 'ollama',
            'base_url' => 'http://host.docker.internal:11434/v1',
            'model' => 'gemma4:e2b-it-qat',
            'role' => 'moderation',
            'params' => json_encode(['reasoning_effort' => 'none']),
            'is_active' => true,
        ]);
    }

    protected function makeClassification(
        TelegramChat $chat,
        TelegramMessage $message,
        ModelProfile $profile,
        array $overrides = [],
    ): MessageClassification {
        return MessageClassification::forceCreate(array_merge([
            'telegram_chat_id' => $chat->id,
            'telegram_message_id' => $message->message_id,
            'model_profile_id' => $profile->id,
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
        ], $overrides));
    }

    protected function insertAction(array $overrides): void
    {
        DB::table('moderation_actions')->insert(array_merge([
            'detail' => json_encode([]),
        ], $overrides));
    }

    /**
     * One incident carrying every evidence kind: a reaction, a direct reply (read in place, no
     * row), a ban, an expulsion, a restriction, a reversal, and every panel act.
     */
    protected function makeIncidentWithEveryEvidenceKind(): ModerationIncident
    {
        $chat = $this->makeChat();
        $message = $this->makeMessage($chat, 1);
        $incident = ModerationIncident::forceCreate([
            'telegram_chat_id' => $chat->id,
            'telegram_message_id' => $message->message_id,
            'opened_at' => $message->sent_at,
            'detected_at' => now()->subHours(2),
            'source' => 'operator',
            'opened_by_user_id' => 1,
            'category' => 'SPAM_OR_AD',
            'severity' => 'low',
        ]);

        // A moderator's direct reply — read in place, not a row.
        TelegramMessage::forceCreate([
            'telegram_chat_id' => $chat->id,
            'message_id' => 2,
            'telegram_user_id' => $message->telegram_user_id,
            'sent_at' => now()->subMinutes(110),
            'reply_to_message_id' => $message->message_id,
            'is_service' => false,
            'is_from_moderator' => true,
            'original_text' => 'please stop',
            'normalized_text' => 'please stop',
            'entity_flags' => [],
            'source_update_id' => $this->makeCapturedUpdate($chat, 'message'),
        ]);

        foreach (['ban', 'expulsion', 'restriction', 'reversal'] as $kind) {
            $this->insertAction([
                'telegram_chat_id' => $chat->id,
                'action_type' => $kind,
                'action_strength' => $kind === 'reversal' ? null : 'enforcement',
                'occurred_at' => now()->subMinutes(90),
                'subject_telegram_user_id' => $message->telegram_user_id,
                'source_update_id' => $this->makeCapturedUpdate($chat, 'chat_member'),
            ]);
        }

        $reactingModeratorIdentity = TelegramUser::forceCreate([
            'tg_user_id' => random_int(10_000_000, 2_000_000_000),
            'is_bot' => false,
        ]);
        $reactingModerator = Moderator::create([
            'telegram_user_id' => $reactingModeratorIdentity->id,
            'display_name' => 'Reacting Moderator',
        ]);
        $this->insertAction([
            'telegram_chat_id' => $chat->id,
            'action_type' => 'reaction',
            'action_strength' => 'acknowledgement',
            'occurred_at' => now()->subMinutes(100),
            'target_message_id' => $message->message_id,
            'actor_moderator_id' => $reactingModerator->id,
            'actor_telegram_user_id' => $reactingModeratorIdentity->id,
            'source_update_id' => $this->makeCapturedUpdate($chat, 'message_reaction'),
        ]);

        foreach ([
            ['panel_acknowledge', 'acknowledgement', null],
            ['panel_resolve', 'confirmation', 'Confirmed with the group owner.'],
            ['panel_false_positive', null, 'Reported in error.'],
        ] as [$kind, $strength, $note]) {
            $this->insertAction([
                'telegram_chat_id' => $chat->id,
                'action_type' => $kind,
                'action_strength' => $strength,
                'occurred_at' => now()->subMinutes(80),
                'panel_user_id' => 1,
                'moderation_incident_id' => $incident->id,
                'note' => $note,
            ]);
        }

        return $incident;
    }
}
