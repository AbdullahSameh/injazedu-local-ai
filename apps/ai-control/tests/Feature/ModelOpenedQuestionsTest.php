<?php

namespace Tests\Feature;

use App\Filament\Pages\ClassificationAccuracy;
use App\Models\AttentionItem;
use App\Models\MessageClassification;
use App\Models\ModelProfile;
use App\Models\TelegramChat;
use App\Models\TelegramMessage;
use App\Models\User;
use Illuminate\Foundation\Testing\DatabaseTransactions;
use Illuminate\Support\Facades\DB;
use Livewire\Livewire;
use Tests\TestCase;

/**
 * TG-M5.1, C9 (`classification-metrics.md` §8a): the Classification Accuracy page shows, per model,
 * the questions the model opened and what the humans did with them — dismissed ÷ opened with its
 * denominator (the pilot's false-positive gate), and beside the rule baseline how many were kept:
 * rule misses the model caught, which the recall floor's operator-added count never sees (M19,
 * amended). The same scenario `test_metrics_model_opened.py` proves on the Python side, smaller.
 *
 * Amended by TG-M5.3 (`specs/011-tg-m5-3-attention-judgement/contracts/dismissal-reasons.md` K8,
 * K11): the dismissal count reads "dismissed (any reason)", with its per-reason breakdown beside
 * it; its value is unchanged.
 *
 * Amended by TG-M5.3 again (`contracts/attention-metrics.md` §1 C9′, §3; `tasks.md` T045): an item
 * opened from an attention judgement is counted in that judgement's own attention block, never in a
 * classification block, and "Model-opened and kept" sums `model_kept` across both eras (M19).
 */
class ModelOpenedQuestionsTest extends TestCase
{
    use DatabaseTransactions;

    private function makeChat(): TelegramChat
    {
        return TelegramChat::forceCreate([
            'chat_id' => -random_int(10_000_000, 2_000_000_000),
            'chat_type' => 'group',
            'title' => 'Model Questions Group',
            'is_monitored' => true,
        ]);
    }

