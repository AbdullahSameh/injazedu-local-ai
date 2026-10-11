<?php

namespace Tests\Feature;

use App\Filament\Resources\ModelProfiles\Pages\CreateModelProfile;
use App\Filament\Resources\ModelProfiles\Pages\EditModelProfile;
use App\Filament\Resources\ModelProfiles\Pages\ListModelProfiles;
use App\Models\ModelProfile;
use App\Models\User;
use Illuminate\Foundation\Testing\DatabaseTransactions;
use Livewire\Livewire;
use Tests\TestCase;

/**
 * T073 (US7, `control-panel-classification.md` §2.4 R1-R2, FR-058, SC-010): the roster's role
 * select and filter offer `moderation`; `App\Models\ModelProfile`'s existing activation guard
 * covers it unchanged — activating a classification model never touches the `llm` role, and
 * vice versa, and deactivating the only active moderation profile is refused exactly as it is
 * for any other role.
 */
class ModelProfileRoleTest extends TestCase
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

    public function test_the_form_and_filter_offer_the_moderation_role(): void
    {
        $this->actingAsPanelOperator();

        Livewire::test(CreateModelProfile::class)
            ->fillForm([
                'name' => 'test-moderation-'.bin2hex(random_bytes(6)),
                'provider' => 'fake',
                'model' => 'fake-model',
                'role' => 'moderation',
                'is_active' => false,
            ])
            ->call('create')
            ->assertHasNoFormErrors();

        $moderationProfile = $this->makeProfile(['role' => 'moderation']);

        Livewire::test(ListModelProfiles::class)
            ->filterTable('role', 'moderation')
            ->assertCanSeeTableRecords([$moderationProfile]);
    }

    public function test_activating_a_second_moderation_profile_deactivates_the_first_and_leaves_llm_unchanged(): void
    {
        $this->actingAsPanelOperator();

        $activeLlm = $this->makeProfile(['role' => 'llm', 'is_active' => true]);
        $incumbentModeration = $this->makeProfile(['role' => 'moderation', 'is_active' => true]);
        $challengerModeration = $this->makeProfile(['role' => 'moderation', 'is_active' => false]);

        Livewire::test(EditModelProfile::class, ['record' => $challengerModeration->getRouteKey()])
            ->fillForm(['is_active' => true])
            ->call('save')
            ->assertHasNoFormErrors();

        $this->assertTrue($challengerModeration->fresh()->is_active);
        $this->assertFalse($incumbentModeration->fresh()->is_active);
        $this->assertTrue($activeLlm->fresh()->is_active);
    }

    public function test_activating_a_different_llm_profile_leaves_the_moderation_profile_unchanged(): void
    {
        $this->actingAsPanelOperator();

        $activeModeration = $this->makeProfile(['role' => 'moderation', 'is_active' => true]);
        $incumbentLlm = $this->makeProfile(['role' => 'llm', 'is_active' => true]);
        $challengerLlm = $this->makeProfile(['role' => 'llm', 'is_active' => false]);

        Livewire::test(EditModelProfile::class, ['record' => $challengerLlm->getRouteKey()])
            ->fillForm(['is_active' => true])
            ->call('save')
            ->assertHasNoFormErrors();

        $this->assertTrue($challengerLlm->fresh()->is_active);
        $this->assertFalse($incumbentLlm->fresh()->is_active);
        $this->assertTrue($activeModeration->fresh()->is_active);
    }

    public function test_deactivating_the_only_active_moderation_profile_is_refused(): void
    {
        $this->actingAsPanelOperator();

        $onlyActive = $this->makeProfile(['role' => 'moderation', 'is_active' => true]);

        Livewire::test(EditModelProfile::class, ['record' => $onlyActive->getRouteKey()])
            ->fillForm(['is_active' => false])
            ->call('save')
            ->assertHasErrors(['is_active']);

        $this->assertTrue($onlyActive->fresh()->is_active);
    }
}
