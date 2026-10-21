<?php

namespace Tests\Feature;

use App\Filament\Resources\Moderators\Pages\CreateModerator;
use App\Filament\Resources\Moderators\Pages\EditModerator;
use App\Filament\Resources\Moderators\RelationManagers\AssignmentsRelationManager;
use App\Models\Moderator;
use App\Models\ModeratorGroupAssignment;
use App\Models\TelegramChat;
use App\Models\TelegramUser;
use App\Models\User;
use Illuminate\Foundation\Testing\DatabaseTransactions;
use Livewire\Livewire;
use Tests\TestCase;

/**
 * T054 (US5): a moderator can be added with an observed sender identity **or** a not-yet-observed
 * numeric identifier, creating exactly one placeholder identity; deactivation changes only
 * availability (FR-047, SC-009). T055: the reassign action delegates to the model method rather
 * than performing two writes of its own, and the assignments view lists every past and current
 * assignment in chronological order, with nothing deletable (FR-048, D-TG-58).
 */
class ModeratorResourceTest extends TestCase
{
    use DatabaseTransactions;

    private function actingAsPanelOperator(): void
    {
        $this->actingAs(User::factory()->create(['is_panel_operator' => true]));
    }

    private function makeChat(array $overrides = []): TelegramChat
    {
        return TelegramChat::forceCreate(array_merge([
            'chat_id' => -random_int(10_000_000, 2_000_000_000),
            'chat_type' => 'group',
            'title' => 'Test Group',
            'is_monitored' => true,
        ], $overrides));
    }

    private function makeObservedIdentity(array $overrides = []): TelegramUser
    {
        return TelegramUser::forceCreate(array_merge([
            'tg_user_id' => random_int(10_000_000, 2_000_000_000),
            'display_name' => 'Observed Person',
            'is_bot' => false,
            'first_seen_at' => now(),
            'last_seen_at' => now(),
        ], $overrides));
    }

    public function test_a_moderator_can_be_added_with_a_not_yet_observed_numeric_identifier(): void
    {
        $this->actingAsPanelOperator();
        $tgUserId = random_int(10_000_000, 2_000_000_000);

        Livewire::test(CreateModerator::class)
            ->fillForm([
                'display_name' => 'Future Moderator',
                'identity_source' => 'placeholder',
                'tg_user_id' => $tgUserId,
            ])
            ->call('create')
            ->assertHasNoFormErrors();

        $identity = TelegramUser::where('tg_user_id', $tgUserId)->firstOrFail();
        $this->assertNull($identity->display_name);
        $this->assertNull($identity->first_seen_at);
        $this->assertSame(1, TelegramUser::where('tg_user_id', $tgUserId)->count());

        $moderator = Moderator::where('telegram_user_id', $identity->id)->firstOrFail();
        $this->assertSame('Future Moderator', $moderator->display_name);
    }

    public function test_a_moderator_can_be_added_with_an_already_observed_identity(): void
    {
        $this->actingAsPanelOperator();
        $identity = $this->makeObservedIdentity();

        Livewire::test(CreateModerator::class)
            ->fillForm([
                'display_name' => 'Observed Moderator',
                'identity_source' => 'observed',
                'existing_telegram_user_id' => $identity->id,
            ])
            ->call('create')
            ->assertHasNoFormErrors();

        $moderator = Moderator::where('telegram_user_id', $identity->id)->firstOrFail();
        $this->assertSame('Observed Moderator', $moderator->display_name);
    }

    /**
     * The identity choice re-renders the form, so choosing an observed sender hides the numeric id
     * field (and its browser `required` check) instead of leaving it on screen, blocking the save.
     */
    public function test_the_identity_choice_switches_which_field_is_shown(): void
    {
        $this->actingAsPanelOperator();

        $test = Livewire::test(CreateModerator::class);
        $this->assertTrue(
            $test->instance()->form->getComponent('identity_source')->isLive()
        );

        $test->assertFormFieldIsVisible('tg_user_id')
            ->assertFormFieldIsHidden('existing_telegram_user_id')
            ->fillForm(['identity_source' => 'observed'])
            ->assertFormFieldIsHidden('tg_user_id')
            ->assertFormFieldIsVisible('existing_telegram_user_id');
    }

    /** Revision 0009: the panel account link is optional on create. */
    public function test_a_moderator_can_be_added_with_or_without_a_panel_account(): void
    {
        $this->actingAsPanelOperator();
        $account = User::factory()->create();
        $linked = $this->makeObservedIdentity();
        $unlinked = $this->makeObservedIdentity();

        Livewire::test(CreateModerator::class)
            ->fillForm([
                'display_name' => 'Linked Moderator',
                'identity_source' => 'observed',
                'existing_telegram_user_id' => $linked->id,
                'user_id' => $account->id,
            ])
            ->call('create')
            ->assertHasNoFormErrors();

        Livewire::test(CreateModerator::class)
            ->fillForm([
                'display_name' => 'Unlinked Moderator',
                'identity_source' => 'observed',
                'existing_telegram_user_id' => $unlinked->id,
            ])
            ->call('create')
            ->assertHasNoFormErrors();

        $this->assertSame($account->id, Moderator::where('telegram_user_id', $linked->id)->value('user_id'));
        $this->assertNull(Moderator::where('telegram_user_id', $unlinked->id)->value('user_id'));
        $this->assertSame('Linked Moderator', $account->fresh()->moderator->display_name);
    }

