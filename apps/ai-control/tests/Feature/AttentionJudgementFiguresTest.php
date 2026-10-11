<?php

namespace Tests\Feature;

use App\Filament\Pages\ClassificationAccuracy;
use App\Models\AttentionItem;
use App\Models\ModelProfile;
use App\Models\TelegramChat;
use App\Models\TelegramMessage;
use App\Models\TelegramUser;
use App\Models\User;
use Illuminate\Foundation\Testing\DatabaseTransactions;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;
use Livewire\Livewire;
use Tests\TestCase;

/**
 * TG-M5.3 (`specs/011-tg-m5-3-attention-judgement/contracts/attention-metrics.md` §2 C10a-C10c, §3):
 * the attention judgement's coverage, intents and timeliness on the Classification Accuracy page —
 * the same hand-computed scenario as `apps/ai-api/tests/moderation/attention_judgement/
 * test_metrics_attention.py`, read through the page, which runs the contract's SQL and nothing else.
 *
 * In one group, ten messages: 1-3 and 7 judged live (model A `asking` at exactly the 90 s gap,
 * `discussion` at 91 s, `asking` at 5 s after a failure; model B `informing` at 10 s), 10 judged by
 * catch-up, 4-5 excluded (`rule_opens`, `moderator`), 6 failed twice (latest `model_truncated`), 8-9
 * nothing. C10a: 10 = 5 + 2 + 1 + 2. C10b: model A judged 3, asking 2, discussion 1, on time 2 / 3;
 * model B judged 1, informing 1, on time 1 / 1.
 *
 * C10c (M30-M32) has its own scenario, the same as `test_metrics_attention.py`'s C10c one: eight
 * operator-added items, by their anchor's attention status and by whether the anchor's sender has
 * a same-thread neighbour within the gap (see `test_operator_added_items_…` below).
 */
class AttentionJudgementFiguresTest extends TestCase
{
    use DatabaseTransactions;

    private function makeChat(): TelegramChat
    {
        return TelegramChat::forceCreate([
            'chat_id' => -random_int(10_000_000, 2_000_000_000),
            'chat_type' => 'group',
            'title' => 'Attention Judgement Figures Group',
            'is_monitored' => true,
        ]);
    }

    /**
     * @param  array<string, mixed>  $overrides  `telegram_user_id`, `sender_chat_id`, `message_thread_id`
     */
    private function makeMessage(TelegramChat $chat, int $messageId, Carbon $sentAt, array $overrides = []): TelegramMessage
    {
        $updateId = DB::table('telegram_updates')->insertGetId([
            'bot_id' => random_int(10_000_000, 2_000_000_000),
            'update_id' => random_int(10_000_000, 2_000_000_000),
            'update_type' => 'message',
            'chat_id' => $chat->chat_id,
            'payload' => json_encode(['message' => []]),
            'received_at' => now(),
        ]);

        return TelegramMessage::forceCreate(array_merge([
            'telegram_chat_id' => $chat->id,
            'message_id' => $messageId,
            'sent_at' => $sentAt,
            'is_service' => false,
            'is_from_moderator' => false,
            'original_text' => 'في محاضرة بكرة',
            'normalized_text' => 'في محاضره بكره',
            'entity_flags' => '{}',
            'source_update_id' => $updateId,
        ], $overrides));
    }

    private function makeProfile(string $label): ModelProfile
    {
        return ModelProfile::forceCreate([
            'name' => "test-attention-{$label}-".random_int(1, 1_000_000),
            'provider' => 'fake',
            'model' => "fake-attention-{$label}",
            'role' => 'attention',
            'params' => json_encode([]),
            'is_active' => false,
        ]);
    }

    private function judge(
        TelegramChat $chat,
        int $messageId,
        ModelProfile $profile,
        string $intent,
        bool $needsResponse,
        Carbon $createdAt,
        string $path = 'live',
    ): void {
        DB::table('message_attention_judgements')->insert([
            'telegram_chat_id' => $chat->id,
            'telegram_message_id' => $messageId,
            'model_profile_id' => $profile->id,
            'prompt_version' => 'attention_test',
            'intent' => $intent,
            // A stored value, given literally per row: the derivation has one definition, in
            // Python (S2, N2), and no PHP helper restates it. C10 never reads this column.
            'needs_response' => $needsResponse,
            'path' => $path,
            'is_current' => true,
            'created_at' => $createdAt,
        ]);
    }

