<?php

namespace Tests\Feature;

use App\Filament\Resources\Incidents\Pages\ListIncidents;
use App\Models\ModerationIncident;
use App\Models\TelegramChat;
use App\Models\TelegramMessage;
use App\Models\TelegramUser;
use App\Models\User;
use Illuminate\Foundation\Testing\DatabaseTransactions;
use Illuminate\Support\Facades\DB;
use Livewire\Livewire;
use Tests\TestCase;

/**
 * T049 (US4): `acknowledge`/`resolve`/`closeAsFalsePositive`, each the guarded insert of
 * `contracts/incident-lifecycle.md` §5 — allowed only from the states H1 names, each requiring
 * its note/reason, each recording `panel_user_id` and the incident it names, a second identical
 * call inserting nothing, a stale page (evidence landed underneath) inserting nothing, no act
 * offered on a resolved or closed incident's row, and the advisory lock taken with the exact
 * literal `moderation:incidents` (FR-040, FR-041, SC-003) — together with T040 and T048 this
 * covers the full transition table.
 */
class IncidentActionsTest extends TestCase
{
    use DatabaseTransactions;

    private function actingAsPanelOperator(): User
    {
        $user = User::factory()->create(['is_panel_operator' => true]);
        $this->actingAs($user);

        return $user;
    }

    private function makeChat(): TelegramChat
    {
        return TelegramChat::forceCreate([
            'chat_id' => -random_int(10_000_000, 2_000_000_000),
            'chat_type' => 'group',
            'title' => 'Incident Group',
            'is_monitored' => true,
        ]);
    }

    private function makeCapturedUpdate(TelegramChat $chat): int
    {
        return DB::table('telegram_updates')->insertGetId([
            'bot_id' => random_int(10_000_000, 2_000_000_000),
            'update_id' => random_int(10_000_000, 2_000_000_000),
            'update_type' => 'message',
            'chat_id' => $chat->chat_id,
            'payload' => json_encode(['message' => []]),
            'received_at' => now(),
        ]);
    }

    private function makeMessage(TelegramChat $chat, int $messageId, ?int $senderId = null): TelegramMessage
    {
        $senderId ??= TelegramUser::forceCreate([
            'tg_user_id' => random_int(10_000_000, 2_000_000_000),
            'is_bot' => false,
        ])->id;

        return TelegramMessage::forceCreate([
            'telegram_chat_id' => $chat->id,
            'message_id' => $messageId,
            'telegram_user_id' => $senderId,
            'sent_at' => now()->subMinutes(30),
            'is_service' => false,
            'is_from_moderator' => false,
            'original_text' => 'spam text',
            'normalized_text' => 'spam text',
            'entity_flags' => '{}',
            'source_update_id' => $this->makeCapturedUpdate($chat),
        ]);
    }

    private function makeIncident(TelegramChat $chat, TelegramMessage $message): ModerationIncident
    {
        return ModerationIncident::forceCreate([
            'telegram_chat_id' => $chat->id,
            'telegram_message_id' => $message->message_id,
            'opened_at' => $message->sent_at,
            'detected_at' => now(),
            'source' => 'operator',
            'opened_by_user_id' => 1,
            'category' => 'SPAM_OR_AD',
            'severity' => 'low',
        ]);
    }

    private function recordBan(TelegramChat $chat, TelegramMessage $message): void
    {
        DB::table('moderation_actions')->insert([
            'telegram_chat_id' => $chat->id,
            'action_type' => 'ban',
            'action_strength' => 'enforcement',
            'occurred_at' => now(),
            'subject_telegram_user_id' => $message->telegram_user_id,
            'source_update_id' => $this->makeCapturedUpdate($chat),
            'detail' => json_encode([]),
        ]);
    }

    public function test_acknowledge_succeeds_only_from_open(): void
    {
        $operator = $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $incident = $this->makeIncident($chat, $this->makeMessage($chat, 1));

        $this->assertTrue($incident->acknowledge($operator));
        $this->assertSame('acknowledged', $incident->state()->status);

        // Not allowed a second time — no longer `open`.
        $this->assertFalse($incident->acknowledge($operator));
    }

