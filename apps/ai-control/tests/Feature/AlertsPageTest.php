<?php

namespace Tests\Feature;

use App\Filament\Pages\Alerts;
use App\Filament\Resources\Incidents\IncidentResource;
use App\Models\Alert;
use App\Models\Moderator;
use App\Models\TelegramChat;
use App\Models\TelegramUser;
use App\Models\User;
use Illuminate\Foundation\Testing\DatabaseTransactions;
use Illuminate\Support\Carbon;
use Illuminate\Support\Facades\DB;
use Livewire\Livewire;
use Tests\Feature\Concerns\SeedsAlerts;
use Tests\TestCase;

/**
 * T543 (TG-M6, US4; `alerting.md` S3, FR-572): the Alerts history. Each row reads its rule,
 * trigger, group, subject, repeat, status with its reason or error category, fired, delivered and
 * presses; the filters narrow by rule, trigger, group, status and `Asia/Riyadh` day; ten to a page,
 * newest first; nothing on the page writes. Rows are scoped by this test's own rule or group,
 * since the database is shared.
 */
class AlertsPageTest extends TestCase
{
    use DatabaseTransactions;
    use SeedsAlerts;

    private TelegramChat $chat;

    protected function setUp(): void
    {
        parent::setUp();
        $this->actingAs(User::factory()->create(['is_panel_operator' => true]));
        $this->chat = $this->makeGroup(['title' => 'History Group']);
    }

    private function press(int $alertId, string $kind = 'alert_take'): void
    {
        $identity = TelegramUser::forceCreate(['tg_user_id' => random_int(10_000_000, 2_000_000_000), 'is_bot' => false]);
        $moderator = Moderator::create(['telegram_user_id' => $identity->id, 'display_name' => 'Presser']);
        DB::table('moderation_actions')->insert([
            'telegram_chat_id' => $this->chat->id,
            'action_type' => $kind,
            'occurred_at' => now(),
            'actor_telegram_user_id' => $identity->id,
            'actor_moderator_id' => $moderator->id,
            'alert_id' => $alertId,
            'source_update_id' => $this->seedCallbackUpdate(),
            'detail' => json_encode([]),
        ]);
    }

    public function test_each_row_reads_its_status_reason_repeat_subject_and_presses(): void
    {
        $ruleId = $this->seedRule($this->chat, 'question_waiting', ['repeat_every_s' => 600, 'max_repeats' => 3]);
        $sent = $this->seedAlert($ruleId, $this->chat, ['delivery_status' => 'sent']);
        $this->press($sent);
        $this->press($sent);
        $repeat = $this->seedAlert($ruleId, $this->chat, [
            'repeat_index' => 2,
            'rule_values' => json_encode(['max_repeats' => 3]),
            'delivery_status' => 'not_sent',
            'not_sent_reason' => 'no_destination',
        ]);
        $failed = $this->seedAlert($ruleId, $this->chat, [
            'delivery_status' => 'failed',
            'last_error_category' => 'telegram_outcome_unknown',
        ]);
        $incidentRule = $this->seedRule($this->chat, 'incident_flagged');
        $incident = $this->seedAlert($incidentRule, $this->chat, ['subject_type' => 'incident', 'subject_id' => 424242]);

        Livewire::test(Alerts::class)
            ->filterTable('group', $this->chat->id)
            ->assertCanSeeTableRecords(Alert::query()->whereKey([$sent, $repeat, $failed, $incident])->get())
            ->assertTableColumnFormattedStateSet('delivery_status', __('Sent'), $sent)
            ->assertTableColumnFormattedStateSet('delivery_status', __('Not sent').' · '.__('No destination'), $repeat)
            ->assertTableColumnFormattedStateSet('delivery_status', __('Failed').' · telegram_outcome_unknown', $failed)
            ->assertTableColumnStateSet('repeat', __('First'), $sent)
            ->assertTableColumnStateSet('repeat', __(':k of :n', ['k' => 2, 'n' => 3]), $repeat)
            ->assertTableColumnStateSet('acts_count', 2, $sent)
            ->assertTableColumnStateSet('acts_count', 0, $failed)
            ->assertTableColumnStateSet('group', 'History Group', $sent)
            ->assertTableColumnFormattedStateSet('trigger', __('Question waiting'), $sent)
            ->assertTableColumnStateSet('subject', __('Incident #:id', ['id' => 424242]), $incident)
            ->assertSee(IncidentResource::getUrl('view', ['record' => 424242]));
    }

