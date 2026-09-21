<?php

namespace Tests\Feature;

use App\Models\Moderator;
use App\Models\ModeratorGroupAssignment;
use App\Models\TelegramChat;
use App\Models\TelegramUser;
use Illuminate\Foundation\Testing\DatabaseTransactions;
use Tests\TestCase;

/**
 * T047's two assertions, through the Eloquent model rather than the Python path — the panel is
 * the writer, and Laravel's `now()` is evaluated per call, so this is where the PHP-side hazard
 * of `contracts/moderator-ownership.md` §2 / D-TG-47 (research Finding 2) actually lives.
 */
class AssignmentHandoverTest extends TestCase
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

    private function makeModerator(string $displayName): Moderator
    {
        $identity = TelegramUser::forceCreate([
            'tg_user_id' => random_int(10_000_000, 2_000_000_000),
            'is_bot' => false,
        ]);

        return Moderator::create([
            'telegram_user_id' => $identity->id,
            'display_name' => $displayName,
        ]);
    }

    public function test_handover_leaves_no_hole_and_no_overlap(): void
    {
        $chat = $this->makeChat();
        $incumbent = $this->makeModerator('Incumbent');
        $successor = $this->makeModerator('Successor');

        $incumbentAssignment = ModeratorGroupAssignment::handover($chat->id, $incumbent->id);
        $successorAssignment = ModeratorGroupAssignment::handover($chat->id, $successor->id);

        $incumbentAssignment->refresh();

        // (a) the incumbent's valid_to and the successor's valid_from are the identical value.
        $this->assertTrue($incumbentAssignment->valid_to->eq($successorAssignment->valid_from));

        // (b) exactly one owner covers that exact instant.
        $at = $successorAssignment->valid_from;
        $coveringCount = ModeratorGroupAssignment::query()
            ->responsibleAt($chat->id, $at)
            ->count();
        $this->assertSame(1, $coveringCount);

        $owner = ModeratorGroupAssignment::query()->responsibleAt($chat->id, $at)->first();
        $this->assertSame($successor->id, $owner->moderator_id);
    }

    public function test_a_second_handover_call_closes_the_first_before_opening_the_second(): void
    {
        $chat = $this->makeChat();
        $a = $this->makeModerator('A');
        $b = $this->makeModerator('B');
        $c = $this->makeModerator('C');

        $first = ModeratorGroupAssignment::handover($chat->id, $a->id);
        ModeratorGroupAssignment::handover($chat->id, $b->id);
        ModeratorGroupAssignment::handover($chat->id, $c->id);

        $first->refresh();
        $this->assertNotNull($first->valid_to);

        $currentCount = ModeratorGroupAssignment::query()
            ->where('telegram_chat_id', $chat->id)
            ->currentPrimary()
            ->count();
        $this->assertSame(1, $currentCount);

        $current = ModeratorGroupAssignment::query()
            ->where('telegram_chat_id', $chat->id)
            ->currentPrimary()
            ->first();
        $this->assertSame($c->id, $current->moderator_id);
    }

    public function test_opening_a_first_owner_closes_zero_rows(): void
    {
        $chat = $this->makeChat();
        $moderator = $this->makeModerator('First Owner');

        $assignment = ModeratorGroupAssignment::handover($chat->id, $moderator->id);

        $this->assertNull($assignment->valid_to);
        $this->assertSame($moderator->id, $assignment->moderator_id);
    }
}
