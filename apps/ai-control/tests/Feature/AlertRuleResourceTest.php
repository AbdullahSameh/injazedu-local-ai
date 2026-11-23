<?php

namespace Tests\Feature;

use App\Filament\Resources\AlertRules\AlertRuleResource;
use App\Filament\Resources\AlertRules\Pages\CreateAlertRule;
use App\Filament\Resources\AlertRules\Pages\EditAlertRule;
use App\Filament\Resources\AlertRules\Pages\ListAlertRules;
use App\Models\AlertRule;
use App\Models\User;
use Filament\Forms\Components\Select;
use Illuminate\Foundation\Testing\DatabaseTransactions;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;
use Illuminate\Validation\ValidationException;
use Livewire\Livewire;
use LogicException;
use PHPUnit\Framework\Attributes\DataProvider;
use Tests\Feature\Concerns\SeedsAlerts;
use Tests\TestCase;

/**
 * T543 (TG-M6, US4; `alerting.md` S1, R1-R8): the Alert Rules resource. Each R-rule refusal reads
 * as a sentence, from the form and from the model; `enabled_at` is stamped on each change from
 * disabled to enabled and on nothing else; a disabled group rule beside an enabled all-groups rule
 * is allowed (it mutes the trigger for that group — the muting itself is the evaluator's, tested in
 * Python); nothing is deletable; only measured groups are offered.
 */
class AlertRuleResourceTest extends TestCase
{
    use DatabaseTransactions;
    use SeedsAlerts;

    private User $operator;

    protected function setUp(): void
    {
        parent::setUp();
        $this->operator = User::factory()->create(['is_panel_operator' => true]);
        $this->actingAs($this->operator);
    }

    public function test_a_group_rule_is_created_in_minutes_and_stored_in_seconds(): void
    {
        $chat = $this->makeGroup();

        Livewire::test(CreateAlertRule::class)
            ->fillForm([
                'trigger' => 'question_waiting',
                'telegram_chat_id' => $chat->id,
                'threshold_s' => 10,
                'repeat_every_s' => 30,
                'max_repeats' => 2,
                'quiet_hours' => [['from' => '23:00', 'to' => '07:00']],
                'is_enabled' => true,
            ])
            ->call('create')
            ->assertHasNoFormErrors();

        $rule = AlertRule::query()->where('telegram_chat_id', $chat->id)->sole();
        $this->assertSame('question_waiting', $rule->trigger);
        $this->assertSame(600, $rule->threshold_s);
        $this->assertSame(1800, $rule->repeat_every_s);
        $this->assertSame(2, $rule->max_repeats);
        $this->assertEquals([['from' => '23:00', 'to' => '07:00']], $rule->quiet_hours); // jsonb orders keys
        $this->assertTrue($rule->is_enabled);
        $this->assertNotNull($rule->enabled_at);
        $this->assertSame($this->operator->id, $rule->updated_by_user_id);
        $this->assertNull($rule->min_severity);
    }

    public function test_an_incident_rule_keeps_its_filters_and_an_empty_choice_means_any(): void
    {
        $chat = $this->makeGroup();

        Livewire::test(CreateAlertRule::class)
            ->fillForm([
                'trigger' => 'incident_flagged',
                'telegram_chat_id' => $chat->id,
                'min_severity' => 'medium',
                'categories' => ['SPAM_OR_AD'],
                'openers' => [],
            ])
            ->call('create')
            ->assertHasNoFormErrors();

        $rule = AlertRule::query()->where('telegram_chat_id', $chat->id)->sole();
        $this->assertNull($rule->threshold_s);
        $this->assertSame('medium', $rule->min_severity);
        $this->assertSame(['SPAM_OR_AD'], $rule->categories);
        $this->assertNull($rule->openers);
        $this->assertFalse($rule->is_enabled);
        $this->assertNull($rule->enabled_at);
    }

    public function test_the_trigger_drives_which_fields_show(): void
    {
        Livewire::test(CreateAlertRule::class)
            ->fillForm(['trigger' => 'bot_not_admin'])
            ->assertFormFieldHidden('threshold_s')
            ->assertFormFieldHidden('min_severity')
            ->fillForm(['trigger' => 'group_silent'])
            ->assertFormFieldVisible('threshold_s')
            ->assertFormFieldHidden('categories')
            ->fillForm(['trigger' => 'incident_unhandled'])
            ->assertFormFieldVisible('threshold_s')
            ->assertFormFieldVisible('openers');
    }

    public function test_a_threshold_trigger_without_a_threshold_is_refused_in_the_form(): void
    {
        $chat = $this->makeGroup();

        Livewire::test(CreateAlertRule::class)
            ->fillForm(['trigger' => 'group_silent', 'telegram_chat_id' => $chat->id])
            ->call('create')
            ->assertHasFormErrors(['threshold_s']);

        $this->assertFalse(AlertRule::query()->where('telegram_chat_id', $chat->id)->exists());
    }