    public function test_a_panel_account_can_be_linked_and_unlinked_on_edit(): void
    {
        $this->actingAsPanelOperator();
        $account = User::factory()->create();
        $moderator = Moderator::create([
            'telegram_user_id' => $this->makeObservedIdentity()->id,
            'display_name' => 'Editable Moderator',
        ]);

        Livewire::test(EditModerator::class, ['record' => $moderator->getRouteKey()])
            ->fillForm(['user_id' => $account->id])
            ->call('save')
            ->assertHasNoFormErrors();
        $this->assertSame($account->id, $moderator->fresh()->user_id);

        Livewire::test(EditModerator::class, ['record' => $moderator->getRouteKey()])
            ->fillForm(['user_id' => null])
            ->call('save')
            ->assertHasNoFormErrors();
        $this->assertNull($moderator->fresh()->user_id);
    }

    public function test_one_panel_account_links_to_at_most_one_moderator(): void
    {
        $this->actingAsPanelOperator();
        $account = User::factory()->create();
        Moderator::create([
            'telegram_user_id' => $this->makeObservedIdentity()->id,
            'display_name' => 'First Moderator',
            'user_id' => $account->id,
        ]);
        $second = Moderator::create([
            'telegram_user_id' => $this->makeObservedIdentity()->id,
            'display_name' => 'Second Moderator',
        ]);

        Livewire::test(EditModerator::class, ['record' => $second->getRouteKey()])
            ->fillForm(['user_id' => $account->id])
            ->call('save')
            ->assertHasFormErrors(['user_id' => 'unique']);

        $this->assertNull($second->fresh()->user_id);
    }

    public function test_deactivation_changes_only_availability(): void
    {
        $this->actingAsPanelOperator();
        $identity = $this->makeObservedIdentity();
        $moderator = Moderator::create([
            'telegram_user_id' => $identity->id,
            'display_name' => 'Active Moderator',
            'is_active' => true,
        ]);

        Livewire::test(EditModerator::class, ['record' => $moderator->getRouteKey()])
            ->fillForm(['is_active' => false])
            ->call('save')
            ->assertHasNoFormErrors();

        $fresh = $moderator->fresh();
        $this->assertFalse($fresh->is_active);
        $this->assertSame('Active Moderator', $fresh->display_name);
        $this->assertSame($identity->id, $fresh->telegram_user_id);
    }

    public function test_add_to_group_delegates_to_the_model_method(): void
    {
        $this->actingAsPanelOperator();
        $identity = $this->makeObservedIdentity();
        $moderator = Moderator::create([
            'telegram_user_id' => $identity->id,
            'display_name' => 'Reassignable Moderator',
        ]);
        $chat = $this->makeChat();

        Livewire::test(AssignmentsRelationManager::class, [
            'ownerRecord' => $moderator,
            'pageClass' => EditModerator::class,
        ])->callTableAction('add_to_group', null, [
            'telegram_chat_id' => $chat->id,
            'note' => 'covering while on leave',
        ])->assertHasNoTableActionErrors();

        $assignment = ModeratorGroupAssignment::query()
            ->where('telegram_chat_id', $chat->id)
            ->where('moderator_id', $moderator->id)
            ->currentMembers()
            ->firstOrFail();

        $this->assertSame('covering while on leave', $assignment->note);
        $this->assertSame('primary', $assignment->assignment_role);
        $this->assertNull($assignment->valid_to);
    }

    public function test_the_assignments_view_lists_the_newest_ten_first_with_nothing_deletable(): void
    {
        $this->actingAsPanelOperator();
        $identity = $this->makeObservedIdentity();
        $moderator = Moderator::create([
            'telegram_user_id' => $identity->id,
            'display_name' => 'History Moderator',
        ]);
        $chat = $this->makeChat(['title' => 'Group A']);
        // Twelve ended memberships, one a day, written directly as fixtures: day 12 is the newest.
        $history = collect(range(1, 12))->map(fn (int $day) => ModeratorGroupAssignment::create([
            'telegram_chat_id' => $chat->id,
            'moderator_id' => $moderator->id,
            'assignment_role' => 'primary',
            'valid_from' => now()->subDays(13 - $day)->format('Y-m-d H:i:s.u'),
            'valid_to' => now()->subDays(13 - $day)->addHour()->format('Y-m-d H:i:s.u'),
        ]));

        $component = Livewire::test(AssignmentsRelationManager::class, [
            'ownerRecord' => $moderator,
            'pageClass' => EditModerator::class,
        ]);

        $component->assertCanSeeTableRecords($history->slice(2)->reverse()->values(), inOrder: true);
        $component->assertCanNotSeeTableRecords($history->take(2));
        $component->assertTableActionDoesNotExist('delete');
        $component->assertTableBulkActionDoesNotExist('delete');
    }
}