    private function attempt(
        TelegramChat $chat,
        int $messageId,
        string $outcome,
        string $reason,
        Carbon $createdAt,
        ?ModelProfile $profile = null,
    ): void {
        DB::table('message_attention_attempts')->insert([
            'telegram_chat_id' => $chat->id,
            'telegram_message_id' => $messageId,
            'path' => 'live',
            'outcome' => $outcome,
            'reason' => $reason,
            'model_profile_id' => $profile?->id,
            'created_at' => $createdAt,
        ]);
    }

    public function test_coverage_intents_and_timeliness_are_the_contracts_numbers(): void
    {
        $this->actingAs(User::factory()->create(['is_panel_operator' => true]));
        $chat = $this->makeChat();
        $otherChat = $this->makeChat();
        $modelA = $this->makeProfile('a');
        $modelB = $this->makeProfile('b');

        $base = now()->subHours(3)->startOfMinute();
        $sent = fn (int $n): Carbon => $base->copy()->addMinutes($n);

        for ($n = 1; $n <= 10; $n++) {
            $this->makeMessage($chat, $n, $sent($n));
        }
        $this->makeMessage($otherChat, 12, $sent(12));

        $this->judge($chat, 1, $modelA, 'asking', true, $sent(1)->addSeconds(90));
        $this->judge($chat, 2, $modelA, 'discussion', false, $sent(2)->addSeconds(91));
        $this->judge($chat, 3, $modelB, 'informing', false, $sent(3)->addSeconds(10));
        $this->attempt($chat, 4, 'excluded', 'rule_opens', $sent(4)->addSecond());
        $this->attempt($chat, 5, 'excluded', 'moderator', $sent(5)->addSecond());
        $this->attempt($chat, 6, 'failed', 'provider_unreachable', $sent(6)->addSeconds(30), $modelA);
        $this->attempt($chat, 6, 'failed', 'model_truncated', $sent(6)->addSeconds(60), $modelA);
        $this->attempt($chat, 7, 'failed', 'model_timeout', $sent(7)->addSeconds(2), $modelA);
        $this->judge($chat, 7, $modelA, 'asking', true, $sent(7)->addSeconds(5));
        $this->judge($chat, 10, $modelA, 'social', false, $sent(10)->addSeconds(5), 'catch_up');
        $this->judge($otherChat, 12, $modelA, 'asking', true, $sent(12)->addSeconds(5));

        $component = Livewire::test(ClassificationAccuracy::class)
            ->set('chatId', (string) $chat->id)
            ->set('periodFrom', now()->subDays(2)->toDateString())
            ->set('periodTo', now()->toDateString());
        $page = $component->instance();

        // C10a (M26): the four outcomes partition the messages; exclusions by reason, failures by
        // the latest reason.
        $this->assertSame([
            'messages' => 10,
            'judged' => 5,
            'excluded' => 2,
            'failed' => 1,
            'not_judged_yet' => 2,
            'excluded_by_reason' => ['moderator' => 1, 'rule_opens' => 1],
            'failed_by_reason' => ['model_truncated' => 1],
        ], $this->sortedBreakdowns($page->attentionVolume()));

        // C10b (M28): one block per (model, attention instruction), live only.
        $blocks = collect($page->attentionBlocks())->keyBy('model');
        $this->assertCount(2, $blocks);
        $this->assertSame([
            'judged' => 3, 'asking' => 2, 'discussion' => 1, 'informing' => 0,
            'social' => 0, 'offering' => 0, 'other' => 0, 'on_time' => 2,
        ], $blocks[$modelA->name]['judgements']);
        $this->assertSame([
            'judged' => 1, 'asking' => 0, 'discussion' => 0, 'informing' => 1,
            'social' => 0, 'offering' => 0, 'other' => 0, 'on_time' => 1,
        ], $blocks[$modelB->name]['judgements']);

        $html = $component->html();
        $this->assertStringContainsString('Attention judgements: what happened to every message', $html);
        $this->assertStringContainsString("{$modelA->name} · attention_test", $html);
        $this->assertStringContainsString('asking 2 · discussion 1 · informing 0 · social 0 · offering 0 · other 0', $html);
        $this->assertStringContainsString('asking 0 · discussion 0 · informing 1 · social 0 · offering 0 · other 0', $html);
        $this->assertStringContainsString('Judged on time: 2 / 3', $html);
        $this->assertStringContainsString('Judged on time: 1 / 1', $html);
        $this->assertStringContainsString('rule_opens:1', $html);
        $this->assertStringContainsString('model_truncated:1', $html);
        $this->assertStringNotContainsString('%', $html);
    }

