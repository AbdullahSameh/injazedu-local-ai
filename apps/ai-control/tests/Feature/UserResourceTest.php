<?php

namespace Tests\Feature;

use App\Filament\Resources\Users\Pages\CreateUser;
use App\Filament\Resources\Users\Pages\EditUser;
use App\Filament\Resources\Users\Pages\ListUsers;
use App\Models\User;
use Filament\Auth\Pages\Login;
use Illuminate\Foundation\Testing\DatabaseTransactions;
use Illuminate\Support\Facades\Auth;
use Illuminate\Support\Facades\Hash;
use Livewire\Livewire;
use Tests\TestCase;

/**
 * `docs/plan/side/panel-users-and-sorting-plan.md` §3: panel accounts are added and edited from
 * the panel; the password is stored only as a hash and kept when left blank; an operator cannot
 * switch off their own access; access off means the panel refuses the account; nothing is
 * deletable.
 */
class UserResourceTest extends TestCase
{
    use DatabaseTransactions;

    private const PASSWORD = 'a-long-enough-passphrase-42';

    private function actingAsPanelOperator(): User
    {
        $user = User::factory()->create(['is_panel_operator' => true]);
        $this->actingAs($user);

        return $user;
    }

    private function uniqueEmail(): string
    {
        return 'operator-'.bin2hex(random_bytes(6)).'@example.test';
    }

    public function test_the_list_loads_and_shows_accounts(): void
    {
        $me = $this->actingAsPanelOperator();

        $this->get('/admin/users')->assertOk();
        Livewire::test(ListUsers::class)->assertCanSeeTableRecords([$me]);
    }

    public function test_a_created_account_stores_a_hash_and_can_sign_in(): void
    {
        $this->actingAsPanelOperator();
        $email = $this->uniqueEmail();

        Livewire::test(CreateUser::class)
            ->fillForm([
                'name' => 'New Operator',
                'email' => $email,
                'password' => self::PASSWORD,
                'passwordConfirmation' => self::PASSWORD,
            ])
            ->call('create')
            ->assertHasNoFormErrors();

        $created = User::where('email', $email)->firstOrFail();
        $this->assertNotSame(self::PASSWORD, $created->password);
        $this->assertTrue(Hash::check(self::PASSWORD, $created->password));
        $this->assertTrue($created->is_panel_operator);

        Auth::logout();
        Livewire::test(Login::class)
            ->fillForm(['email' => $email, 'password' => self::PASSWORD])
            ->call('authenticate')
            ->assertHasNoFormErrors();

        $this->assertAuthenticatedAs($created);
        $this->get('/admin')->assertOk();
    }

    public function test_a_password_is_required_and_must_match_its_confirmation_on_create(): void
    {
        $this->actingAsPanelOperator();

        Livewire::test(CreateUser::class)
            ->fillForm(['name' => 'No Password', 'email' => $this->uniqueEmail()])
            ->call('create')
            ->assertHasFormErrors(['password' => 'required']);

        Livewire::test(CreateUser::class)
            ->fillForm([
                'name' => 'Mismatch',
                'email' => $this->uniqueEmail(),
                'password' => self::PASSWORD,
                'passwordConfirmation' => 'something-else-entirely',
            ])
            ->call('create')
            ->assertHasFormErrors(['password']);
    }

    public function test_a_duplicate_email_is_refused(): void
    {
        $this->actingAsPanelOperator();
        $existing = User::factory()->create();

        Livewire::test(CreateUser::class)
            ->fillForm([
                'name' => 'Duplicate',
                'email' => $existing->email,
                'password' => self::PASSWORD,
                'passwordConfirmation' => self::PASSWORD,
            ])
            ->call('create')
            ->assertHasFormErrors(['email' => 'unique']);
    }

    public function test_editing_with_a_blank_password_keeps_the_current_hash(): void
    {
        $this->actingAsPanelOperator();
        $other = User::factory()->create(['password' => self::PASSWORD]);
        $hash = $other->fresh()->password;

        Livewire::test(EditUser::class, ['record' => $other->getRouteKey()])
            ->fillForm(['name' => 'Renamed', 'password' => ''])
            ->call('save')
            ->assertHasNoFormErrors();

        $fresh = $other->fresh();
        $this->assertSame('Renamed', $fresh->name);
        $this->assertSame($hash, $fresh->password);
    }

    public function test_a_new_password_on_edit_replaces_the_hash(): void
    {
        $this->actingAsPanelOperator();
        $other = User::factory()->create();

        Livewire::test(EditUser::class, ['record' => $other->getRouteKey()])
            ->fillForm(['password' => self::PASSWORD, 'passwordConfirmation' => self::PASSWORD])
            ->call('save')
            ->assertHasNoFormErrors();

        $this->assertTrue(Hash::check(self::PASSWORD, $other->fresh()->password));
    }

    public function test_your_own_panel_access_cannot_be_switched_off(): void
    {
        $me = $this->actingAsPanelOperator();

        Livewire::test(EditUser::class, ['record' => $me->getRouteKey()])
            ->assertFormFieldIsDisabled('is_panel_operator')
            ->fillForm(['is_panel_operator' => false])
            ->call('save')
            ->assertHasNoFormErrors();

        $this->assertTrue($me->fresh()->is_panel_operator);
    }

    public function test_an_account_with_access_switched_off_is_refused_by_the_panel(): void
    {
        $this->actingAsPanelOperator();
        $other = User::factory()->create(['is_panel_operator' => true]);

        Livewire::test(EditUser::class, ['record' => $other->getRouteKey()])
            ->assertFormFieldIsEnabled('is_panel_operator')
            ->fillForm(['is_panel_operator' => false])
            ->call('save')
            ->assertHasNoFormErrors();

        $this->assertFalse($other->fresh()->is_panel_operator);
        $this->actingAs($other->fresh())->get('/admin')->assertForbidden();
    }

    public function test_no_delete_or_bulk_action_exists(): void
    {
        $this->actingAsPanelOperator();
        $other = User::factory()->create();

        Livewire::test(ListUsers::class)
            ->assertTableActionDoesNotExist('delete', record: $other)
            ->assertTableBulkActionDoesNotExist('delete');
        Livewire::test(EditUser::class, ['record' => $other->getRouteKey()])
            ->assertActionDoesNotExist('delete');
    }
}
