<?php

namespace Tests\Feature;

use App\Filament\Pages\ClassificationAccuracy;
use App\Filament\Pages\PossibleViolations;
use App\Filament\Resources\Incidents\Pages\ListIncidents;
use App\Models\MessageClassification;
use App\Models\ModelProfile;
use App\Models\ModerationIncident;
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
 * T059 (US6): the Incidents list's figures table (`contracts/incident-metrics.md` §2-§4,
 * `control-panel-incidents.md` §4) — the panel renders the same numbers
 * `App\Filament\Resources\Incidents\Concerns\IncidentMetrics` computes from the identical SQL
 * `apps/ai-api`'s own copy runs (D-TG-118), the suppression reason below the sample floor,
 * "no data" for a NULL figure, a dash for a zero-denominator handled share, no detection-latency
 * column on moderator rows (P15), and the standing prohibition on any average or composite score
 * anywhere on the page (M14, D-TG-92). `DatabaseTransactions` against `injaz_ai_test`.
 */
class IncidentMetricsTest extends TestCase
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
            'title' => 'Figures Group',
            'is_monitored' => true,
        ], $overrides));
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

    private function makeMessage(TelegramChat $chat, int $messageId, \DateTimeInterface $sentAt): TelegramMessage
    {
        return TelegramMessage::forceCreate([
            'telegram_chat_id' => $chat->id,
            'message_id' => $messageId,
            'sent_at' => $sentAt,
            'is_service' => false,
            'is_from_moderator' => false,
            'original_text' => 'spam text',
            'normalized_text' => 'spam text',
            'entity_flags' => '{}',
            'source_update_id' => $this->makeCapturedUpdate($chat),
        ]);
    }

    private function makeIncident(
        TelegramChat $chat,
        TelegramMessage $message,
        \DateTimeInterface $detectedAt,
        ?int $responsibleModeratorId = null,
    ): ModerationIncident {
        return ModerationIncident::forceCreate([
            'telegram_chat_id' => $chat->id,
            'telegram_message_id' => $message->message_id,
            'opened_at' => $message->sent_at,
            'detected_at' => $detectedAt,
            'source' => 'operator',
            'opened_by_user_id' => 1,
            'category' => 'SPAM_OR_AD',
            'severity' => 'low',
            'responsible_moderator_id' => $responsibleModeratorId,
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

    private function makeClassification(
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
            'severity' => 'high',
            'confidence' => '0.930',
            'path' => 'live',
            'route' => 'incident',
            'confidence_floor' => '0.600',
            'incident_threshold' => '0.850',
            'is_current' => true,
        ], $overrides));
    }

    /**
     * TG-M5, D-TG-159: a model-opened incident (`source='ai'`) — needs an opening prediction
     * (`ck_incident_ai_link`) and no `opened_by_user_id` (`ck_incident_opener`).
     */
    private function makeModelOpenedIncident(
        TelegramChat $chat,
        TelegramMessage $message,
        MessageClassification $classification,
        \DateTimeInterface $detectedAt,
    ): ModerationIncident {
        return ModerationIncident::forceCreate([
            'telegram_chat_id' => $chat->id,
            'telegram_message_id' => $message->message_id,
            'opened_at' => $message->sent_at,
            'detected_at' => $detectedAt,
            'source' => 'ai',
            'opened_by_user_id' => null,
            'category' => 'SPAM_OR_AD',
            'severity' => 'high',
            'message_classification_id' => $classification->id,
        ]);
    }

    private function recordBan(TelegramChat $chat, TelegramMessage $message, \DateTimeInterface $occurredAt): void
    {
        $subject = TelegramUser::forceCreate([
            'tg_user_id' => random_int(10_000_000, 2_000_000_000),
            'is_bot' => false,
        ]);
        $message->forceFill(['telegram_user_id' => $subject->id])->save();

        DB::table('moderation_actions')->insert([
            'telegram_chat_id' => $chat->id,
            'action_type' => 'ban',
            'action_strength' => 'enforcement',
            'occurred_at' => $occurredAt,
            'subject_telegram_user_id' => $subject->id,
            'source_update_id' => $this->makeCapturedUpdate($chat),
            'detail' => json_encode([]),
        ]);
    }

    public function test_the_figures_table_renders_the_same_numbers_the_python_statements_compute(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();

        // Handled: resolved well within the 24h default ceiling.
        $detectedAt = now()->subDays(2);
        $message = $this->makeMessage($chat, 1, $detectedAt);
        $this->makeIncident($chat, $message, $detectedAt);
        $this->recordBan($chat, $message, (clone $detectedAt)->addHour());

        // Missed: the ceiling has passed with no resolution.
        $missedDetectedAt = now()->subDays(2);
        $missedMessage = $this->makeMessage($chat, 2, $missedDetectedAt);
        $this->makeIncident($chat, $missedMessage, $missedDetectedAt);

        Livewire::test(ListIncidents::class)
            ->assertSeeText('Figures Group')
            ->assertSeeText('2') // flagged
            ->assertSeeText('1'); // handled and missed each render as 1
    }

    public function test_p90_renders_the_suppression_reason_below_the_sample_floor(): void
    {
        $this->actingAsPanelOperator();
        config(['moderation.percentile_min_samples' => 10]);
        $chat = $this->makeChat();

        // Four detection-latency samples — below the default floor of 10.
        foreach (range(1, 4) as $index) {
            $detectedAt = now()->subDays(1)->addMinutes($index);
            $message = $this->makeMessage($chat, $index, (clone $detectedAt)->subMinutes(5));
            $this->makeIncident($chat, $message, $detectedAt);
        }

        $html = Livewire::test(ListIncidents::class)->html();
        $this->assertStringContainsString('Fewer than 10 samples', $html);
    }

    public function test_a_null_figure_renders_no_data_not_zero_seconds(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();

        // Flagged but never acknowledged, confirmed or enforced — every timing is NULL.
        $detectedAt = now()->subHours(2);
        $message = $this->makeMessage($chat, 1, $detectedAt);
        $this->makeIncident($chat, $message, $detectedAt);

        $row = collect(Livewire::test(ListIncidents::class)->instance()->figuresByGroup())
            ->firstWhere('label', 'Figures Group');

        $this->assertNotNull($row);
        $this->assertNull($row['timings']['acknowledgement']['median']);
        $this->assertSame('no data', (new ListIncidents)->humanDuration($row['timings']['acknowledgement']['median']));
    }

    public function test_a_zero_denominator_renders_the_handled_share_as_a_dash(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();

        // Within window: neither handled nor missed yet — the handled-share denominator is zero.
        $detectedAt = now()->subMinutes(5);
        $message = $this->makeMessage($chat, 1, $detectedAt);
        $this->makeIncident($chat, $message, $detectedAt);

        $row = collect(Livewire::test(ListIncidents::class)->instance()->figuresByGroup())
            ->firstWhere('label', 'Figures Group');

        $this->assertNotNull($row);
        $this->assertNull($row['handled_share']);
        $this->assertSame('—', (new ListIncidents)->shareDisplay($row['handled_share']));
    }

    public function test_moderator_rows_have_no_detection_latency_column(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $moderator = $this->makeModerator();

        $detectedAt = now()->subDays(1);
        $message = $this->makeMessage($chat, 1, $detectedAt);
        $this->makeIncident($chat, $message, $detectedAt, $moderator->id);

        $row = collect(Livewire::test(ListIncidents::class)->instance()->figuresByModerator())
            ->firstWhere('label', $moderator->display_name);

        $this->assertNotNull($row);
        $this->assertArrayNotHasKey('latency', $row);
    }

    /**
     * T066 (US6): detection latency is grouped by opener (`classification-metrics.md` C8,
     * D-TG-159) — one row for "Operator" and one for "Model", each with its own count and p90
     * suppression judged on its own sample size; every other incident figure is unchanged and
     * still counts the model-opened incident (M17: false positives, and every source, count).
     */
    public function test_detection_latency_renders_one_row_per_opener(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();

        $operatorDetectedAt = now()->subDays(1);
        $operatorMessage = $this->makeMessage($chat, 1, $operatorDetectedAt);
        $this->makeIncident($chat, $operatorMessage, $operatorDetectedAt);

        $profile = $this->makeModerationProfile();
        $aiDetectedAt = now()->subDays(1);
        $aiMessage = $this->makeMessage($chat, 2, $aiDetectedAt);
        $classification = $this->makeClassification($chat, $aiMessage, $profile);
        $this->makeModelOpenedIncident($chat, $aiMessage, $classification, $aiDetectedAt);

        $row = collect(Livewire::test(ListIncidents::class)->instance()->figuresByGroup())
            ->firstWhere('label', 'Figures Group');

        $this->assertNotNull($row);
        $this->assertSame(2, $row['flagged']); // both sources counted in every other figure
        $this->assertArrayHasKey('operator', $row['latency']);
        $this->assertArrayHasKey('ai', $row['latency']);
        $this->assertSame(1, $row['latency']['operator']['flagged']);
        $this->assertSame(1, $row['latency']['ai']['flagged']);

        Livewire::test(ListIncidents::class)
            ->assertSeeText('Operator')
            ->assertSeeText('Model');
    }

    /**
     * T078 (W4): the standing prohibition holds on every Moderation Intelligence page, not only
     * the Incidents list — Possible Violations and Classification Accuracy gain the same check.
     */
    public function test_the_page_contains_no_average_and_no_composite_score(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();

        $detectedAt = now()->subHours(1);
        $message = $this->makeMessage($chat, 1, $detectedAt);
        $this->makeIncident($chat, $message, $detectedAt);

        $profile = $this->makeModerationProfile();
        $profile->forceFill(['is_active' => true])->save();
        $listedMessage = $this->makeMessage($chat, 2, $detectedAt);
        $this->makeClassification($chat, $listedMessage, $profile, [
            'route' => 'possible_violation',
            'route_reason' => 'uncertain',
        ]);

        $htmls = [
            'Incidents' => Livewire::test(ListIncidents::class)->html(),
            'Possible Violations' => Livewire::test(PossibleViolations::class)->html(),
            'Classification Accuracy' => Livewire::test(ClassificationAccuracy::class)->html(),
        ];

        foreach ($htmls as $page => $html) {
            $this->assertStringNotContainsIgnoringCase('average', $html, $page);
            $this->assertStringNotContainsIgnoringCase(' avg', $html, $page);
            $this->assertStringNotContainsIgnoringCase('score', $html, $page);
        }
    }

    private function assertStringNotContainsIgnoringCase(string $needle, string $haystack, string $message = ''): void
    {
        $this->assertStringNotContainsString(strtolower($needle), strtolower($haystack), $message);
    }
}
