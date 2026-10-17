<?php

namespace Tests\Feature;

use App\Filament\Pages\LiveAttentionQueue;
use App\Filament\Resources\Incidents\Pages\ListIncidents;
use App\Filament\Resources\Incidents\Support\IncidentDisplay;
use App\Filament\Resources\Moderators\Pages\CreateModerator;
use App\Filament\Support\ModelView;
use App\Models\User;
use Illuminate\Foundation\Testing\DatabaseTransactions;
use Livewire\Livewire;
use PHPUnit\Framework\Attributes\DataProvider;
use Tests\TestCase;

/**
 * Every panel screen in Arabic (`tg-panel-bilingual-plan.md` §3-§5): rendered right to left under
 * the `panel_locale` cookie with its own Arabic title, the same screen still English without it,
 * and the wording promises the English carries — "self-reported", never a probability.
 */
class PanelArabicScreensTest extends TestCase
{
    use DatabaseTransactions;

    /** @return array<string, array{0: string, 1: string, 2: string}> path, Arabic title, English title */
    public static function screens(): array
    {
        return [
            'live attention queue' => ['/admin/live-attention-queue', 'قائمة المتابعة المباشرة', 'Live Attention Queue'],
            'incidents' => ['/admin/incidents', 'المخالفات', 'Incidents'],
            'possible violations' => ['/admin/possible-violations', 'مخالفات محتملة', 'Possible Violations'],
            'classification accuracy' => ['/admin/classification-accuracy', 'دقة التصنيف', 'Classification Accuracy'],
            'groups' => ['/admin/telegram-chats', 'المجموعات', 'Telegram Chats'],
            'moderators' => ['/admin/moderators', 'المشرفون', 'Moderators'],
            'model profiles' => ['/admin/model-profiles', 'ملفات النماذج', 'Model Profiles'],
            'users' => ['/admin/users', 'المستخدمون', 'Users'],
        ];
    }

    private function actingAsPanelOperator(): void
    {
        $this->actingAs(User::factory()->create(['is_panel_operator' => true]));
    }

    #[DataProvider('screens')]
    public function test_each_screen_renders_in_arabic_right_to_left(string $path, string $arabic, string $english): void
    {
        $this->actingAsPanelOperator();

        $this->withCookie('panel_locale', 'ar')
            ->get($path)
            ->assertOk()
            ->assertSee('dir="rtl"', false)
            ->assertSee($arabic)
            ->assertSee('ذكاء الإشراف')
            ->assertDontSee('Moderation Intelligence');
    }

    #[DataProvider('screens')]
    public function test_each_screen_stays_english_without_a_choice(string $path, string $arabic, string $english): void
    {
        $this->actingAsPanelOperator();

        $this->get($path)
            ->assertOk()
            ->assertSee('dir="ltr"', false)
            ->assertSee($english)
            ->assertDontSee($arabic);
    }

    public function test_confidence_stays_self_reported_in_arabic(): void
    {
        app()->setLocale('ar');

        $confidence = ModelView::confidence('0.950');

        $this->assertSame('ثقة يقدّرها النموذج بنفسه 0.950', $confidence);
    }

    public function test_no_arabic_entry_calls_anything_a_probability_or_a_percentage(): void
    {
        $arabic = json_decode((string) file_get_contents(lang_path('ar.json')), true, flags: JSON_THROW_ON_ERROR);

        foreach ($arabic as $english => $line) {
            $this->assertDoesNotMatchRegularExpression('/احتمال|أرجحية|نسبة مئوية/u', $line, $english);
            if (! str_contains($english, '%')) {
                $this->assertStringNotContainsString('%', $line, $english);
            }
        }
    }

    /**
     * Carbon has no Arabic short units: with Laravel's English fallback, a short duration would
     * read "20m" on an Arabic screen. Arabic gets the full words; English keeps its short form.
     */
    public function test_durations_read_in_arabic_words(): void
    {
        $this->assertSame('20m', IncidentDisplay::humanDuration(1200));
        $this->assertSame('20m', (new LiveAttentionQueue)->humanDuration(1200));
        $this->assertSame('20m', (new ListIncidents)->humanDuration(1200));

        app()->setLocale('ar');

        foreach ([
            IncidentDisplay::humanDuration(1200),
            (new LiveAttentionQueue)->humanDuration(1200),
            (new ListIncidents)->humanDuration(1200),
        ] as $duration) {
            $this->assertStringContainsString('دقيقة', $duration);
            $this->assertDoesNotMatchRegularExpression('/[A-Za-z]/', $duration);
        }
    }

    public function test_validation_messages_are_arabic(): void
    {
        $this->actingAsPanelOperator();
        app()->setLocale('ar');

        $component = Livewire::test(CreateModerator::class)
            ->fillForm(['display_name' => '', 'identity_source' => 'placeholder', 'tg_user_id' => ''])
            ->call('create')
            ->assertHasFormErrors(['display_name' => 'required']);

        $this->assertSame('حقل الاسم المعروض مطلوب.', $component->errors()->first('data.display_name'));
    }
}