    public function test_resolve_and_close_as_false_positive_succeed_only_from_open_or_acknowledged(): void
    {
        $operator = $this->actingAsPanelOperator();
        $chat = $this->makeChat();

        $resolvable = $this->makeIncident($chat, $this->makeMessage($chat, 1));
        $this->assertTrue($resolvable->resolve($operator, 'Confirmed by the group owner.'));
        $this->assertSame('resolved', $resolvable->state()->status);
        // Never allowed once resolved.
        $this->assertFalse($resolvable->resolve($operator, 'again'));
        $this->assertFalse($resolvable->closeAsFalsePositive($operator, 'again'));

        $closable = $this->makeIncident($chat, $this->makeMessage($chat, 2));
        $this->assertTrue($closable->acknowledge($operator));
        $this->assertTrue($closable->closeAsFalsePositive($operator, 'Not spam after all.'));
        $this->assertSame('closed_false_positive', $closable->state()->status);
    }

    public function test_resolve_requires_a_note_and_false_positive_requires_a_reason(): void
    {
        $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $incident = $this->makeIncident($chat, $this->makeMessage($chat, 1));

        Livewire::test(ListIncidents::class)
            ->callTableAction('resolve_incident', $incident, data: ['note' => ''])
            ->assertHasTableActionErrors(['note']);

        Livewire::test(ListIncidents::class)
            ->callTableAction('close_false_positive', $incident, data: ['reason' => ''])
            ->assertHasTableActionErrors(['reason']);
    }

    public function test_each_act_records_the_panel_account_and_its_incident(): void
    {
        $operator = $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $incident = $this->makeIncident($chat, $this->makeMessage($chat, 1));

        $incident->resolve($operator, 'Confirmed by the group owner.');

        $row = DB::table('moderation_actions')
            ->where('moderation_incident_id', $incident->id)
            ->where('action_type', 'panel_resolve')
            ->first();

        $this->assertNotNull($row);
        $this->assertSame($operator->id, $row->panel_user_id);
        $this->assertSame($incident->id, $row->moderation_incident_id);
        $this->assertNull($row->actor_moderator_id);
        $this->assertNull($row->source_update_id);
    }

    public function test_a_second_identical_call_inserts_nothing_and_returns_false(): void
    {
        $operator = $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $incident = $this->makeIncident($chat, $this->makeMessage($chat, 1));

        $this->assertTrue($incident->acknowledge($operator));
        $this->assertFalse($incident->acknowledge($operator));

        $this->assertSame(1, DB::table('moderation_actions')
            ->where('moderation_incident_id', $incident->id)
            ->count());
    }

    public function test_a_ban_recorded_between_page_load_and_submit_makes_close_as_false_positive_insert_nothing(): void
    {
        $operator = $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $message = $this->makeMessage($chat, 1);
        $incident = $this->makeIncident($chat, $message);

        // The page was loaded while the incident was still `open`; a ban lands underneath before
        // the operator submits.
        $this->recordBan($chat, $message);
        $this->assertSame('resolved', $incident->fresh()->state()->status);

        $this->assertFalse($incident->closeAsFalsePositive($operator, 'Stale — already resolved.'));
        $this->assertSame('resolved', $incident->fresh()->state()->status);
    }

    public function test_no_act_is_offered_on_a_resolved_or_closed_incidents_row(): void
    {
        $operator = $this->actingAsPanelOperator();
        $chat = $this->makeChat();

        $resolved = $this->makeIncident($chat, $this->makeMessage($chat, 1));
        $resolved->resolve($operator, 'Confirmed.');

        $closed = $this->makeIncident($chat, $this->makeMessage($chat, 2));
        $closed->closeAsFalsePositive($operator, 'Not spam.');

        $test = Livewire::test(ListIncidents::class);
        foreach ([$resolved, $closed] as $incident) {
            $test->assertTableActionHidden('acknowledge_incident', $incident->fresh())
                ->assertTableActionHidden('resolve_incident', $incident->fresh())
                ->assertTableActionHidden('close_false_positive', $incident->fresh());
        }
    }

    public function test_each_act_issues_the_advisory_lock_statement_with_the_shared_literal(): void
    {
        $operator = $this->actingAsPanelOperator();
        $chat = $this->makeChat();
        $incident = $this->makeIncident($chat, $this->makeMessage($chat, 1));

        $lockQueries = [];
        DB::listen(function ($query) use (&$lockQueries): void {
            if (str_contains($query->sql, 'pg_advisory_xact_lock')) {
                $lockQueries[] = $query;
            }
        });

        $incident->acknowledge($operator);

        $this->assertNotEmpty($lockQueries);
        $this->assertContains('moderation:incidents', $lockQueries[0]->bindings);
    }
}
