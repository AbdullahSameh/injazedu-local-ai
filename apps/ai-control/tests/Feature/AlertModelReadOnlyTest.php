<?php

namespace Tests\Feature;

use App\Models\Alert;
use App\Models\AlertRule;
use App\Models\ModerationAction;
use App\Models\Moderator;
use App\Models\TelegramUser;
use Illuminate\Foundation\Testing\DatabaseTransactions;
use Illuminate\Support\Facades\DB;
use LogicException;
use Tests\Feature\Concerns\SeedsAlerts;
use Tests\TestCase;

/**
 * T543 (TG-M6, US4; `alerting.md` S6, D-TG-228): the panel only reads alerts. `Alert` throws on
 * create, update and delete — from `tinker` too — and reaches its rule, its source group and the
 * button acts recorded for it.
 */
class AlertModelReadOnlyTest extends TestCase
{
    use DatabaseTransactions;
    use SeedsAlerts;

    public function test_creating_an_alert_throws(): void
    {
        $chat = $this->makeGroup();
        $ruleId = $this->seedRule($chat);

        $this->expectException(LogicException::class);
        Alert::query()->forceCreate([
            'alert_rule_id' => $ruleId,
            'trigger' => 'question_waiting',
            'telegram_chat_id' => $chat->id,
            'subject_type' => 'attention_item',
            'subject_id' => 1,
            'repeat_index' => 0,
            'dedupe_key' => 'never-written',
            'rule_values' => [],
            'qualified_at' => now(),
        ]);
    }

    public function test_updating_or_deleting_an_alert_throws_and_leaves_it_as_written(): void
    {
        $chat = $this->makeGroup();
        $alertId = $this->seedAlert($this->seedRule($chat), $chat, ['delivery_status' => 'failed', 'last_error_category' => 'telegram_5xx']);
        $alert = Alert::query()->findOrFail($alertId);

        foreach ([
            fn () => $alert->forceFill(['delivery_status' => 'pending'])->save(),
            fn () => $alert->delete(),
        ] as $write) {
            try {
                $write();
                $this->fail('an alert was written from the panel');
            } catch (LogicException) {
                // refused
            }
        }

        $row = DB::table('alerts')->where('id', $alertId)->first();
        $this->assertSame('failed', $row->delivery_status);
        $this->assertSame('telegram_5xx', $row->last_error_category);
    }

    public function test_an_alert_reaches_its_rule_group_and_acts(): void
    {
        $chat = $this->makeGroup(['title' => 'Source group']);
        $ruleId = $this->seedRule($chat);
        $alertId = $this->seedAlert($ruleId, $chat, ['delivery_status' => 'sent']);
        $identity = TelegramUser::forceCreate(['tg_user_id' => random_int(10_000_000, 2_000_000_000), 'is_bot' => false]);
        $moderator = Moderator::create(['telegram_user_id' => $identity->id, 'display_name' => 'Presser']);
        DB::table('moderation_actions')->insert([
            'telegram_chat_id' => $chat->id,
            'action_type' => 'alert_take',
            'occurred_at' => now(),
            'actor_telegram_user_id' => $identity->id,
            'actor_moderator_id' => $moderator->id,
            'alert_id' => $alertId,
            'source_update_id' => $this->seedCallbackUpdate(),
            'detail' => json_encode([]),
        ]);

        $alert = Alert::query()->findOrFail($alertId);

        $this->assertInstanceOf(AlertRule::class, $alert->rule);
        $this->assertSame($ruleId, $alert->rule->id);
        $this->assertSame('Source group', $alert->chat->title);
        $this->assertSame(['alert_take'], $alert->acts->map(fn (ModerationAction $act): string => $act->action_type)->all());
    }
}
