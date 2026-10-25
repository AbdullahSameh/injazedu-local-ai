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
 * TG-M5.3, Story 1 (`specs/011-tg-m5-3-attention-judgement/contracts/dismissal-reasons.md` K5-K12,
 * SC-301): on one hand-computed scenario with dismissals of every reason, every existing dismissal
 * count keeps its value, each per-reason breakdown sums to its count, and the page never describes
 * all dismissals as "not a real question".
 *
 * The scenario, in one group:
 * - **Rule items** (`rule_version = 1`): dismissed as `not_a_question`, `member_discussion`,
 *   `message_removed`, operator free text ("spam bot") and no reason, plus one answered. Rule-opened
 *   6, rule-dismissed 5, breakdown 1 · 1 · 1 · 2, precision 1 / 6.
 * - **TG-M5.1 model items** (`source = 'ai'`, linked to the classification that opened them):
 *   dismissed as `member_discussion` and `message_removed`, plus one open. Opened 3, dismissed 2,
 *   breakdown 0 · 1 · 1 · 0.
 */
class DismissalBreakdownTest extends TestCase
{
    use DatabaseTransactions;

    private int $nextMessageId = 1;

    private function makeChat(): TelegramChat
    {
        return TelegramChat::forceCreate([
            'chat_id' => -random_int(10_000_000, 2_000_000_000),
            'chat_type' => 'group',
            'title' => 'Dismissal Breakdown Group',
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

    /**
     * One item on its own new message. A model item is linked to the classification that opened
     * it; an answered item to a reply message one minute later.
     */
    private function makeItem(
        TelegramChat $chat,
        string $source,
        string $status,
        ?string $closeReason = null,
        ?ModelProfile $profile = null,
    ): AttentionItem {
        $messageId = $this->nextMessageId++;
        $sentAt = now()->subHours(3)->addMinutes($messageId);
        $this->makeMessage($chat, $messageId, $sentAt);

        $classificationId = null;
        if ($profile !== null) {
            $classificationId = MessageClassification::forceCreate([
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
            ])->id;
        }

        $answered = $status === 'answered';
        if ($answered) {
            $this->makeMessage($chat, $messageId + 1000, $sentAt->copy()->addMinute());
        }
        $dismissed = $status === 'dismissed';

        return AttentionItem::forceCreate([
            'telegram_chat_id' => $chat->id,
            'telegram_message_id' => $messageId,
            'opened_at' => $sentAt,
            'source' => $source,
            'rule_version' => $source === 'rule' ? 1 : null,
            'message_classification_id' => $classificationId,
            'status' => $status,
            'first_response_message_id' => $answered ? $messageId + 1000 : null,
            'first_response_at' => $answered ? $sentAt->copy()->addMinute() : null,
            'first_response_kind' => $answered ? 'direct_reply' : null,
            'close_reason' => $closeReason,
            'closed_at' => $dismissed ? $sentAt->copy()->addMinutes(5) : null,
        ]);
    }

    public function test_every_dismissal_count_is_unchanged_and_each_breakdown_sums_to_it(): void
    {
        $this->actingAs(User::factory()->create(['is_panel_operator' => true]));
        $chat = $this->makeChat();
        $profile = ModelProfile::forceCreate([
            'name' => 'test-dismissal-breakdown-'.random_int(1, 1_000_000),
            'provider' => 'fake',
            'model' => 'fake-dismissal-breakdown',
            'role' => 'moderation',
            'params' => json_encode([]),
            'is_active' => false,
        ]);

        $this->makeItem($chat, 'rule', 'dismissed', 'not_a_question');
        $this->makeItem($chat, 'rule', 'dismissed', 'member_discussion');
        $this->makeItem($chat, 'rule', 'dismissed', 'message_removed');
        $this->makeItem($chat, 'rule', 'dismissed', 'spam bot');
        $this->makeItem($chat, 'rule', 'dismissed', null);
        $this->makeItem($chat, 'rule', 'answered');

        $this->makeItem($chat, 'ai', 'dismissed', 'member_discussion', $profile);
        $this->makeItem($chat, 'ai', 'dismissed', 'message_removed', $profile);
        $this->makeItem($chat, 'ai', 'open', null, $profile);

        $component = Livewire::test(ClassificationAccuracy::class)
            ->set('chatId', (string) $chat->id)
            ->set('periodFrom', now('Asia/Riyadh')->subDays(2)->toDateString())
            ->set('periodTo', now('Asia/Riyadh')->toDateString());
        $page = $component->instance();

        // C7 (K7): the existing columns keep their values; the four parts are exact and sum.
        $baseline = $page->ruleBaseline();
        $this->assertCount(1, $baseline);
        $row = $baseline->first();
        $this->assertSame([
            'rule_version' => 1,
            'rule_opened' => 6,
            'rule_dismissed' => 5,
            'operator_added' => 0,
            'dismissed_not_a_question' => 1,
            'dismissed_member_discussion' => 1,
            'dismissed_member_answered' => 0,
            'dismissed_message_removed' => 1,
            'dismissed_other' => 2,
        ], $row);
        $this->assertSame(
            $row['rule_dismissed'],
            $row['dismissed_not_a_question'] + $row['dismissed_member_discussion'] + $row['dismissed_member_answered']
                + $row['dismissed_message_removed'] + $row['dismissed_other'],
        );
        // Precision is the unchanged `1 − rule_dismissed ÷ rule_opened`, read as kept / opened.
        $this->assertSame('1 / 6', $page->ratio($row['rule_opened'] - $row['rule_dismissed'], $row['rule_opened']));

        // C9 (K8): `dismissed` is unchanged, and the four parts are exact and sum to it.
        $block = collect($page->blocks())->firstWhere('model', $profile->name);
        $this->assertNotNull($block);
        $questions = $block['model_questions'];
        $this->assertSame([
            'opened' => 3,
            'dismissed' => 2,
            'kept' => 1,
            'answered' => 0,
            'unanswered' => 1,
            'dismissed_not_a_question' => 0,
            'dismissed_member_discussion' => 1,
            'dismissed_member_answered' => 0,
            'dismissed_message_removed' => 1,
            'dismissed_other' => 0,
        ], $questions);
        $this->assertSame(
            $questions['dismissed'],
            $questions['dismissed_not_a_question'] + $questions['dismissed_member_discussion'] + $questions['dismissed_member_answered']
                + $questions['dismissed_message_removed'] + $questions['dismissed_other'],
        );

        // K11, K12: the wording, and counts only.
        $html = $component->html();
        $this->assertStringContainsString('Rule-dismissed (any reason)', $html);
        $this->assertStringContainsString('not a real question 1 · member discussion 1 · answered by a member 0 · message removed 1 · other 2', $html);
        $this->assertStringContainsString('1 / 6', $html);
        $this->assertStringContainsString('Model-opened, dismissed (any reason): 2 / 3', $html);
        $this->assertStringContainsString('not a real question 0 · member discussion 1 · answered by a member 0 · message removed 1 · other 0', $html);
        $this->assertStringNotContainsString('dismissed as not a real question', $html);
        $this->assertStringNotContainsString('%', $html);
    }
}
