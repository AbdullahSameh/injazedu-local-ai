<?php

namespace Tests\Feature;

use App\Filament\Resources\Incidents\Pages\ListIncidents;
use App\Filament\Resources\Incidents\Pages\ViewIncident;
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
 * T053 (US5, P17, D-TG-126): the standing sentence is present on both the list and a view page
 * carrying every evidence kind; once that sentence and the "Text removed" marker are stripped,
 * no case-insensitive `delet` or `remov` substring remains anywhere on either screen (FR-020,
 * FR-070, SC-013). The membership kind is named `expulsion`, never `removal`, precisely so this
 * test can stay strict.
 */
class IncidentWordingTest extends TestCase
{
    use DatabaseTransactions;

    private const STANDING_SENTENCE = 'Telegram does not report message deletion in groups; no removal evidence is available.';

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
            'title' => 'Incident Group',
            'is_monitored' => true,
            'bot_status' => 'member',
        ]);
    }

    private function makeCapturedUpdate(TelegramChat $chat, string $updateType): int
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

    private function makeMessage(TelegramChat $chat, int $messageId): TelegramMessage
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

    private function insertAction(array $overrides): void
    {
        DB::table('moderation_actions')->insert(array_merge([
            'detail' => json_encode([]),
        ], $overrides));
    }

    /**
     * One incident carrying every evidence kind: a reaction, a direct reply (read in place, no
     * row), a ban, an expulsion, a restriction, a reversal, and every panel act.
     */
    private function makeIncidentWithEveryEvidenceKind(): ModerationIncident
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

    /**
     * The wording rule (P17) is about what the screen *says*, not the framework's own HTML
     * attributes (Livewire ships `wire:loading.remove` on plenty of markup) — so this strips tags
     * down to visible text before removing the two sentences the rule allows by name.
     */
    private function stripAllowedWords(string $html): string
    {
        $text = strip_tags($html);
        $text = str_replace(self::STANDING_SENTENCE, '', $text);

        return str_ireplace('Text removed', '', $text);
    }

    public function test_the_standing_sentence_is_present_on_the_list_and_a_full_view_page(): void
    {
        $this->actingAsPanelOperator();
        $incident = $this->makeIncidentWithEveryEvidenceKind();

        Livewire::test(ListIncidents::class)
            ->assertSeeText(self::STANDING_SENTENCE);

        Livewire::test(ViewIncident::class, ['record' => $incident->getKey()])
            ->assertSeeText(self::STANDING_SENTENCE);
    }

    public function test_no_delet_or_remov_substring_remains_on_the_list_page(): void
    {
        $this->actingAsPanelOperator();
        $this->makeIncidentWithEveryEvidenceKind();

        $html = Livewire::test(ListIncidents::class)->html();
        $cleaned = $this->stripAllowedWords($html);

        $this->assertDoesNotMatchRegularExpression('/delet/i', $cleaned);
        $this->assertDoesNotMatchRegularExpression('/remov/i', $cleaned);
    }

    public function test_no_delet_or_remov_substring_remains_on_a_view_page_with_every_evidence_kind(): void
    {
        $this->actingAsPanelOperator();
        $incident = $this->makeIncidentWithEveryEvidenceKind();

        $html = Livewire::test(ViewIncident::class, ['record' => $incident->getKey()])->html();
        $cleaned = $this->stripAllowedWords($html);

        $this->assertDoesNotMatchRegularExpression('/delet/i', $cleaned);
        $this->assertDoesNotMatchRegularExpression('/remov/i', $cleaned);
    }

    public function test_no_delet_or_remov_substring_remains_on_a_view_page_with_a_purged_anchor(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $message = $this->makeMessage($chat, 1);
        $message->forceFill(['original_text' => null, 'text_purged_at' => now()])->save();
        $incident = ModerationIncident::forceCreate([
            'telegram_chat_id' => $chat->id,
            'telegram_message_id' => $message->message_id,
            'opened_at' => $message->sent_at,
            'detected_at' => now(),
            'source' => 'operator',
            'opened_by_user_id' => 1,
            'category' => 'SPAM_OR_AD',
            'severity' => 'low',
        ]);

        $html = Livewire::test(ViewIncident::class, ['record' => $incident->getKey()])->html();
        $this->assertStringContainsString('Text removed', $html);

        $cleaned = $this->stripAllowedWords($html);
        $this->assertDoesNotMatchRegularExpression('/delet/i', $cleaned);
        $this->assertDoesNotMatchRegularExpression('/remov/i', $cleaned);
    }
}