    private function makeMessage(TelegramChat $chat, int $messageId, \DateTimeInterface $sentAt): TelegramMessage
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
            'sent_at' => $sentAt,
            'is_service' => false,
            'is_from_moderator' => false,
            'original_text' => 'في محاضرة بكرة',
            'normalized_text' => 'في محاضره بكره',
            'entity_flags' => '{}',
            'source_update_id' => $updateId,
        ]);
    }

    private function makeModelItem(
        TelegramChat $chat,
        ModelProfile $profile,
        int $messageId,
        string $status,
        ?string $closeReason = null,
    ): void {
        $sentAt = now()->subHours(2)->addMinutes($messageId);
        $this->makeMessage($chat, $messageId, $sentAt);
        $prediction = MessageClassification::forceCreate([
            'telegram_chat_id' => $chat->id,
            'telegram_message_id' => $messageId,
            'model_profile_id' => $profile->id,
            'prompt_version' => 'classify_v2',
            'taxonomy_version' => 1,
            'category' => 'QUESTION_COURSE',
            'needs_response' => true,
            'needs_moderation' => false,
            'severity' => 'none',
            'confidence' => '0.950',
            'path' => 'live',
            'route' => 'none',
            'confidence_floor' => '0.600',
            'incident_threshold' => '0.850',
            'is_current' => true,
        ]);
        $answered = $status === 'answered';
        if ($answered) {
            $this->makeMessage($chat, $messageId + 1000, $sentAt->copy()->addMinute());
        }
        AttentionItem::forceCreate([
            'telegram_chat_id' => $chat->id,
            'telegram_message_id' => $messageId,
            'opened_at' => $sentAt,
            'source' => 'ai',
            'rule_version' => null,
            'message_classification_id' => $prediction->id,
            'status' => $status,
            'first_response_message_id' => $answered ? $messageId + 1000 : null,
            'first_response_at' => $answered ? $sentAt->copy()->addMinute() : null,
            'first_response_kind' => $answered ? 'direct_reply' : null,
            'close_reason' => $closeReason,
        ]);
    }

    private function makeAttentionItem(
        TelegramChat $chat,
        ModelProfile $profile,
        int $messageId,
        string $status,
        ?string $closeReason = null,
    ): void {
        $sentAt = now()->subHours(2)->addMinutes($messageId);
        $this->makeMessage($chat, $messageId, $sentAt);
        $judgementId = DB::table('message_attention_judgements')->insertGetId([
            'telegram_chat_id' => $chat->id,
            'telegram_message_id' => $messageId,
            'model_profile_id' => $profile->id,
            'prompt_version' => 'attention_test',
            'intent' => 'asking',
            // A stored value, given literally: the derivation has one definition, in Python
            // (S2, N2), and no PHP helper restates it. C9′ never reads this column.
            'needs_response' => true,
            'path' => 'live',
            'is_current' => true,
            'created_at' => $sentAt->copy()->addSeconds(5),
        ]);
        AttentionItem::forceCreate([
            'telegram_chat_id' => $chat->id,
            'telegram_message_id' => $messageId,
            'opened_at' => $sentAt,
            'source' => 'ai',
            'rule_version' => null,
            'attention_judgement_id' => $judgementId,
            'status' => $status,
            'close_reason' => $closeReason,
        ]);
    }

    public function test_the_page_shows_each_models_opened_questions_with_their_denominators(): void
    {
        $this->actingAs(User::factory()->create(['is_panel_operator' => true]));
        $chat = $this->makeChat();
        $profile = ModelProfile::forceCreate([
            'name' => 'test-model-questions-'.random_int(1, 1_000_000),
            'provider' => 'fake',
            'model' => 'fake-model-questions',
            'role' => 'moderation',
            'params' => json_encode([]),
            'is_active' => false,
        ]);
        $this->makeModelItem($chat, $profile, 1, 'answered');
        $this->makeModelItem($chat, $profile, 2, 'dismissed', 'not_a_question');
        $this->makeModelItem($chat, $profile, 3, 'open');

        $component = Livewire::test(ClassificationAccuracy::class)
            ->set('chatId', (string) $chat->id)
            ->set('periodFrom', now()->subDays(2)->toDateString())
            ->set('periodTo', now()->toDateString());

        $block = collect($component->instance()->blocks())->firstWhere('model', $profile->name);
        $this->assertNotNull($block);
        $this->assertSame(
            [
                'opened' => 3, 'dismissed' => 1, 'kept' => 2, 'answered' => 1, 'unanswered' => 1,
                'dismissed_not_a_question' => 1, 'dismissed_member_discussion' => 0,
                'dismissed_message_removed' => 0, 'dismissed_other' => 0,
            ],
            $block['model_questions'],
        );
        $this->assertSame(2, $component->instance()->modelKeptQuestions());

        $html = $component->html();
        $this->assertStringContainsString('Questions the model opened', $html);
        $this->assertStringContainsString('dismissed (any reason): 1 / 3', $html);
        $this->assertStringNotContainsString('dismissed as not a real question', $html);
        $this->assertStringContainsString('Model-opened and kept: 2', $html);
        $this->assertStringNotContainsString('%', $html);
    }

    public function test_an_attention_era_item_is_counted_in_its_attention_block_never_a_classification_one(): void
    {
        $this->actingAs(User::factory()->create(['is_panel_operator' => true]));
        $chat = $this->makeChat();
        $moderation = ModelProfile::forceCreate([
            'name' => 'test-model-questions-'.random_int(1, 1_000_000),
            'provider' => 'fake',
            'model' => 'fake-model-questions',
            'role' => 'moderation',
            'params' => json_encode([]),
            'is_active' => false,
        ]);
        $attention = ModelProfile::forceCreate([
            'name' => 'test-attention-questions-'.random_int(1, 1_000_000),
            'provider' => 'fake',
            'model' => 'fake-attention-questions',
            'role' => 'attention',
            'params' => json_encode([]),
            'is_active' => false,
        ]);
        // TG-M5.1 era: one item from a prediction, answered.
        $this->makeModelItem($chat, $moderation, 1, 'answered');
        // TG-M5.3 era: two items from attention judgements — one dismissed as member discussion,
        // one still open.
        $this->makeAttentionItem($chat, $attention, 2, 'dismissed', 'member_discussion');
        $this->makeAttentionItem($chat, $attention, 3, 'open');

        $component = Livewire::test(ClassificationAccuracy::class)
            ->set('chatId', (string) $chat->id)
            ->set('periodFrom', now()->subDays(2)->toDateString())
            ->set('periodTo', now()->toDateString());
        $page = $component->instance();

        $classificationBlock = collect($page->blocks())->firstWhere('model', $moderation->name);
        $this->assertNotNull($classificationBlock);
        $this->assertSame(
            [
                'opened' => 1, 'dismissed' => 0, 'kept' => 1, 'answered' => 1, 'unanswered' => 0,
                'dismissed_not_a_question' => 0, 'dismissed_member_discussion' => 0,
                'dismissed_message_removed' => 0, 'dismissed_other' => 0,
            ],
            $classificationBlock['model_questions'],
        );
        $this->assertNull(collect($page->blocks())->firstWhere('model', $attention->name));

        $attentionBlock = collect($page->attentionBlocks())->firstWhere('model', $attention->name);
        $this->assertNotNull($attentionBlock);
        $this->assertSame('attention_test', $attentionBlock['prompt_version']);
        $this->assertSame(
            [
                'opened' => 2, 'dismissed' => 1, 'kept' => 1, 'answered' => 0, 'unanswered' => 1,
                'dismissed_not_a_question' => 0, 'dismissed_member_discussion' => 1,
                'dismissed_message_removed' => 0, 'dismissed_other' => 0,
            ],
            $attentionBlock['model_questions'],
        );
        // M19: kept across both eras — a count, not a rate.
        $this->assertSame(2, $page->modelKeptQuestions());

        $html = $component->html();
        $this->assertStringContainsString("{$attention->name} · attention_test · attention judgement", $html);
        $this->assertStringContainsString('Model-opened, dismissed (any reason): 0 / 1', $html);
        $this->assertStringContainsString('Model-opened, dismissed (any reason): 1 / 2', $html);
        $this->assertStringContainsString('not a real question 0 · member discussion 1 · message removed 0 · other 0', $html);
        $this->assertStringContainsString('Model-opened and kept: 2', $html);
        $this->assertStringNotContainsString('%', $html);
    }
}