    public function test_the_filters_narrow_by_rule_trigger_status_and_day(): void
    {
        $questions = $this->seedRule($this->chat, 'question_waiting');
        $silence = $this->seedRule($this->chat, 'group_silent');
        $tenth = $this->seedAlert($questions, $this->chat, [
            'delivery_status' => 'sent',
            'fired_at' => Carbon::parse('2026-11-10 12:00', 'Asia/Riyadh')->utc(),
        ]);
        $eleventh = $this->seedAlert($questions, $this->chat, [
            'delivery_status' => 'suppressed',
            // 00:30 in Riyadh on the 11th is still the 10th in UTC.
            'fired_at' => Carbon::parse('2026-11-11 00:30', 'Asia/Riyadh')->utc(),
        ]);
        $quiet = $this->seedAlert($silence, $this->chat, ['subject_type' => 'chat', 'subject_id' => $this->chat->id]);
        $records = fn (array $ids) => Alert::query()->whereKey($ids)->get();

        Livewire::test(Alerts::class)
            ->filterTable('rule', $silence)
            ->assertCanSeeTableRecords($records([$quiet]))
            ->assertCanNotSeeTableRecords($records([$tenth, $eleventh]));

        Livewire::test(Alerts::class)
            ->filterTable('group', $this->chat->id)
            ->filterTable('trigger', 'question_waiting')
            ->assertCanSeeTableRecords($records([$tenth, $eleventh]))
            ->assertCanNotSeeTableRecords($records([$quiet]));

        Livewire::test(Alerts::class)
            ->filterTable('group', $this->chat->id)
            ->filterTable('status', 'suppressed')
            ->assertCanSeeTableRecords($records([$eleventh]))
            ->assertCanNotSeeTableRecords($records([$tenth, $quiet]));

        Livewire::test(Alerts::class)
            ->filterTable('group', $this->chat->id)
            ->filterTable('fired', ['from' => '2026-11-11', 'until' => '2026-11-11'])
            ->assertCanSeeTableRecords($records([$eleventh]))
            ->assertCanNotSeeTableRecords($records([$tenth, $quiet]));
    }

    public function test_ten_to_a_page_newest_first(): void
    {
        $ruleId = $this->seedRule($this->chat);
        $ids = [];
        foreach (range(1, 12) as $minutesAgo) {
            $ids[$minutesAgo] = $this->seedAlert($ruleId, $this->chat, ['fired_at' => now()->subMinutes($minutesAgo)]);
        }
        $newest = Alert::query()->whereKey(array_slice($ids, 0, 10, true))->get();
        $oldest = Alert::query()->whereKey([$ids[11], $ids[12]])->get();

        Livewire::test(Alerts::class)
            ->filterTable('rule', $ruleId)
            ->assertCountTableRecords(12)
            ->assertCanSeeTableRecords($newest, inOrder: true)
            ->assertCanNotSeeTableRecords($oldest)
            ->call('gotoPage', 2)
            ->assertCanSeeTableRecords($oldest)
            ->assertCanNotSeeTableRecords($newest);
    }

    public function test_nothing_on_the_page_writes(): void
    {
        $alertId = $this->seedAlert($this->seedRule($this->chat), $this->chat);
        $alert = Alert::query()->findOrFail($alertId);

        Livewire::test(Alerts::class)
            ->filterTable('group', $this->chat->id)
            ->assertCanSeeTableRecords([$alert])
            ->assertTableActionDoesNotExist('edit', record: $alert)
            ->assertTableActionDoesNotExist('delete', record: $alert)
            ->assertTableBulkActionDoesNotExist('delete');
    }
}
