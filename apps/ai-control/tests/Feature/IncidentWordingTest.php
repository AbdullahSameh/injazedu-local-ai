<?php

namespace Tests\Feature;

use App\Filament\Pages\ClassificationAccuracy;
use App\Filament\Pages\PossibleViolations;
use App\Filament\Resources\Incidents\Pages\ListIncidents;
use App\Filament\Resources\Incidents\Pages\ViewIncident;
use App\Models\ModerationIncident;
use Illuminate\Foundation\Testing\DatabaseTransactions;
use Livewire\Livewire;
use Tests\Feature\Concerns\BuildsIncidentWordingFixtures;
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
    use BuildsIncidentWordingFixtures;
    use DatabaseTransactions;

    private const STANDING_SENTENCE = 'Telegram does not report message deletion in groups; no removal evidence is available.';

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

    /**
     * T078 (W3): the new pages follow the same rule as every incident page — once the "Text
     * removed" marker is stripped, no `delet`/`remov` substring remains, including with a purged
     * anchor.
     */
    public function test_no_delet_or_remov_substring_remains_on_the_possible_violations_page(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $profile = $this->makeModerationProfile();
        $message = $this->makeMessage($chat, 1);
        $message->forceFill(['original_text' => null, 'text_purged_at' => now()])->save();
        $this->makeClassification($chat, $message->fresh(), $profile);

        $html = Livewire::test(PossibleViolations::class)->html();
        $this->assertStringContainsString('Text removed', $html);

        $cleaned = $this->stripAllowedWords($html);
        $this->assertDoesNotMatchRegularExpression('/delet/i', $cleaned);
        $this->assertDoesNotMatchRegularExpression('/remov/i', $cleaned);
    }

    public function test_no_delet_or_remov_substring_remains_on_the_classification_accuracy_page(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $profile = $this->makeModerationProfile();
        $this->makeClassification($chat, $this->makeMessage($chat, 1), $profile, [
            'route' => 'incident',
            'route_reason' => null,
        ]);

        $html = Livewire::test(ClassificationAccuracy::class)->html();

        $cleaned = $this->stripAllowedWords($html);
        $this->assertDoesNotMatchRegularExpression('/delet/i', $cleaned);
        $this->assertDoesNotMatchRegularExpression('/remov/i', $cleaned);
    }
}
