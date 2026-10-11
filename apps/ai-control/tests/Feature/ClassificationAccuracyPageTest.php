<?php

namespace Tests\Feature;

use App\Filament\Pages\ClassificationAccuracy;
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
 * T065 (US6): the Classification Accuracy page renders research probe 10's fourteen-message,
 * two-model scenario (the same one `test_metrics.py`'s `test_probe_10_scenario_matches_every_
 * hand_computed_figure` proves on the Python side) — every figure as numerator / denominator, one
 * block per model, never pooled; list-prompted shown apart; a zero denominator reads "no labelled
 * examples"; the estimate heading present; no `%`, no "average", no " avg", no combined score
 * (`control-panel-classification.md` §4, FR-046...FR-049, SC-012, SC-013).
 */
class ClassificationAccuracyPageTest extends TestCase
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
            'title' => 'Accuracy Group',
            'is_monitored' => true,
        ]);
    }

    private function makeModerationProfile(string $suffix): ModelProfile
    {
        return ModelProfile::forceCreate([
            'name' => "test-accuracy-{$suffix}-".random_int(1, 1_000_000),
            'provider' => 'fake',
            'model' => "fake-{$suffix}",
            'role' => 'moderation',
            'params' => json_encode([]),
            'is_active' => false,
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

    private function makeMessage(
        TelegramChat $chat,
        int $messageId,
        \DateTimeInterface $sentAt,
        array $overrides = [],
    ): TelegramMessage {
        return TelegramMessage::forceCreate(array_merge([
            'telegram_chat_id' => $chat->id,
            'message_id' => $messageId,
            'sent_at' => $sentAt,
            'is_service' => false,
            'is_from_moderator' => false,
            'original_text' => 'نص للتصنيف',
            'normalized_text' => 'نص للتصنيف',
            'entity_flags' => '{}',
            'source_update_id' => $this->makeCapturedUpdate($chat),
        ], $overrides));
    }

    private function makePrediction(
        TelegramChat $chat,
        int $messageId,
        ModelProfile $profile,
        array $overrides = [],
    ): MessageClassification {
        return MessageClassification::forceCreate(array_merge([
            'telegram_chat_id' => $chat->id,
            'telegram_message_id' => $messageId,
            'model_profile_id' => $profile->id,
            'prompt_version' => 'classify_v1',
            'taxonomy_version' => 1,
            'category' => 'CHITCHAT',
            'needs_response' => false,
            'needs_moderation' => false,
            'severity' => 'none',
            'confidence' => '0.900',
            'path' => 'live',
            'route' => 'none',
            'route_reason' => null,
            'confidence_floor' => '0.600',
            'incident_threshold' => '0.850',
            'is_current' => true,
        ], $overrides));
    }

    private function makeItem(
        TelegramChat $chat,
        int $messageId,
        \DateTimeInterface $openedAt,
        array $overrides = [],
    ): AttentionItem {
        return AttentionItem::forceCreate(array_merge([
            'telegram_chat_id' => $chat->id,
            'telegram_message_id' => $messageId,
            'opened_at' => $openedAt,
            'source' => 'rule',
            'rule_version' => 1,
            'status' => 'open',
        ], $overrides));
    }

    /**
     * Builds probe 10's own scenario: three question items (one a two-message burst), two
     * unverified messages (one per model), four incidents (two independent, one list-prompted,
     * one model-opened — two of the four closed as a false positive), one unanchored possible
     * violation, one excluded message and one failed one — fourteen messages in total.
     *
     * @return array{chat: TelegramChat, modelA: ModelProfile, modelB: ModelProfile}
     */
    private function seedScenario(): array
    {
        $chat = $this->makeChat();
        $modelA = $this->makeModerationProfile('a');
        $modelB = $this->makeModerationProfile('b');
        $base = now()->subDays(1)->startOfHour();
        $sentAt = fn (int $n) => (clone $base)->addMinutes($n);

        // C1: three question items.
        $this->makeMessage($chat, 1, $sentAt(1), ['original_text' => 'السلام عليكم']);
        $this->makePrediction($chat, 1, $modelA, ['category' => 'CHITCHAT', 'needs_response' => false]);
        $item1 = $this->makeItem($chat, 1, $sentAt(1));
        $m2 = $this->makeMessage($chat, 2, $sentAt(2), ['original_text' => 'هل الاختبار الاسبوع القادم؟']);
        $m2->forceFill(['attention_item_id' => $item1->id])->save();
        $this->makePrediction($chat, 2, $modelA, [
            'category' => 'QUESTION_COURSE', 'needs_response' => true,
        ]);

        $this->makeMessage($chat, 3, $sentAt(3), ['original_text' => 'مبروك عليكم']);
        $this->makePrediction($chat, 3, $modelA, ['category' => 'CHITCHAT', 'needs_response' => false]);
        $this->makeItem($chat, 3, $sentAt(3), ['status' => 'dismissed']);

        $this->makeMessage($chat, 4, $sentAt(4), ['original_text' => 'ما هي خطوات التسجيل؟']);
        $this->makePrediction($chat, 4, $modelA, [
            'category' => 'QUESTION_ACCESS', 'needs_response' => true,
        ]);
        $this->makeItem($chat, 4, $sentAt(4), ['source' => 'operator', 'rule_version' => null]);

        // C2: one unverified message per model.
        $this->makeMessage($chat, 5, $sentAt(5), ['original_text' => 'هل يوجد تمديد؟']);
        $this->makePrediction($chat, 5, $modelA, [
            'category' => 'QUESTION_COURSE', 'needs_response' => true,
        ]);
        $this->makeMessage($chat, 6, $sentAt(6), ['original_text' => 'متى ينزل الجدول؟']);
        $this->makePrediction($chat, 6, $modelB, [
            'category' => 'QUESTION_COURSE', 'needs_response' => true,
        ]);

        // C3/C8: four incidents.
        $this->makeMessage($chat, 7, $sentAt(7), ['original_text' => 'اعلان اول']);
        $p7 = $this->makePrediction($chat, 7, $modelA, [
            'category' => 'SPAM_OR_AD', 'needs_moderation' => true, 'severity' => 'medium',
            'route' => 'possible_violation', 'route_reason' => 'uncertain', 'confidence' => '0.700',
        ]);
        ModerationIncident::forceCreate([
            'telegram_chat_id' => $chat->id, 'telegram_message_id' => 7,
            'opened_at' => $sentAt(7), 'detected_at' => $sentAt(7)->addSeconds(30),
            'source' => 'operator', 'opened_by_user_id' => 1,
            'category' => 'SPAM_OR_AD', 'severity' => 'medium',
        ]);

        $this->makeMessage($chat, 8, $sentAt(8), ['original_text' => 'رسالة اساء الفهم']);
        $this->makePrediction($chat, 8, $modelA, [
            'category' => 'CHITCHAT', 'needs_moderation' => false, 'confidence' => '0.850',
        ]);
        $i2 = ModerationIncident::forceCreate([
            'telegram_chat_id' => $chat->id, 'telegram_message_id' => 8,
            'opened_at' => $sentAt(8), 'detected_at' => $sentAt(8)->addSeconds(120),
            'source' => 'operator', 'opened_by_user_id' => 1,
            'category' => 'SPAM_OR_AD', 'severity' => 'low',
        ]);
        DB::table('moderation_actions')->insert([
            'telegram_chat_id' => $chat->id, 'action_type' => 'panel_false_positive',
            'occurred_at' => $sentAt(8)->addMinutes(30), 'panel_user_id' => 1,
            'moderation_incident_id' => $i2->id, 'note' => 'false alarm', 'detail' => json_encode([]),
        ]);

        $this->makeMessage($chat, 9, $sentAt(9), ['original_text' => 'اعلان ثاني']);
        $p9 = $this->makePrediction($chat, 9, $modelA, [
            'category' => 'ABUSE', 'needs_moderation' => true, 'severity' => 'medium',
            'route' => 'possible_violation', 'route_reason' => 'uncertain', 'confidence' => '0.750',
        ]);
        ModerationIncident::forceCreate([
            'telegram_chat_id' => $chat->id, 'telegram_message_id' => 9,
            'opened_at' => $sentAt(9), 'detected_at' => $sentAt(9)->addSeconds(180),
            'source' => 'operator', 'opened_by_user_id' => 1,
            'category' => 'ABUSE', 'severity' => 'medium',
            'prompted_by_classification_id' => $p9->id,
        ]);

        $this->makeMessage($chat, 10, $sentAt(10), ['original_text' => 'اعلان بسعر مخفض جدا']);
        $p10 = $this->makePrediction($chat, 10, $modelA, [
            'category' => 'SPAM_OR_AD', 'needs_moderation' => true, 'severity' => 'high',
            'route' => 'incident', 'confidence' => '0.930',
        ]);
        $i4 = ModerationIncident::forceCreate([
            'telegram_chat_id' => $chat->id, 'telegram_message_id' => 10,
            'opened_at' => $sentAt(10), 'detected_at' => $sentAt(10)->addSeconds(4),
            'source' => 'ai', 'opened_by_user_id' => null,
            'category' => 'SPAM_OR_AD', 'severity' => 'high',
            'message_classification_id' => $p10->id,
        ]);
        DB::table('moderation_actions')->insert([
            'telegram_chat_id' => $chat->id, 'action_type' => 'panel_false_positive',
            'occurred_at' => $sentAt(10)->addMinutes(30), 'panel_user_id' => 1,
            'moderation_incident_id' => $i4->id, 'note' => 'model misread it', 'detail' => json_encode([]),
        ]);

        // C4: exactly one listed, unanchored possible violation.
        $this->makeMessage($chat, 11, $sentAt(11), ['original_text' => 'اعلان ثالث']);
        $this->makePrediction($chat, 11, $modelA, [
            'category' => 'SPAM_OR_AD', 'needs_moderation' => true, 'severity' => 'low',
            'route' => 'possible_violation', 'route_reason' => 'uncertain', 'confidence' => '0.650',
        ]);

        // C5: excluded / failed / not-yet-classified.
        $this->makeMessage($chat, 12, $sentAt(12), ['original_text' => null, 'media_kind' => 'photo']);
        MessageClassificationAttempt::forceCreate([
            'telegram_chat_id' => $chat->id, 'telegram_message_id' => 12,
            'path' => 'live', 'outcome' => 'excluded', 'reason' => 'media',
        ]);

        $this->makeMessage($chat, 13, $sentAt(13), ['original_text' => 'نص فشل تصنيفه']);
        MessageClassificationAttempt::forceCreate([
            'telegram_chat_id' => $chat->id, 'telegram_message_id' => 13,
            'path' => 'live', 'outcome' => 'failed', 'reason' => 'model_timeout',
            'model_profile_id' => $modelA->id,
        ]);

        $this->makeMessage($chat, 14, $sentAt(14), ['original_text' => 'لم يصنف بعد']);

        return ['chat' => $chat, 'modelA' => $modelA, 'modelB' => $modelB, 'base' => $base];
    }

    public function test_every_figure_matches_the_hand_computed_values(): void
    {
        $this->actingAsPanelOperator();
        $scenario = $this->seedScenario();
        $chat = $scenario['chat'];
        $modelA = $scenario['modelA'];
        $modelB = $scenario['modelB'];

        $component = Livewire::test(ClassificationAccuracy::class)
            ->set('chatId', (string) $chat->id)
            ->set('periodFrom', now()->subDays(2)->toDateString())
            ->set('periodTo', now()->toDateString());

        $blocks = collect($component->instance()->blocks())->keyBy('model');
        $blockA = $blocks->get($modelA->name);
        $blockB = $blocks->get($modelB->name);

        $this->assertNotNull($blockA);
        $this->assertSame(1, $blockA['questions']['rule_kept']['classified']);
        $this->assertSame(1, $blockA['questions']['rule_kept']['judged_needs_response']);
        $this->assertSame(1, $blockA['questions']['rule_dismissed']['classified']);
        $this->assertSame(0, $blockA['questions']['rule_dismissed']['judged_needs_response']);
        $this->assertSame(1, $blockA['questions']['operator_added']['classified']);
        $this->assertSame(1, $blockA['questions']['operator_added']['judged_needs_response']);
        $this->assertSame(1, $blockA['questions']['unverified']);

        $this->assertNotNull($blockB);
        $this->assertSame(0, $blockB['questions']['rule_kept']['classified']); // never pooled with A
        $this->assertSame(1, $blockB['questions']['unverified']);

        $this->assertSame(2, $blockA['violations']['indep_flags']);
        $this->assertSame(1, $blockA['violations']['indep_agreed']);
        $this->assertSame(1, $blockA['violations']['indep_same_cat']);
        $this->assertSame(1, $blockA['violations']['prompted_flags']);
        $this->assertSame(1, $blockA['violations']['prompted_agreed']);
        $this->assertSame(1, $blockA['violations']['prompted_same_cat']);
        $this->assertSame(2, $blockA['violations']['fp_closures']);
        $this->assertSame(1, $blockA['violations']['fp_model_raised']);
        $this->assertSame(1, $blockA['violations']['model_opened']);
        $this->assertSame(1, $blockA['violations']['model_opened_fp']);
        $this->assertSame(1, $blockA['violations']['listed_now']);

        $volume = $component->instance()->volume();
        $this->assertSame(14, $volume['messages']);
        $this->assertSame(11, $volume['classified']);
        $this->assertSame(1, $volume['excluded']);
        $this->assertSame(1, $volume['failed']);
        $this->assertSame(1, $volume['not_classified_yet']);
        $this->assertSame(['media' => 1], $volume['excluded_by_reason']);
        $this->assertSame(['model_timeout' => 1], $volume['failed_by_reason']);

        $baseline = collect($component->instance()->ruleBaseline())->keyBy(
            fn (array $row) => $row['rule_version'] ?? 'null'
        );
        $this->assertSame(2, $baseline[1]['rule_opened']);
        $this->assertSame(1, $baseline[1]['rule_dismissed']);
        $this->assertSame(1, $baseline['null']['operator_added']);
    }

    public function test_never_pooled_rows_stay_apart_in_the_rendered_page(): void
    {
        $this->actingAsPanelOperator();
        $scenario = $this->seedScenario();

        Livewire::test(ClassificationAccuracy::class)
            ->set('chatId', (string) $scenario['chat']->id)
            ->set('periodFrom', now()->subDays(2)->toDateString())
            ->set('periodTo', now()->toDateString())
            ->assertSeeText($scenario['modelA']->name)
            ->assertSeeText($scenario['modelB']->name)
            ->assertSeeText('Estimates over the human labels available');
    }

    public function test_a_zero_denominator_reads_no_labelled_examples(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();

        Livewire::test(ClassificationAccuracy::class)
            ->set('chatId', (string) $chat->id)
            ->assertSeeText('No labelled examples');
    }

    public function test_no_percentage_no_average_and_no_combined_score(): void
    {
        $this->actingAsPanelOperator();
        $scenario = $this->seedScenario();

        $html = Livewire::test(ClassificationAccuracy::class)
            ->set('chatId', (string) $scenario['chat']->id)
            ->set('periodFrom', now()->subDays(2)->toDateString())
            ->set('periodTo', now()->toDateString())
            ->html();

        $this->assertStringNotContainsString('%', $html);
        $this->assertStringNotContainsIgnoringCase('average', $html);
        $this->assertStringNotContainsIgnoringCase(' avg', $html);
        $this->assertStringNotContainsIgnoringCase('composite score', $html);
    }

    private function assertStringNotContainsIgnoringCase(string $needle, string $haystack): void
    {
        $this->assertStringNotContainsString(strtolower($needle), strtolower($haystack));
    }
}
