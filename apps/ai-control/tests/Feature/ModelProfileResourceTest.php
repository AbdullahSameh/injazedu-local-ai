<?php

namespace Tests\Feature;

use App\Filament\Resources\ModelProfiles\Pages\EditModelProfile;
use App\Models\ModelProfile;
use App\Models\User;
use Illuminate\Foundation\Testing\DatabaseTransactions;
use Livewire\Livewire;
use Tests\TestCase;

/**
 * The activation invariant (data-model.md §1, FR-011, FR-017, FR-043): the database's partial
 * unique index makes "two active profiles for one role" impossible, and the panel must honour
 * it — not merely rely on the index rejecting a bad write with an ugly database error.
 */
class ModelProfileResourceTest extends TestCase
{
    use DatabaseTransactions;

    private function actingAsPanelOperator(): void
    {
        $this->actingAs(User::factory()->create(['is_panel_operator' => true]));
    }

    private function makeProfile(array $overrides = []): ModelProfile
    {
        return ModelProfile::create(array_merge([
            'name' => 'test-profile-'.bin2hex(random_bytes(6)),
            'provider' => 'fake',
            'base_url' => null,
            'model' => 'fake-model',
            'role' => 'llm',
            'params' => [],
            'dim' => null,
            'api_key_env' => null,
            'is_active' => false,
        ], $overrides));
    }

    public function test_activating_a_profile_deactivates_the_incumbent_in_one_transaction(): void
    {
        $this->actingAsPanelOperator();

        $incumbent = $this->makeProfile(['role' => 'llm', 'is_active' => true]);
        $challenger = $this->makeProfile(['role' => 'llm', 'is_active' => false]);

        Livewire::test(EditModelProfile::class, ['record' => $challenger->getRouteKey()])
            ->fillForm(['is_active' => true])
            ->call('save')
            ->assertHasNoFormErrors();

        $this->assertTrue($challenger->fresh()->is_active);
        $this->assertFalse($incumbent->fresh()->is_active);
    }

    public function test_deactivating_the_only_active_profile_for_a_role_is_refused(): void
    {
        $this->actingAsPanelOperator();

        $onlyActive = $this->makeProfile([
            'role' => 'embedding',
            'dim' => 8,
            'is_active' => true,
        ]);

        Livewire::test(EditModelProfile::class, ['record' => $onlyActive->getRouteKey()])
            ->fillForm(['is_active' => false])
            ->call('save')
            ->assertHasErrors(['is_active']);

        $this->assertTrue($onlyActive->fresh()->is_active);
    }

    public function test_editing_dim_on_an_existing_row_is_refused(): void
    {
        $this->actingAsPanelOperator();

        $profile = $this->makeProfile([
            'role' => 'embedding',
            'dim' => 8,
            'is_active' => false,
        ]);

        Livewire::test(EditModelProfile::class, ['record' => $profile->getRouteKey()])
            ->fillForm(['dim' => 16])
            ->call('save')
            ->assertHasErrors(['dim']);

        $this->assertSame(8, $profile->fresh()->dim);
    }
}
