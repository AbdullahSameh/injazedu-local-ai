<?php

namespace Tests\Feature;

use App\Models\MessageClassification;
use App\Models\MessageClassificationAttempt;
use App\Models\ModelProfile;
use App\Models\TelegramChat;
use App\Models\TelegramUser;
use Illuminate\Foundation\Testing\DatabaseTransactions;
use Illuminate\Support\Facades\DB;
use LogicException;
use Tests\TestCase;

/**
 * T029 (FR-015, D-TG-147): `message_classifications` and `message_classification_attempts` are
 * immutable — a prediction is a claim, recorded once and never changed. `booted()` on both models
 * throws on `update()` and `delete()` so the invariant holds from `tinker` too, mirroring
 * `ModerationActionImmutabilityTest`.
 */
class ClassificationImmutabilityTest extends TestCase
{
    use DatabaseTransactions;

    private function makeChat(): TelegramChat
    {
        return TelegramChat::forceCreate([
            'chat_id' => -random_int(10_000_000, 2_000_000_000),
            'chat_type' => 'group',
            'title' => 'Test Group',
            'is_monitored' => true,
        ]);
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

    private function makeMessage(TelegramChat $chat, int $messageId): object
    {
        $sender = TelegramUser::forceCreate([
            'tg_user_id' => random_int(10_000_000, 2_000_000_000),
            'is_bot' => false,
        ]);

        $id = DB::table('telegram_messages')->insertGetId([
            'telegram_chat_id' => $chat->id,
            'message_id' => $messageId,
            'telegram_user_id' => $sender->id,
            'sent_at' => now(),
            'is_service' => false,
            'is_from_moderator' => false,
            'original_text' => 'buy now, best price',
            'normalized_text' => 'buy now, best price',
            'entity_flags' => json_encode([]),
            'source_update_id' => $this->makeCapturedUpdate($chat),
        ]);

        return (object) ['id' => $id, 'message_id' => $messageId];
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

    private function makeClassification(TelegramChat $chat, object $message, ModelProfile $profile): MessageClassification
    {
        return MessageClassification::forceCreate([
            'telegram_chat_id' => $chat->id,
            'telegram_message_id' => $message->message_id,
            'model_profile_id' => $profile->id,
            'prompt_version' => 'classify_v1',
            'taxonomy_version' => 1,
            'category' => 'SPAM_OR_AD',
            'needs_response' => false,
            'needs_moderation' => true,
            'severity' => 'high',
            'confidence' => '0.900',
            'path' => 'live',
            'route' => 'incident',
            'confidence_floor' => '0.600',
            'incident_threshold' => '0.850',
            'is_current' => true,
        ]);
    }

    private function makeAttempt(TelegramChat $chat, object $message): MessageClassificationAttempt
    {
        return MessageClassificationAttempt::forceCreate([
            'telegram_chat_id' => $chat->id,
            'telegram_message_id' => $message->message_id,
            'path' => 'live',
            'outcome' => 'excluded',
            'reason' => 'moderator',
        ]);
    }

    public function test_inserting_a_prediction_succeeds(): void
    {
        $chat = $this->makeChat();
        $message = $this->makeMessage($chat, 1);
        $profile = $this->makeModerationProfile();

        $classification = $this->makeClassification($chat, $message, $profile);

        $this->assertDatabaseHas('message_classifications', [
            'id' => $classification->id,
            'category' => 'SPAM_OR_AD',
        ]);
    }

    public function test_inserting_an_attempt_succeeds(): void
    {
        $chat = $this->makeChat();
        $message = $this->makeMessage($chat, 1);

        $attempt = $this->makeAttempt($chat, $message);

        $this->assertDatabaseHas('message_classification_attempts', [
            'id' => $attempt->id,
            'outcome' => 'excluded',
        ]);
    }

    public function test_updating_a_prediction_throws_and_leaves_the_row_unchanged(): void
    {
        $chat = $this->makeChat();
        $message = $this->makeMessage($chat, 1);
        $profile = $this->makeModerationProfile();
        $classification = $this->makeClassification($chat, $message, $profile);
        $originalCategory = $classification->category;

        $classification->category = 'OTHER';

        $this->expectException(LogicException::class);

        try {
            $classification->save();
        } finally {
            $this->assertSame($originalCategory, $classification->fresh()->category);
        }
    }

    public function test_deleting_a_prediction_throws_and_leaves_the_row_in_place(): void
    {
        $chat = $this->makeChat();
        $message = $this->makeMessage($chat, 1);
        $profile = $this->makeModerationProfile();
        $classification = $this->makeClassification($chat, $message, $profile);

        $this->expectException(LogicException::class);

        try {
            $classification->delete();
        } finally {
            $this->assertDatabaseHas('message_classifications', ['id' => $classification->id]);
        }
    }

    public function test_updating_an_attempt_throws_and_leaves_the_row_unchanged(): void
    {
        $chat = $this->makeChat();
        $message = $this->makeMessage($chat, 1);
        $attempt = $this->makeAttempt($chat, $message);
        $originalReason = $attempt->reason;

        $attempt->reason = 'service';

        $this->expectException(LogicException::class);

        try {
            $attempt->save();
        } finally {
            $this->assertSame($originalReason, $attempt->fresh()->reason);
        }
    }

    public function test_deleting_an_attempt_throws_and_leaves_the_row_in_place(): void
    {
        $chat = $this->makeChat();
        $message = $this->makeMessage($chat, 1);
        $attempt = $this->makeAttempt($chat, $message);

        $this->expectException(LogicException::class);

        try {
            $attempt->delete();
        } finally {
            $this->assertDatabaseHas('message_classification_attempts', ['id' => $attempt->id]);
        }
    }
}