    public function test_a_repeat_interval_without_a_count_is_refused_in_the_form(): void
    {
        $chat = $this->makeGroup();

        Livewire::test(CreateAlertRule::class)
            ->fillForm([
                'trigger' => 'question_waiting',
                'telegram_chat_id' => $chat->id,
                'threshold_s' => 5,
                'repeat_every_s' => 10,
            ])
            ->call('create')
            ->assertHasFormErrors(['max_repeats']);

        $this->assertFalse(AlertRule::query()->where('telegram_chat_id', $chat->id)->exists());
    }

    public function test_a_second_rule_for_the_same_group_and_trigger_is_refused_in_the_form(): void
    {
        $chat = $this->makeGroup();
        $this->seedRule($chat, 'bot_not_admin');

        Livewire::test(CreateAlertRule::class)
            ->fillForm(['trigger' => 'bot_not_admin', 'telegram_chat_id' => $chat->id])
            ->call('create')
            ->assertHasFormErrors(['telegram_chat_id']);

        $this->assertSame(1, AlertRule::query()->where('telegram_chat_id', $chat->id)->count());
    }

    /**
     * @return array<string, array{0: array<string, mixed>, 1: string}>
     */
    public static function refusals(): array
    {
        return [
            'R2 an unknown trigger' => [['trigger' => 'question_answered'], 'trigger'],
            'R3 a threshold missing' => [['trigger' => 'question_waiting'], 'threshold_s'],
            'R3 a threshold forbidden' => [['trigger' => 'bot_not_admin', 'threshold_s' => 600], 'threshold_s'],
            'R3 a threshold not positive' => [['trigger' => 'group_silent', 'threshold_s' => 0], 'threshold_s'],
            'R4 a filter on a non-incident trigger' => [['trigger' => 'group_silent', 'threshold_s' => 600, 'min_severity' => 'high'], 'min_severity'],
            'R4 an unknown severity' => [['trigger' => 'incident_flagged', 'min_severity' => 'urgent'], 'min_severity'],
            'R4 an unknown category' => [['trigger' => 'incident_flagged', 'categories' => ['QUESTION_COURSE']], 'categories'],
            'R4 an unknown opener' => [['trigger' => 'incident_flagged', 'openers' => ['moderator']], 'openers'],
            'R6 an interval without a count' => [['trigger' => 'bot_not_admin', 'repeat_every_s' => 600], 'max_repeats'],
            'R6 a count without an interval' => [['trigger' => 'bot_not_admin', 'max_repeats' => 2], 'repeat_every_s'],
            'R6 a count not positive' => [['trigger' => 'bot_not_admin', 'repeat_every_s' => 600, 'max_repeats' => 0], 'max_repeats'],
            'R7 a window not HH:MM' => [['trigger' => 'bot_not_admin', 'quiet_hours' => [['from' => '7:00', 'to' => '09:00']]], 'quiet_hours'],
            'R7 a window past 23:59' => [['trigger' => 'bot_not_admin', 'quiet_hours' => [['from' => '22:00', 'to' => '24:00']]], 'quiet_hours'],
            'R7 a window from equal to' => [['trigger' => 'bot_not_admin', 'quiet_hours' => [['from' => '22:00', 'to' => '22:00']]], 'quiet_hours'],
            'R7 a window missing its end' => [['trigger' => 'bot_not_admin', 'quiet_hours' => [['from' => '22:00']]], 'quiet_hours'],
        ];
    }

    /**
     * @param  array<string, mixed>  $values
     */
    #[DataProvider('refusals')]
    public function test_the_model_refuses_each_rule_violation_with_a_sentence(array $values, string $field): void
    {
        $chat = $this->makeGroup();

        try {
            AlertRule::query()->create(['telegram_chat_id' => $chat->id] + $values);
            $this->fail('the rule was saved');
        } catch (ValidationException $refused) {
            $this->assertArrayHasKey($field, $refused->errors());
        }

        $this->assertFalse(AlertRule::query()->where('telegram_chat_id', $chat->id)->exists());
    }

    public function test_a_group_rule_on_an_unmeasured_group_is_refused_and_never_offered(): void
    {
        $measured = $this->makeGroup(['title' => 'Measured Group']);
        $unmeasured = $this->makeGroup(['title' => 'Unmeasured Group', 'is_monitored' => false]);

        Livewire::test(CreateAlertRule::class)
            ->assertFormFieldExists('telegram_chat_id', function (Select $field) use ($measured, $unmeasured): bool {
                $options = $field->getOptions();

                return array_key_exists($measured->id, $options) && ! array_key_exists($unmeasured->id, $options);
            });

        $this->expectException(ValidationException::class);
        AlertRule::query()->create(['trigger' => 'bot_not_admin', 'telegram_chat_id' => $unmeasured->id]);
    }

    public function test_a_rule_whose_group_stopped_being_measured_can_still_be_disabled(): void
    {
        $chat = $this->makeGroup();
        $rule = AlertRule::query()->create(['trigger' => 'bot_not_admin', 'telegram_chat_id' => $chat->id, 'is_enabled' => true]);
        $chat->forceFill(['is_monitored' => false])->save();

        $rule->update(['is_enabled' => false]);

        $this->assertFalse($rule->fresh()->is_enabled);
    }