    public function test_a_period_with_no_judgements_has_no_attention_block(): void
    {
        $this->actingAs(User::factory()->create(['is_panel_operator' => true]));
        $chat = $this->makeChat();
        $this->makeMessage($chat, 1, now()->subHours(3));

        $component = Livewire::test(ClassificationAccuracy::class)
            ->set('chatId', (string) $chat->id)
            ->set('periodFrom', now()->subDays(2)->toDateString())
            ->set('periodTo', now()->toDateString());
        $page = $component->instance();

        // M22: a model with no judgements has no block; M27: unjudged messages read "not judged yet".
        $this->assertCount(0, $page->attentionBlocks());
        $this->assertSame(1, $page->attentionVolume()['not_judged_yet']);
        $this->assertStringContainsString('Attention judgements: what happened to every message', $component->html());
    }

    private function makeMember(): TelegramUser
    {
        return TelegramUser::forceCreate([
            'tg_user_id' => random_int(10_000_000, 2_000_000_000),
            'is_bot' => false,
            'first_seen_at' => now(),
            'last_seen_at' => now(),
        ]);
    }

    private function operatorItem(TelegramChat $chat, int $messageId, Carbon $openedAt, string $source = 'operator'): void
    {
        AttentionItem::forceCreate([
            'telegram_chat_id' => $chat->id,
            'telegram_message_id' => $messageId,
            'opened_at' => $openedAt,
            'source' => $source,
            'rule_version' => $source === 'rule' ? 1 : null,
            'status' => 'open',
        ]);
    }

