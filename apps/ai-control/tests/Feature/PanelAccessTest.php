<?php

namespace Tests\Feature;

use App\Models\User;
use Filament\Auth\Pages\Login;
use Illuminate\Foundation\Testing\DatabaseTransactions;
use Livewire\Livewire;
use Tests\TestCase;

class PanelAccessTest extends TestCase
{
    use DatabaseTransactions;

    public function test_unauthenticated_request_to_admin_redirects_to_sign_in(): void
    {
        $response = $this->get('/admin');

        $response->assertRedirect('/admin/login');
    }

    public function test_an_incorrect_password_establishes_no_session(): void
    {
        $user = User::factory()->create([
            'password' => bcrypt('the-correct-password'),
            'is_panel_operator' => true,
        ]);

        Livewire::test(Login::class)
            ->fillForm([
                'email' => $user->email,
                'password' => 'a-wrong-password',
            ])
            ->call('authenticate')
            ->assertHasFormErrors();

        $this->assertGuest();

        $this->get('/admin')->assertRedirect('/admin/login');
    }
}
