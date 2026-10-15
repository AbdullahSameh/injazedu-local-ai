<?php

namespace Tests\Feature;

use App\Http\Middleware\SetPanelLocale;
use App\Models\User;
use Illuminate\Foundation\Testing\DatabaseTransactions;
use Livewire\Livewire;
use Tests\TestCase;

/**
 * The bilingual panel (`docs/plan/telegram/tg-panel-bilingual-plan.md` §1): English and LTR by
 * default, Arabic and RTL once chosen from the user menu, the choice kept in the `panel_locale`
 * cookie and applied to Livewire's own update requests too.
 */
class PanelLocaleTest extends TestCase
{
    use DatabaseTransactions;

    private function actingAsPanelOperator(): void
    {
        $this->actingAs(User::factory()->create(['is_panel_operator' => true]));
    }

    public function test_the_panel_is_english_and_left_to_right_by_default(): void
    {
        $this->actingAsPanelOperator();

        $this->get('/admin')
            ->assertOk()
            ->assertSee('lang="en"', false)
            ->assertSee('dir="ltr"', false)
            ->assertSee('العربية')
            ->assertSee(route('filament.admin.locale', ['locale' => 'ar']), false);
    }

    public function test_choosing_arabic_remembers_it_and_returns_to_the_same_page(): void
    {
        $this->actingAsPanelOperator();

        $this->from('/admin/incidents')
            ->post(route('filament.admin.locale', ['locale' => 'ar']))
            ->assertRedirect('/admin/incidents')
            ->assertCookie('panel_locale', 'ar');
    }

    public function test_the_switch_never_returns_to_another_site(): void
    {
        $this->actingAsPanelOperator();

        $this->withHeader('referer', 'https://elsewhere.example/phish')
            ->post(route('filament.admin.locale', ['locale' => 'ar']))
            ->assertRedirect(url('/admin'));
    }

    public function test_an_arabic_choice_renders_the_panel_right_to_left_in_arabic(): void
    {
        $this->actingAsPanelOperator();

        $this->withCookie('panel_locale', 'ar')
            ->get('/admin')
            ->assertOk()
            ->assertSee('lang="ar"', false)
            ->assertSee('dir="rtl"', false)
            ->assertSee('تسجيل الخروج')
            ->assertSee('English');
    }

    public function test_an_unsupported_locale_cannot_be_chosen(): void
    {
        $this->actingAsPanelOperator();

        $this->post('/admin/locale/fr')->assertNotFound();
    }

    public function test_a_guest_cannot_choose_a_locale(): void
    {
        $this->post('/admin/locale/ar')->assertRedirect('/admin/login');
    }

    public function test_an_unknown_cookie_value_falls_back_to_english(): void
    {
        $this->actingAsPanelOperator();

        $this->withCookie('panel_locale', 'fr')
            ->get('/admin')
            ->assertOk()
            ->assertSee('lang="en"', false)
            ->assertSee('dir="ltr"', false);
    }

    public function test_the_login_page_follows_the_remembered_choice(): void
    {
        $this->withCookie('panel_locale', 'ar')
            ->get('/admin/login')
            ->assertOk()
            ->assertSee('dir="rtl"', false);
    }

    public function test_livewire_updates_keep_the_chosen_locale(): void
    {
        $this->assertContains(SetPanelLocale::class, Livewire::getPersistentMiddleware());
    }
}
