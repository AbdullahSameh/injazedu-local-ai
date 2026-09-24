<?php

namespace Tests\Feature;

use App\Filament\Pages\LiveAttentionQueue;
use App\Models\AttentionItem;
use App\Models\Moderator;
use App\Models\TelegramChat;
use App\Models\TelegramMessage;
use App\Models\TelegramUser;
use App\Models\User;
use Illuminate\Foundation\Testing\DatabaseTransactions;
use Illuminate\Support\Facades\DB;
use Livewire\Livewire;
use Tests\TestCase;

/**
 * T071 (US6): the Live Attention Queue's figures table (`contracts/attention-metrics.md` §2-§4,
 * `control-panel-attention.md` §3) — the answered count beside every percentile, the suppression
 * reason in place of a number below the sample floor, "no data" rather than "0s" for a NULL
 * figure, and the standing prohibition on any average or composite score anywhere on the page
 * (M7, M17, M18, D-TG-92). `DatabaseTransactions` against `injaz_ai_test`, as established.
 */
class AttentionMetricsTest extends TestCase
{
    use DatabaseTransactions;

    private function actingAsPanelOperator(): void
    {
        $this->actingAs(User::factory()->create(['is_panel_operator' => true]));
    }

    private function makeChat(array $overrides = []): TelegramChat
    {
        return TelegramChat::forceCreate(array_merge([
            'chat_id' => -random_int(10_000_000, 2_000_000_000),
            'chat_type' => 'group',
            'title' => 'Figures Group',
            'is_monitored' => true,
        ], $overrides));
    }

    private function makeStudent(): TelegramUser
    {
        return TelegramUser::forceCreate([
            'tg_user_id' => random_int(10_000_000, 2_000_000_000),
            'is_bot' => false,
            'first_seen_at' => now(),
            'last_seen_at' => now(),
        ]);
    }

