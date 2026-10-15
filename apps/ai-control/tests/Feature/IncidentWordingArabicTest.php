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
 * `IncidentWordingTest` in Arabic (`tg-panel-bilingual-plan.md` §4-§5): the same screens, the same
 * promise. Once the Arabic standing sentence is stripped, no word for deletion or removal — حذف,
 * إزالة, أُزيل — remains, with short vowels ignored so a diacritic cannot hide one.
 */
class IncidentWordingArabicTest extends TestCase
{
    use BuildsIncidentWordingFixtures;
    use DatabaseTransactions;

    private const DELETION_WORDS = '/حذف|[اأإ]زال|[اأإ]زيل/u';

    protected function setUp(): void
    {
        parent::setUp();

        app()->setLocale('ar');
    }

    private function standingSentence(): string
    {
        return __('Telegram does not report message deletion in groups; no removal evidence is available.');
    }

    private function cleaned(string $html): string
    {
        $text = preg_replace('/[\x{064B}-\x{0652}\x{0670}]/u', '', strip_tags($html));

        return str_replace(
            preg_replace('/[\x{064B}-\x{0652}\x{0670}]/u', '', $this->standingSentence()),
            '',
            $text,
        );
    }

    public function test_the_standing_sentence_is_translated(): void
    {
        $this->assertNotSame(
            'Telegram does not report message deletion in groups; no removal evidence is available.',
            $this->standingSentence(),
        );
    }

    public function test_the_standing_sentence_is_present_on_the_list_and_a_full_view_page(): void
    {
        $this->actingAsPanelOperator();
        $incident = $this->makeIncidentWithEveryEvidenceKind();

        Livewire::test(ListIncidents::class)
            ->assertSeeText($this->standingSentence())
            ->assertSeeText('المخالفات');

        Livewire::test(ViewIncident::class, ['record' => $incident->getKey()])
            ->assertSeeText($this->standingSentence());
    }

    public function test_no_deletion_word_remains_on_the_list_page(): void
    {
        $this->actingAsPanelOperator();
        $this->makeIncidentWithEveryEvidenceKind();

        $html = Livewire::test(ListIncidents::class)->html();

        $this->assertDoesNotMatchRegularExpression(self::DELETION_WORDS, $this->cleaned($html));
    }

    public function test_no_deletion_word_remains_on_a_view_page_with_every_evidence_kind(): void
    {
        $this->actingAsPanelOperator();
        $incident = $this->makeIncidentWithEveryEvidenceKind();

        $html = Livewire::test(ViewIncident::class, ['record' => $incident->getKey()])->html();

        $this->assertStringContainsString('أُخرج من المجموعة (دون حظر)', $html);
        $this->assertDoesNotMatchRegularExpression(self::DELETION_WORDS, $this->cleaned($html));
    }

    public function test_no_deletion_word_remains_on_a_view_page_with_a_purged_anchor(): void
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

        $this->assertStringContainsString(__('Text removed'), $html);
        $this->assertDoesNotMatchRegularExpression(self::DELETION_WORDS, $this->cleaned($html));
    }

    public function test_no_deletion_word_remains_on_the_possible_violations_page(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $profile = $this->makeModerationProfile();
        $message = $this->makeMessage($chat, 1);
        $message->forceFill(['original_text' => null, 'text_purged_at' => now()])->save();
        $this->makeClassification($chat, $message->fresh(), $profile);

        $html = Livewire::test(PossibleViolations::class)->html();

        $this->assertStringContainsString(__('Text removed'), $html);
        $this->assertDoesNotMatchRegularExpression(self::DELETION_WORDS, $this->cleaned($html));
    }

    public function test_no_deletion_word_remains_on_the_classification_accuracy_page(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $profile = $this->makeModerationProfile();
        $this->makeClassification($chat, $this->makeMessage($chat, 1), $profile, [
            'route' => 'incident',
            'route_reason' => null,
        ]);

        $html = Livewire::test(ClassificationAccuracy::class)->html();

        $this->assertDoesNotMatchRegularExpression(self::DELETION_WORDS, $this->cleaned($html));
    }
}
