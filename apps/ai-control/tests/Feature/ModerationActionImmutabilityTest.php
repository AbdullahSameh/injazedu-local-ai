<?php

namespace Tests\Feature;

use App\Models\ModerationAction;
use App\Models\TelegramChat;
use App\Models\TelegramUser;
use Illuminate\Foundation\Testing\DatabaseTransactions;
use Illuminate\Support\Facades\DB;
use LogicException;
use Tests\TestCase;

/**
 * T018 (FR-018, D-TG-113): `moderation_actions` is append-only. `ModerationAction::booted()`
 * throws on `update()` and `delete()` so the invariant holds from `tinker` too, not only from a
 * Filament action — mirroring `ModerationActionImmutabilityTest`'s siblings for
 * `ModelProfile::save()`'s guard.
 */
class ModerationActionImmutabilityTest extends TestCase
{
    use DatabaseTransactions;

    private function makeChat(): TelegramChat
    {
        return TelegramChat::forceCreate([
            'chat_id' => -random_int(10_000_000, 2_000_000_000),
            'chat_type' => 'group',
            'title' => 'Test Group',
            'is_monitored' => true,
        ]);
    }

    private function makeAction(TelegramChat $chat): ModerationAction
    {
        $subject = TelegramUser::forceCreate([
            'tg_user_id' => random_int(10_000_000, 2_000_000_000),
            'is_bot' => false,
        ]);

        $updateId = DB::table('telegram_updates')->insertGetId([
            'bot_id' => random_int(10_000_000, 2_000_000_000),
            'update_id' => random_int(10_000_000, 2_000_000_000),
            'update_type' => 'chat_member',
            'payload' => json_encode([]),
        ]);

        return ModerationAction::forceCreate([
            'telegram_chat_id' => $chat->id,
            'action_type' => 'ban',
            'action_strength' => 'enforcement',
            'occurred_at' => now(),
            'subject_telegram_user_id' => $subject->id,
            'source_update_id' => $updateId,
        ]);
    }

    public function test_creating_a_panel_action_succeeds(): void
    {
        $chat = $this->makeChat();

        $action = $this->makeAction($chat);

        $this->assertDatabaseHas('moderation_actions', ['id' => $action->id, 'action_type' => 'ban']);
    }

    public function test_update_throws_and_leaves_the_row_unchanged(): void
    {
        $chat = $this->makeChat();
        $action = $this->makeAction($chat);
        $originalNote = $action->note;

        $action->note = 'attempted edit';

        $this->expectException(LogicException::class);

        try {
            $action->save();
        } finally {
            $this->assertSame($originalNote, $action->fresh()->note);
        }
    }

    public function test_delete_throws_and_leaves_the_row_in_place(): void
    {
        $chat = $this->makeChat();
        $action = $this->makeAction($chat);

        $this->expectException(LogicException::class);

        try {
            $action->delete();
        } finally {
            $this->assertDatabaseHas('moderation_actions', ['id' => $action->id]);
        }
    }
}