    public function test_a_second_all_groups_rule_for_a_trigger_is_refused(): void
    {
        $global = AlertRule::query()->whereNull('telegram_chat_id')->where('trigger', 'incident_flagged')->first()
            ?? AlertRule::query()->create(['trigger' => 'incident_flagged']);

        try {
            AlertRule::query()->create(['trigger' => 'incident_flagged']);
            $this->fail('a second all-groups rule was saved');
        } catch (ValidationException $refused) {
            $this->assertArrayHasKey('trigger', $refused->errors());
        }

        $this->assertSame(1, AlertRule::query()->whereNull('telegram_chat_id')->where('trigger', 'incident_flagged')->count());
        $this->assertNotNull($global->fresh());
    }

    public function test_enabled_at_is_stamped_on_each_enabling_and_on_nothing_else(): void
    {
        $chat = $this->makeGroup();
        $rule = AlertRule::query()->create(['trigger' => 'bot_not_admin', 'telegram_chat_id' => $chat->id]);
        $this->assertNull($rule->enabled_at);

        Carbon::setTestNow('2026-11-15 08:00:00');
        $rule->update(['is_enabled' => true]);
        $first = $rule->fresh()->enabled_at;
        $this->assertTrue($first->equalTo(Carbon::parse('2026-11-15 08:00:00')));

        // Another edit while enabled: no new stamp.
        Carbon::setTestNow('2026-11-15 09:00:00');
        $rule->update(['quiet_hours' => [['from' => '22:00', 'to' => '06:00']]]);
        $this->assertTrue($rule->fresh()->enabled_at->equalTo($first));

        // Disabling keeps the last stamp; enabling again stamps anew.
        $rule->update(['is_enabled' => false]);
        $this->assertTrue($rule->fresh()->enabled_at->equalTo($first));
        Carbon::setTestNow('2026-11-15 10:00:00');
        $rule->update(['is_enabled' => true]);
        $this->assertTrue($rule->fresh()->enabled_at->equalTo(Carbon::parse('2026-11-15 10:00:00')));

        Carbon::setTestNow();
    }

    public function test_enabling_from_the_edit_page_stamps_enabled_at(): void
    {
        $chat = $this->makeGroup();
        $rule = AlertRule::query()->create(['trigger' => 'group_silent', 'telegram_chat_id' => $chat->id, 'threshold_s' => 3600]);

        Livewire::test(EditAlertRule::class, ['record' => $rule->getRouteKey()])
            ->assertFormSet(['threshold_s' => '60'])
            ->fillForm(['is_enabled' => true])
            ->call('save')
            ->assertHasNoFormErrors();

        $rule->refresh();
        $this->assertTrue($rule->is_enabled);
        $this->assertNotNull($rule->enabled_at);
        $this->assertSame(3600, $rule->threshold_s);
        $this->assertSame('group_silent', $rule->trigger);
    }

    public function test_a_disabled_group_rule_may_sit_beside_an_enabled_all_groups_rule(): void
    {
        $chat = $this->makeGroup();
        $global = AlertRule::query()->whereNull('telegram_chat_id')->where('trigger', 'bot_not_admin')->first()
            ?? AlertRule::query()->create(['trigger' => 'bot_not_admin']);
        $global->update(['is_enabled' => true]);

        Livewire::test(CreateAlertRule::class)
            ->fillForm(['trigger' => 'bot_not_admin', 'telegram_chat_id' => $chat->id, 'is_enabled' => false])
            ->call('create')
            ->assertHasNoFormErrors();

        $muting = AlertRule::query()->where('telegram_chat_id', $chat->id)->sole();
        $this->assertFalse($muting->is_enabled);

        Livewire::test(ListAlertRules::class)
            ->assertCanSeeTableRecords([$muting])
            ->assertTableColumnStateSet('is_enabled', false, $muting)
            ->assertTableColumnStateSet('scope', 'Alerts Test Group', $muting);
    }

    public function test_nothing_on_the_resource_deletes_a_rule(): void
    {
        $chat = $this->makeGroup();
        $rule = AlertRule::query()->create(['trigger' => 'bot_not_admin', 'telegram_chat_id' => $chat->id]);

        Livewire::test(ListAlertRules::class)
            ->assertTableActionDoesNotExist('delete', record: $rule)
            ->assertTableBulkActionDoesNotExist('delete');
        Livewire::test(EditAlertRule::class, ['record' => $rule->getRouteKey()])
            ->assertActionDoesNotExist('delete');

        $this->assertTrue(AlertRuleResource::hasPage('edit'));
        $this->assertNotNull($rule->fresh());
    }

    public function test_a_rule_that_has_fired_cannot_be_deleted(): void
    {
        $chat = $this->makeGroup();
        $ruleId = $this->seedRule($chat, 'bot_not_admin');
        $this->seedAlert($ruleId, $chat, ['subject_type' => 'chat', 'subject_id' => $chat->id]);

        try {
            AlertRule::query()->findOrFail($ruleId)->delete();
            $this->fail('a fired rule was deleted');
        } catch (LogicException) {
            // refused
        }

        $this->assertTrue(DB::table('alert_rules')->where('id', $ruleId)->exists());
    }
}