    /**
     * C10c (M30-M32): anchors ten minutes apart, all from one member apart from #6, a channel
     * posting as itself. 1 `asking`, alone; 2 `asking`, a same-thread neighbour at exactly +90 s;
     * 3 `discussion`, one at +91 s; 4 excluded `rule_opens`, one at exactly -90 s; 5 failed, one in
     * another thread; 6 nothing, a `sender_chat` anchor beside the same channel's message; 7
     * nothing, a same-topic neighbour at +30 s; 8 failed then `discussion`, alone. Not counted: a
     * rule item (#9), an operator item opened before the period (#10), and one in another group.
     */
    public function test_operator_added_items_are_split_by_anchor_status_and_burst_size(): void
    {
        $this->actingAs(User::factory()->create(['is_panel_operator' => true]));
        $chat = $this->makeChat();
        $otherChat = $this->makeChat();
        $model = $this->makeProfile('c10c');
        $member = $this->makeMember();
        $channel = -random_int(10_000_000, 2_000_000_000);

        $base = now()->subHours(3)->startOfMinute();
        $sent = fn (int $n): Carbon => $base->copy()->addMinutes(10 * $n);
        $byMember = ['telegram_user_id' => $member->id];

        $this->makeMessage($chat, 1, $sent(1), $byMember);
        $this->judge($chat, 1, $model, 'asking', true, $sent(1)->addSeconds(5));

        $this->makeMessage($chat, 2, $sent(2), $byMember);
        $this->makeMessage($chat, 102, $sent(2)->addSeconds(90), $byMember);
        $this->judge($chat, 2, $model, 'asking', true, $sent(2)->addSeconds(5));

        $this->makeMessage($chat, 3, $sent(3), $byMember);
        $this->makeMessage($chat, 103, $sent(3)->addSeconds(91), $byMember);
        $this->judge($chat, 3, $model, 'discussion', false, $sent(3)->addSeconds(5));

        $this->makeMessage($chat, 4, $sent(4), $byMember);
        $this->makeMessage($chat, 104, $sent(4)->subSeconds(90), $byMember);
        $this->attempt($chat, 4, 'excluded', 'rule_opens', $sent(4)->addSeconds(2));

        $this->makeMessage($chat, 5, $sent(5), $byMember);
        $this->makeMessage($chat, 105, $sent(5)->addSeconds(30), $byMember + ['message_thread_id' => 7]);
        $this->attempt($chat, 5, 'failed', 'model_truncated', $sent(5)->addSeconds(2), $model);

        $this->makeMessage($chat, 6, $sent(6), ['sender_chat_id' => $channel]);
        $this->makeMessage($chat, 106, $sent(6)->addSeconds(10), ['sender_chat_id' => $channel]);

        $this->makeMessage($chat, 7, $sent(7), $byMember + ['message_thread_id' => 7]);
        $this->makeMessage($chat, 107, $sent(7)->addSeconds(30), $byMember + ['message_thread_id' => 7]);

        $this->makeMessage($chat, 8, $sent(8), $byMember);
        $this->attempt($chat, 8, 'failed', 'model_timeout', $sent(8)->addSeconds(2), $model);
        $this->judge($chat, 8, $model, 'discussion', false, $sent(8)->addSeconds(5));

        $this->makeMessage($chat, 9, $sent(9), $byMember);
        $this->judge($chat, 9, $model, 'asking', true, $sent(9)->addSeconds(5));
        $this->makeMessage($chat, 10, $sent(10), $byMember);
        $this->makeMessage($otherChat, 11, $sent(11), $byMember);

        for ($n = 1; $n <= 8; $n++) {
            $this->operatorItem($chat, $n, $sent($n));
        }
        $this->operatorItem($chat, 9, $sent(9), 'rule');
        $this->operatorItem($chat, 10, now()->subDays(10));
        $this->operatorItem($otherChat, 11, $sent(11));

        $component = Livewire::test(ClassificationAccuracy::class)
            ->set('chatId', (string) $chat->id)
            ->set('periodFrom', now()->subDays(2)->toDateString())
            ->set('periodTo', now()->toDateString());

        $this->assertSame([
            ['anchor_status' => 'judged_asking', 'single' => 1, 'multi' => 1],
            ['anchor_status' => 'judged_discussion', 'single' => 2, 'multi' => 0],
            ['anchor_status' => 'excluded_rule_opens', 'single' => 0, 'multi' => 1],
            ['anchor_status' => 'failed', 'single' => 1, 'multi' => 0],
            ['anchor_status' => 'none', 'single' => 1, 'multi' => 1],
        ], $component->instance()->attentionOperatorAdded());

        $html = $component->html();
        $this->assertStringContainsString('Operator-added items, by anchor status and burst size', $html);
        $this->assertStringContainsString('review multi-message rows by hand', $html);
        $this->assertStringContainsString('excluded_rule_opens', $html);
        $this->assertStringNotContainsString('%', $html);
    }

    public function test_a_period_with_no_operator_added_items_says_so(): void
    {
        $this->actingAs(User::factory()->create(['is_panel_operator' => true]));
        $chat = $this->makeChat();
        $this->makeMessage($chat, 1, now()->subHours(3));

        $component = Livewire::test(ClassificationAccuracy::class)
            ->set('chatId', (string) $chat->id)
            ->set('periodFrom', now()->subDays(2)->toDateString())
            ->set('periodTo', now()->toDateString());

        $this->assertSame([], $component->instance()->attentionOperatorAdded());
        $this->assertStringContainsString('No operator-added items in this period.', $component->html());
    }

    /**
     * @param  array<string, mixed>  $volume
     * @return array<string, mixed>
     */
    private function sortedBreakdowns(array $volume): array
    {
        ksort($volume['excluded_by_reason']);
        ksort($volume['failed_by_reason']);

        return $volume;
    }
}
