<?php

namespace Tests\Feature;

use App\Filament\Resources\TelegramChats\Pages\EditTelegramChat;
use App\Filament\Resources\TelegramChats\Pages\ListTelegramChats;
use App\Models\TelegramChat;
use App\Models\User;
use Illuminate\Database\QueryException;
use Illuminate\Foundation\Testing\DatabaseTransactions;
use Illuminate\Support\Facades\DB;
use Illuminate\Validation\ValidationException;
use Livewire\Livewire;
use Tests\Feature\Concerns\SeedsAlerts;
use Tests\TestCase;

/**
 * T543 (TG-M6, US4; `alerting.md` D1-D2, S2, FR-571): the alert destination on Telegram Groups.
 * Designating moves the one flag; a measured group, a group the bot is not in and a channel are
 * never offered; switching on measurement for the destination is refused with a notification;
 * the database backs both orders. Any destination another run left is cleared first, inside the
 * test's own transaction.
 */
class AlertDestinationTest extends TestCase
{
    use DatabaseTransactions;
    use SeedsAlerts;

    protected function setUp(): void
    {
        parent::setUp();
        $this->actingAs(User::factory()->create(['is_panel_operator' => true]));
        DB::table('telegram_chats')->where('is_alert_destination', true)->update(['is_alert_destination' => false]);
    }

    private function alertGroup(array $overrides = []): TelegramChat
    {
        return $this->makeGroup(array_merge([
            'title' => 'Moderators',
            'is_monitored' => false,
            'bot_status' => 'member',
        ], $overrides));
    }

    public function test_an_unmeasured_group_the_bot_is_in_can_be_designated(): void
    {
        $chat = $this->alertGroup();

        Livewire::test(ListTelegramChats::class)
            ->assertTableActionVisible('use_as_alert_destination', $chat)
            ->assertTableActionHidden('stop_using_as_alert_destination', $chat)
            ->callTableAction('use_as_alert_destination', $chat)
            ->assertHasNoTableActionErrors()
            ->assertTableColumnStateSet('destination', __('Alert destination'), $chat->fresh())
            ->assertTableActionHidden('use_as_alert_destination', $chat->fresh())
            ->assertTableActionVisible('stop_using_as_alert_destination', $chat->fresh());

        $this->assertTrue($chat->fresh()->is_alert_destination);
        $this->assertSame($chat->id, TelegramChat::alertDestination()?->id);
    }

    public function test_a_measured_group_is_never_offered_and_is_refused(): void
    {
        $measured = $this->makeGroup();

        Livewire::test(ListTelegramChats::class)
            ->assertTableActionHidden('use_as_alert_destination', $measured);

        try {
            $measured->useAsAlertDestination();
            $this->fail('a measured group became the destination');
        } catch (ValidationException $refused) {
            $this->assertArrayHasKey('is_alert_destination', $refused->errors());
        }
        $this->assertFalse($measured->fresh()->is_alert_destination);
    }

    public function test_the_database_refuses_a_measured_destination_in_both_orders(): void
    {
        $measured = $this->makeGroup();
        $destination = $this->alertGroup();
        $destination->useAsAlertDestination();

        foreach ([
            fn () => DB::table('telegram_chats')->where('id', $measured->id)->update(['is_alert_destination' => true]),
            fn () => DB::table('telegram_chats')->where('id', $destination->id)->update(['is_monitored' => true]),
        ] as $write) {
            try {
                DB::transaction($write);
                $this->fail('ck_chat_destination_not_monitored let a write through');
            } catch (QueryException $refused) {
                $this->assertStringContainsString('ck_chat_destination_not_monitored', $refused->getMessage());
            }
        }
    }

    public function test_a_group_the_bot_is_not_in_or_a_channel_is_never_offered(): void
    {
        $left = $this->alertGroup(['bot_status' => 'left']);
        $unknown = $this->alertGroup(['bot_status' => 'unknown']);
        $channel = $this->alertGroup(['chat_type' => 'channel', 'bot_status' => 'administrator']);

        $list = Livewire::test(ListTelegramChats::class);
        foreach ([$left, $unknown, $channel] as $chat) {
            $list->assertTableActionHidden('use_as_alert_destination', $chat);
            $this->assertFalse($chat->canBeAlertDestination());
        }
    }

    public function test_a_group_that_became_a_supergroup_is_never_offered(): void
    {
        // Telegram promotes a basic group to a new supergroup chat; the old row keeps the bot's
        // last standing (member) but nothing can be posted there any more (V5's migrated failure).
        $old = $this->alertGroup(['chat_type' => 'group', 'bot_status' => 'member', 'migrated_to_chat_id' => -1009999999999]);

        Livewire::test(ListTelegramChats::class)->assertTableActionHidden('use_as_alert_destination', $old);
        $this->assertFalse($old->canBeAlertDestination());

        try {
            $old->useAsAlertDestination();
            $this->fail('a migrated group was designated');
        } catch (ValidationException $refused) {
            $this->assertSame(
                [__('This group became a supergroup. Use its new row instead.')],
                $refused->errors()['is_alert_destination'],
            );
        }
        $this->assertFalse($old->fresh()->is_alert_destination);
    }

    public function test_monitoring_the_destination_is_refused_with_a_notification(): void
    {
        $chat = $this->alertGroup();
        $chat->useAsAlertDestination();

        Livewire::test(EditTelegramChat::class, ['record' => $chat->getRouteKey()])
            ->fillForm(['is_monitored' => true])
            ->call('save')
            ->assertNotified(__('Not saved'));

        $chat->refresh();
        $this->assertFalse($chat->is_monitored);
        $this->assertTrue($chat->is_alert_destination);

        $this->expectException(ValidationException::class);
        $chat->forceFill(['is_monitored' => true])->save();
    }

    public function test_one_destination_at_a_time(): void
    {
        $first = $this->alertGroup(['title' => 'First alert group']);
        $second = $this->alertGroup(['title' => 'Second alert group']);

        $first->useAsAlertDestination();
        Livewire::test(ListTelegramChats::class)
            ->callTableAction('use_as_alert_destination', $second)
            ->assertHasNoTableActionErrors();

        $this->assertFalse($first->fresh()->is_alert_destination);
        $this->assertTrue($second->fresh()->is_alert_destination);
        $this->assertSame(1, TelegramChat::query()->where('is_alert_destination', true)->count());
    }

    public function test_stop_using_clears_the_destination(): void
    {
        $chat = $this->alertGroup();
        $chat->useAsAlertDestination();

        Livewire::test(ListTelegramChats::class)
            ->callTableAction('stop_using_as_alert_destination', $chat)
            ->assertHasNoTableActionErrors();

        $this->assertFalse($chat->fresh()->is_alert_destination);
        $this->assertNull(TelegramChat::alertDestination());
        // Unmeasured still: stopping changes only the flag.
        $this->assertFalse($chat->fresh()->is_monitored);
    }
}
