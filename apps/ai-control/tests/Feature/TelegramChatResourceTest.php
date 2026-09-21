<?php

namespace Tests\Feature;

use App\Filament\Resources\TelegramChats\Pages\EditTelegramChat;
use App\Filament\Resources\TelegramChats\Pages\ListTelegramChats;
use App\Filament\Resources\TelegramChats\TelegramChatResource;
use App\Models\Moderator;
use App\Models\ModeratorGroupAssignment;
use App\Models\TelegramChat;
use App\Models\TelegramUser;
use App\Models\User;
use Illuminate\Foundation\Testing\DatabaseTransactions;
use Illuminate\Support\Facades\Queue;
use Livewire\Livewire;
use Tests\TestCase;

/**
 * T030 (US2): the measured toggle writes one boolean and starts no job (FR-018,
 * `message-derivation.md` §7 R2); the resource exposes no create and no delete action, since
 * groups are discovered by capture, never typed in, and deleting one would orphan messages and
 * assignments (`control-panel-moderation.md` §2); the course reference is a plain, unvalidated
 * value — the reference application is on another host and is read-only (FR-046, Principle III).
 * T057 (US5): a measured group with no current primary owner, and a measured group where the
 * bot is not an administrator, are each distinguishable without opening a record (FR-049,
 * SC-023) — both silent by nature.
 */
class TelegramChatResourceTest extends TestCase
{
    use DatabaseTransactions;

    private function actingAsPanelOperator(): void
    {
        $this->actingAs(User::factory()->create(['is_panel_operator' => true]));
    }

    /**
     * `chat_id`/`chat_type`/`title` are deliberately not in the model's `$fillable` — groups
     * are discovered by capture, never typed in (T009). `forceCreate` bypasses that guard for
     * test setup only, the way capture itself would populate the row.
     */
    private function makeChat(array $overrides = []): TelegramChat
    {
        return TelegramChat::forceCreate(array_merge([
            'chat_id' => -random_int(10_000_000, 2_000_000_000),
            'chat_type' => 'group',
            'title' => 'Test Group',
            'is_monitored' => false,
        ], $overrides));
    }

    public function test_toggling_measured_writes_only_that_boolean_and_starts_no_job(): void
    {
        $this->actingAsPanelOperator();
        Queue::fake();

        $chat = $this->makeChat(['is_monitored' => false]);
        $before = $chat->fresh()->getAttributes();

        Livewire::test(EditTelegramChat::class, ['record' => $chat->getRouteKey()])
            ->fillForm(['is_monitored' => true])
            ->call('save')
            ->assertHasNoFormErrors();

        $after = $chat->fresh()->getAttributes();

        $this->assertTrue((bool) $after['is_monitored']);
        $changed = array_keys(array_diff_assoc(
            array_map(static fn ($v) => is_bool($v) ? (int) $v : $v, $after),
            array_map(static fn ($v) => is_bool($v) ? (int) $v : $v, $before),
        ));
        // `updated_at` is touched by every Eloquent save, but Eloquent's default timestamp
        // string has second precision — a fast test that completes within the same wall-clock
        // second legitimately writes the identical string on both reads. The meaningful
        // assertion is that no *other* column moved, not that this incidental one always shows
        // as different.
        $this->assertContains('is_monitored', $changed);
        $this->assertSame([], array_diff($changed, ['is_monitored', 'updated_at']));

        Queue::assertNothingPushed();
    }

    public function test_switching_measurement_off_leaves_the_row_otherwise_untouched(): void
    {
        $this->actingAsPanelOperator();

        $chat = $this->makeChat(['is_monitored' => true, 'injaz_course_id' => 42]);

        Livewire::test(EditTelegramChat::class, ['record' => $chat->getRouteKey()])
            ->fillForm(['is_monitored' => false])
            ->call('save')
            ->assertHasNoFormErrors();

        $fresh = $chat->fresh();
        $this->assertFalse($fresh->is_monitored);
        $this->assertSame(42, $fresh->injaz_course_id);
    }

    public function test_resource_has_no_create_page(): void
    {
        $this->assertFalse(TelegramChatResource::hasPage('create'));
    }

    public function test_resource_has_no_delete_action(): void
    {
        $this->actingAsPanelOperator();

        $chat = $this->makeChat();

        Livewire::test(ListTelegramChats::class)
            ->assertTableActionDoesNotExist('delete', record: $chat)
            ->assertTableBulkActionDoesNotExist('delete');

        $this->assertNotNull($chat->fresh());
    }

    public function test_the_course_reference_stores_a_plain_value_with_no_validation(): void
    {
        $this->actingAsPanelOperator();

        $chat = $this->makeChat(['injaz_course_id' => null]);

        Livewire::test(EditTelegramChat::class, ['record' => $chat->getRouteKey()])
            ->fillForm(['injaz_course_id' => 999_999])
            ->call('save')
            ->assertHasNoFormErrors();

        $this->assertSame(999_999, $chat->fresh()->injaz_course_id);
    }

    public function test_a_measured_group_with_no_current_primary_owner_is_flagged(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat(['is_monitored' => true]);

        Livewire::test(ListTelegramChats::class)
            ->assertTableColumnStateSet('has_current_owner', false, $chat);
    }

    public function test_a_measured_group_with_a_current_primary_owner_is_not_flagged(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat(['is_monitored' => true]);
        $identity = TelegramUser::forceCreate([
            'tg_user_id' => random_int(10_000_000, 2_000_000_000),
            'is_bot' => false,
        ]);
        $moderator = Moderator::create([
            'telegram_user_id' => $identity->id,
            'display_name' => 'Owner',
        ]);
        ModeratorGroupAssignment::handover($chat->id, $moderator->id);

        Livewire::test(ListTelegramChats::class)
            ->assertTableColumnStateSet('has_current_owner', true, $chat);
    }

    public function test_a_measured_group_where_the_bot_is_not_an_administrator_is_flagged(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat(['is_monitored' => true, 'bot_status' => 'member']);

        Livewire::test(ListTelegramChats::class)
            ->assertTableColumnStateSet('bot_is_admin', false, $chat);
    }

    public function test_a_measured_group_where_the_bot_is_an_administrator_is_not_flagged(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat(['is_monitored' => true, 'bot_status' => 'administrator']);

        Livewire::test(ListTelegramChats::class)
            ->assertTableColumnStateSet('bot_is_admin', true, $chat);
    }

    public function test_an_unmeasured_group_is_never_flagged_for_coverage(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat(['is_monitored' => false, 'bot_status' => 'member']);

        Livewire::test(ListTelegramChats::class)
            ->assertTableColumnStateSet('has_current_owner', true, $chat)
            ->assertTableColumnStateSet('bot_is_admin', true, $chat);
    }
}
