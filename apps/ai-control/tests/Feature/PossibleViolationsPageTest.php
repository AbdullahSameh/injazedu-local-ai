<?php

namespace Tests\Feature;

use App\Filament\Pages\PossibleViolations;
use App\Models\MessageClassification;
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
 * T058 (US5): rows are exactly `classification-metrics.md` C4 — live `possible_violation`
 * predictions whose message anchors no incident; every other route is never listed, and an
 * anchored one is never listed; "Why listed" reads **Uncertain** / **Inconsistent** from
 * `route_reason`; the **Flag message** action requires category and severity, opens an operator
 * incident recorded as list-prompted, and the row disappears; no dismiss, relabel or bulk action
 * exists; the empty state and the no-active-model state render §3 V4's words; Arabic text carries
 * `dir="auto"` (`control-panel-classification.md` §3, FR-041...FR-045, SC-018).
 */
class PossibleViolationsPageTest extends TestCase
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
            'title' => 'Possible Violations Group',
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
            'original_text' => 'نص اعلان مشكوك فيه',
            'normalized_text' => 'نص اعلان مشكوك فيه',
            'entity_flags' => '{}',
            'source_update_id' => $this->makeCapturedUpdate($chat),
        ], $overrides));
    }

    private function makeModerationProfile(bool $active = true): ModelProfile
    {
        return ModelProfile::forceCreate([
            'name' => 'test-moderation-'.random_int(1, 1_000_000),
            'provider' => 'ollama',
            'base_url' => 'http://host.docker.internal:11434/v1',
            'model' => 'gemma4:e2b-it-qat',
            'role' => 'moderation',
            'params' => json_encode(['reasoning_effort' => 'none']),
            'is_active' => $active,
        ]);
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
            'confidence' => '0.720',
            'path' => 'live',
            'route' => 'possible_violation',
            'route_reason' => 'uncertain',
            'confidence_floor' => '0.600',
            'incident_threshold' => '0.850',
            'is_current' => true,
        ], $overrides));
    }

    public function test_rows_are_exactly_unanchored_live_possible_violation_predictions(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();

        $listed = $this->makeClassification($chat, $this->makeMessage($chat, 1));

        $reviewRoute = $this->makeClassification($chat, $this->makeMessage($chat, 2), [
            'route' => 'review',
            'route_reason' => null,
            'confidence' => '0.300',
        ]);
        $noneRoute = $this->makeClassification($chat, $this->makeMessage($chat, 3), [
            'category' => 'CHITCHAT',
            'needs_moderation' => false,
            'route' => 'none',
            'route_reason' => null,
        ]);
        $incidentRoute = $this->makeClassification($chat, $this->makeMessage($chat, 4), [
            'severity' => 'high',
            'confidence' => '0.930',
            'route' => 'incident',
            'route_reason' => null,
        ]);
        $catchUpRoute = $this->makeClassification($chat, $this->makeMessage($chat, 5), [
            'path' => 'catch_up',
            'route' => 'measurement_only',
            'route_reason' => null,
            'confidence_floor' => null,
            'incident_threshold' => null,
        ]);

        $anchoredMessage = $this->makeMessage($chat, 6);
        $anchored = $this->makeClassification($chat, $anchoredMessage);
        ModerationIncident::forceCreate([
            'telegram_chat_id' => $chat->id,
            'telegram_message_id' => $anchoredMessage->message_id,
            'opened_at' => $anchoredMessage->sent_at,
            'detected_at' => now(),
            'source' => 'operator',
            'opened_by_user_id' => 1,
            'category' => 'SPAM_OR_AD',
            'severity' => 'low',
        ]);

        Livewire::test(PossibleViolations::class)
            ->assertCanSeeTableRecords([$listed])
            ->assertCanNotSeeTableRecords([
                $reviewRoute,
                $noneRoute,
                $incidentRoute,
                $catchUpRoute,
                $anchored,
            ]);
    }

    public function test_why_listed_reads_uncertain_or_inconsistent_from_route_reason(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();

        $this->makeClassification($chat, $this->makeMessage($chat, 1), ['route_reason' => 'uncertain']);
        $this->makeClassification($chat, $this->makeMessage($chat, 2), ['route_reason' => 'inconsistent']);

        Livewire::test(PossibleViolations::class)
            ->assertSeeText('Uncertain')
            ->assertSeeText('Inconsistent');
    }

    public function test_flag_message_requires_category_and_severity_opens_a_list_prompted_incident_and_removes_the_row(): void
    {
        $operator = $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $message = $this->makeMessage($chat, 1);
        $classification = $this->makeClassification($chat, $message);

        Livewire::test(PossibleViolations::class)
            ->callTableAction('flag_message', $classification->id, data: [
                'category' => null,
                'severity' => null,
            ])
            ->assertHasTableActionErrors(['category', 'severity']);

        Livewire::test(PossibleViolations::class)
            ->callTableAction('flag_message', $classification->id, data: [
                'category' => 'SPAM_OR_AD',
                'severity' => 'low',
            ])
            ->assertHasNoTableActionErrors();

        $incident = ModerationIncident::query()
            ->where('telegram_chat_id', $chat->id)
            ->where('telegram_message_id', $message->message_id)
            ->firstOrFail();
        $this->assertSame('operator', $incident->source);
        $this->assertSame($operator->id, $incident->opened_by_user_id);
        $this->assertSame($classification->id, $incident->prompted_by_classification_id);
        $this->assertNull($incident->message_classification_id);

        Livewire::test(PossibleViolations::class)
            ->assertCanNotSeeTableRecords([$classification]);
    }

    public function test_no_dismiss_relabel_or_bulk_action_exists(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $classification = $this->makeClassification($chat, $this->makeMessage($chat, 1));

        $test = Livewire::test(PossibleViolations::class);

        foreach (['dismiss', 'relabel', 'not_a_violation', 'delete'] as $name) {
            $test->assertTableActionDoesNotExist($name);
        }
        $this->assertSame([], $test->instance()->getTable()->getBulkActions());
        $this->assertNotNull($classification);
    }

    public function test_the_empty_state_renders_v4s_words(): void
    {
        $this->actingAsPanelOperator();
        $this->makeModerationProfile();

        Livewire::test(PossibleViolations::class)
            ->assertSeeText('Nothing listed')
            ->assertSeeText(
                'A message appears here when the model thinks it may need moderation but is not '
                    .'confident or consistent enough to open an incident.'
            );
    }

    public function test_the_no_active_model_state_renders_its_own_words(): void
    {
        $this->actingAsPanelOperator();
        $this->makeModerationProfile(active: false);

        Livewire::test(PossibleViolations::class)
            ->assertSeeText('No classification model is active');
    }

    public function test_arabic_message_text_carries_dir_auto(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $this->makeClassification($chat, $this->makeMessage($chat, 1, [
            'original_text' => 'نص اعلان مشكوك فيه',
        ]));

        Livewire::test(PossibleViolations::class)
            ->assertSee('dir="auto"', false);
    }
}