    private function makeModerator(string $name = 'Responsible'): Moderator
    {
        $identity = TelegramUser::forceCreate([
            'tg_user_id' => random_int(10_000_000, 2_000_000_000),
            'is_bot' => false,
            'first_seen_at' => now(),
            'last_seen_at' => now(),
        ]);

        return Moderator::create([
            'telegram_user_id' => $identity->id,
            'display_name' => $name,
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
        TelegramUser $sender,
        int $messageId,
        \DateTimeInterface $sentAt,
    ): TelegramMessage {
        return TelegramMessage::forceCreate([
            'telegram_chat_id' => $chat->id,
            'message_id' => $messageId,
            'telegram_user_id' => $sender->id,
            'sent_at' => $sentAt,
            'is_service' => false,
            'is_from_moderator' => false,
            'original_text' => 'متى الاختبار؟',
            'normalized_text' => 'متى الاختبار؟',
            'entity_flags' => '{}',
            'source_update_id' => $this->makeCapturedUpdate($chat),
        ]);
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

    private function makeAnsweredItem(
        TelegramChat $chat,
        TelegramMessage $message,
        int $moderatorId,
        int $frtSeconds,
    ): AttentionItem {
        return $this->makeItem($chat, $message, [
            'responsible_moderator_id' => $moderatorId,
            'status' => 'answered',
            'first_response_message_id' => $message->message_id + 9_000,
            'first_response_at' => (clone $message->sent_at)->addSeconds($frtSeconds),
            'first_response_kind' => 'group_message',
        ]);
    }

    public function test_the_figures_table_shows_the_answered_count_beside_every_percentile(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $student = $this->makeStudent();
        $moderator = $this->makeModerator();

        // Ten answered items — at or above the default sample floor, so p90 is not suppressed.
        foreach (range(1, 10) as $index) {
            $message = $this->makeMessage($chat, $student, $index, now()->subDays(1)->addMinutes($index));
            $this->makeAnsweredItem($chat, $message, $moderator->id, 60 * $index);
        }

        Livewire::test(LiveAttentionQueue::class)
            ->assertSet('periodFrom', now('Asia/Riyadh')->subDays(29)->toDateString())
            ->assertSet('periodTo', now('Asia/Riyadh')->toDateString())
            ->assertSeeText('Figures Group')
            ->assertSeeText('10'); // answered count rendered on the group row
    }

    public function test_p90_renders_the_suppression_reason_below_the_sample_floor(): void
    {
        $this->actingAsPanelOperator();
        config(['moderation.percentile_min_samples' => 10]);
        $chat = $this->makeChat();
        $student = $this->makeStudent();
        $moderator = $this->makeModerator();

        // Measured (contract §2 M6): four samples yield an authoritative-looking p90 — the
        // suppression exists precisely so this shape is never rendered as a number.
        foreach ([60, 120, 180, 900] as $index => $frt) {
            $message = $this->makeMessage($chat, $student, $index + 1, now()->subDays(1)->addMinutes($index));
            $this->makeAnsweredItem($chat, $message, $moderator->id, $frt);
        }

        $test = Livewire::test(LiveAttentionQueue::class);
        $test->assertSeeText('Fewer than 10 answered');
        $test->assertDontSeeText('900 seconds');
    }

    public function test_a_null_figure_renders_no_data_not_zero_seconds(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $student = $this->makeStudent();

        // Nothing answered in this group — only an open item, so `opened` > 0 but `answered`
        // (and every FRT figure) is NULL.
        $message = $this->makeMessage($chat, $student, 1, now()->subHours(2));
        $this->makeItem($chat, $message);

        // The group asked one question nobody answered: `median`/`p90`/`max` render "no data",
        // never a duration — a `0s` substring elsewhere on the page (e.g. "50s" in an unrelated
        // waiting time) would be a false pass, so this checks the group's own row directly.
        $row = collect(Livewire::test(LiveAttentionQueue::class)
            ->instance()
            ->figuresByGroup())
            ->firstWhere('label', 'Figures Group');

        $this->assertNotNull($row);
        $this->assertNull($row['median_frt']);
        $this->assertSame('no data', (new LiveAttentionQueue)->humanDuration($row['median_frt']));
    }

    public function test_the_page_contains_no_average_and_no_composite_score(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $student = $this->makeStudent();
        $moderator = $this->makeModerator();

        $message = $this->makeMessage($chat, $student, 1, now()->subHours(1));
        $this->makeAnsweredItem($chat, $message, $moderator->id, 90);

        $html = Livewire::test(LiveAttentionQueue::class)->html();

        // D-TG-92: "add an average, it is one line" is this milestone's most likely well-meaning
        // regression — checked as a standing prohibition, not a specific rendering detail.
        $this->assertStringNotContainsIgnoringCase('average', $html);
        $this->assertStringNotContainsIgnoringCase('composite', $html);
        $this->assertStringNotContainsIgnoringCase('score', $html);
    }

    private function assertStringNotContainsIgnoringCase(string $needle, string $haystack): void
    {
        $this->assertStringNotContainsString(strtolower($needle), strtolower($haystack));
    }

    public function test_the_figures_table_reflects_the_period_filter(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $student = $this->makeStudent();
        $moderator = $this->makeModerator();

        // Inside the default 30-day window.
        $recentMessage = $this->makeMessage($chat, $student, 1, now()->subDays(2));
        $this->makeAnsweredItem($chat, $recentMessage, $moderator->id, 90);

        // Far outside any reasonable window.
        $oldMessage = $this->makeMessage($chat, $student, 2, now()->subYears(2));
        $this->makeAnsweredItem($chat, $oldMessage, $moderator->id, 90);

        $test = Livewire::test(LiveAttentionQueue::class);
        $test->assertSeeText('Figures Group');

        $test->set('periodFrom', now('Asia/Riyadh')->subYears(3)->toDateString());
        $test->set('periodTo', now('Asia/Riyadh')->subYears(1)->toDateString());
        // Only the old item falls in this narrowed window — the group's row still renders with
        // a single asked question, not two.
        $test->assertSeeText('Figures Group');
    }
}
