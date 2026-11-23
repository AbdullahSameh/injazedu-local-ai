<?php

namespace Tests\Feature\Concerns;

use App\Models\TelegramChat;
use Illuminate\Support\Facades\DB;

/**
 * TG-M6 fixtures: groups, rules and alerts written straight to the tables, as the Python workers
 * write alerts (`App\Models\Alert` refuses every write). Rules here are group rules on a fresh
 * group, so they never meet an all-groups rule another test left in the shared database.
 */
trait SeedsAlerts
{
    protected function makeGroup(array $overrides = []): TelegramChat
    {
        return TelegramChat::forceCreate(array_merge([
            'chat_id' => -random_int(10_000_000, 2_000_000_000),
            'chat_type' => 'supergroup',
            'title' => 'Alerts Test Group',
            'is_monitored' => true,
            'bot_status' => 'administrator',
        ], $overrides));
    }

    protected function seedRule(TelegramChat $chat, string $trigger = 'question_waiting', array $overrides = []): int
    {
        return DB::table('alert_rules')->insertGetId(array_merge([
            'trigger' => $trigger,
            'telegram_chat_id' => $chat->id,
            'threshold_s' => in_array($trigger, ['question_waiting', 'incident_unhandled', 'group_silent'], true) ? 600 : null,
            'quiet_hours' => '[]',
            'is_enabled' => false,
        ], $overrides));
    }

    /**
     * One alert row. `subject_type` 'chat' gets an episode; 'sent' gets a posted message; a
     * `not_sent` alert needs `not_sent_reason` in `$overrides`.
     */
    protected function seedAlert(int $ruleId, TelegramChat $chat, array $overrides = []): int
    {
        $row = array_merge([
            'alert_rule_id' => $ruleId,
            'trigger' => DB::table('alert_rules')->where('id', $ruleId)->value('trigger'),
            'telegram_chat_id' => $chat->id,
            'subject_type' => 'attention_item',
            'subject_id' => random_int(1, 2_000_000_000),
            'repeat_index' => 0,
            'rule_values' => json_encode(['max_repeats' => null]),
            'qualified_at' => now()->subHour(),
            'fired_at' => now()->subHour(),
            'delivery_status' => 'pending',
        ], $overrides);
        if ($row['subject_type'] === 'chat' && ! array_key_exists('episode_at', $row)) {
            $row['episode_at'] = now()->subHours(2);
        }
        if ($row['delivery_status'] === 'sent') {
            $row += [
                'sent_chat_id' => -random_int(10_000_000, 2_000_000_000),
                'sent_message_id' => random_int(1, 2_000_000_000),
                'delivered_at' => $row['fired_at'],
            ];
        }
        $row['dedupe_key'] ??= $ruleId.':'.$row['subject_type'].':'.$row['subject_id'].':'.$row['repeat_index'].':'.bin2hex(random_bytes(4));

        return DB::table('alerts')->insertGetId($row);
    }

    /** A captured `callback_query` update, for a button act's provenance. */
    protected function seedCallbackUpdate(): int
    {
        return DB::table('telegram_updates')->insertGetId([
            'bot_id' => random_int(10_000_000, 2_000_000_000),
            'update_id' => random_int(10_000_000, 2_000_000_000),
            'update_type' => 'callback_query',
            'chat_id' => null,
            'payload' => json_encode(['callback_query' => []]),
            'received_at' => now(),
        ]);
    }
}
