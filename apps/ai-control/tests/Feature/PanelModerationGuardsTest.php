<?php

namespace Tests\Feature;

use App\Filament\Resources\Moderators\Pages\EditModerator;
use App\Filament\Resources\Moderators\Pages\ListModerators;
use App\Filament\Resources\Moderators\RelationManagers\AssignmentsRelationManager;
use App\Filament\Resources\TelegramChats\Pages\EditTelegramChat;
use App\Filament\Resources\TelegramChats\Pages\ListTelegramChats;
use App\Models\Moderator;
use App\Models\TelegramChat;
use App\Models\TelegramUser;
use App\Models\User;
use Illuminate\Foundation\Testing\DatabaseTransactions;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Queue;
use Livewire\Livewire;
use Tests\TestCase;

/**
 * T056 (US5): standing prohibitions, restated because this milestone triples the panel's
 * surface (`control-panel-moderation.md` §4, FR-050, SC-022) — no platform call, no model call,
 * no bulk-derivation action anywhere in the panel.
 */
class PanelModerationGuardsTest extends TestCase
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
            'title' => 'Guarded Group',
            'is_monitored' => false,
        ], $overrides));
    }

    private function makeModerator(): Moderator
    {
        $identity = TelegramUser::forceCreate([
            'tg_user_id' => random_int(10_000_000, 2_000_000_000),
            'is_bot' => false,
            'first_seen_at' => now(),
            'last_seen_at' => now(),
        ]);

        return Moderator::create([
            'telegram_user_id' => $identity->id,
            'display_name' => 'Guarded Moderator',
        ]);
    }

    /** @return array<int, string> */
    private function forbiddenActionNames(): array
    {
        return ['derive', 'rederive', 'derive_messages', 'bulk_derive', 'sync', 'run_command'];
    }

    public function test_no_bulk_derivation_action_exists_on_the_groups_screens(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();

        $list = Livewire::test(ListTelegramChats::class);
        $edit = Livewire::test(EditTelegramChat::class, ['record' => $chat->getRouteKey()]);

        foreach ($this->forbiddenActionNames() as $name) {
            $list->assertTableActionDoesNotExist($name);
            $edit->assertActionDoesNotExist($name);
        }
    }

    public function test_no_bulk_derivation_action_exists_on_the_moderators_screens(): void
    {
        $this->actingAsPanelOperator();
        $moderator = $this->makeModerator();

        $list = Livewire::test(ListModerators::class);
        $edit = Livewire::test(EditModerator::class, ['record' => $moderator->getRouteKey()]);
        $assignments = Livewire::test(AssignmentsRelationManager::class, [
            'ownerRecord' => $moderator,
            'pageClass' => EditModerator::class,
        ]);

        foreach ($this->forbiddenActionNames() as $name) {
            $list->assertTableActionDoesNotExist($name);
            $edit->assertActionDoesNotExist($name);
            $assignments->assertTableActionDoesNotExist($name);
        }
    }

    public function test_switching_measurement_makes_no_platform_call_and_starts_no_job(): void
    {
        $this->actingAsPanelOperator();
        Http::preventStrayRequests();
        Queue::fake();

        $chat = $this->makeChat();

        Livewire::test(EditTelegramChat::class, ['record' => $chat->getRouteKey()])
            ->fillForm(['is_monitored' => true])
            ->call('save')
            ->assertHasNoFormErrors();

        Http::assertNothingSent();
        Queue::assertNothingPushed();
    }

    public function test_mapping_a_moderator_makes_no_platform_call_and_starts_no_job(): void
    {
        $this->actingAsPanelOperator();
        Http::preventStrayRequests();
        Queue::fake();

        $this->makeModerator();

        Http::assertNothingSent();
        Queue::assertNothingPushed();
    }

    public function test_reassign_makes_no_platform_call_and_starts_no_job(): void
    {
        $this->actingAsPanelOperator();
        Http::preventStrayRequests();
        Queue::fake();

        $moderator = $this->makeModerator();
        $chat = $this->makeChat(['is_monitored' => true]);

        Livewire::test(AssignmentsRelationManager::class, [
            'ownerRecord' => $moderator,
            'pageClass' => EditModerator::class,
        ])->callTableAction('reassign', null, ['telegram_chat_id' => $chat->id]);

        Http::assertNothingSent();
        Queue::assertNothingPushed();
    }
}
