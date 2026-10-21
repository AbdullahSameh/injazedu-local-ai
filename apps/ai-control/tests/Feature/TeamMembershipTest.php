<?php

namespace Tests\Feature;

use App\Models\MembershipRefused;
use App\Models\Moderator;
use App\Models\ModeratorGroupAssignment;
use App\Models\TelegramChat;
use App\Models\TelegramUser;
use Illuminate\Foundation\Testing\DatabaseTransactions;
use Tests\TestCase;

/**
 * TG-M2.1's team writes through the Eloquent model (`specs/012-tg-m2-1-group-teams/contracts/
 * group-teams.md` T1-T6) — the panel is the writer, and Laravel's `now()` is evaluated per call, so
 * this is where the PHP-side hazard of `contracts/moderator-ownership.md` §2 / D-TG-47 lives. It
 * replaces TG-M2's single-owner handover test: T047's "no hole, no overlap" now holds for one named
 * member of a team.
 */
class TeamMembershipTest extends TestCase
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

    private function refusalReason(callable $write): ?string
    {
        try {
            $write();
        } catch (MembershipRefused $refused) {
            return $refused->reason;
        }

        return null;
    }

    public function test_two_members_can_be_current_and_both_are_on_the_team(): void
    {
        $chat = $this->makeChat();
        $a = $this->makeModerator('A');
        $b = $this->makeModerator('B');

        $first = ModeratorGroupAssignment::addMember($chat->id, $a->id);
        $second = ModeratorGroupAssignment::addMember($chat->id, $b->id);

        $this->assertNull($first->refresh()->valid_to);
        $this->assertSame(
            [min($a->id, $b->id), max($a->id, $b->id)],
            ModeratorGroupAssignment::teamAt($chat->id, $second->valid_from),
        );
        $this->assertSame(2, $chat->currentMemberships()->count());
    }

    public function test_replace_leaves_no_hole_and_no_overlap_and_touches_only_that_member(): void
    {
        $chat = $this->makeChat();
        $a = $this->makeModerator('A');
        $b = $this->makeModerator('B');
        $c = $this->makeModerator('C');
        $keep = ModeratorGroupAssignment::addMember($chat->id, $a->id);
        $incumbent = ModeratorGroupAssignment::addMember($chat->id, $b->id);

        $successor = $incumbent->replaceWith($c->id, 'covering while on leave');

        $incumbent->refresh();
        // (a) the incumbent's valid_to and the successor's valid_from are the identical value.
        $this->assertTrue($incumbent->valid_to->eq($successor->valid_from));
        // (b) exactly the remaining member and the successor cover that exact instant.
        $this->assertSame(
            [min($a->id, $c->id), max($a->id, $c->id)],
            ModeratorGroupAssignment::teamAt($chat->id, $successor->valid_from),
        );
        $this->assertNull($keep->refresh()->valid_to);
        $this->assertSame('covering while on leave', $successor->note);
    }

    public function test_end_closes_one_membership_once(): void
    {
        $chat = $this->makeChat();
        $membership = ModeratorGroupAssignment::addMember($chat->id, $this->makeModerator('A')->id);

        $this->assertTrue($membership->end());
        $this->assertFalse($membership->end());
        $this->assertNotNull($membership->valid_to);
        $this->assertSame(0, $chat->currentMemberships()->count());
    }

    public function test_the_t4_refusals_write_nothing(): void
    {
        $chat = $this->makeChat();
        $moderator = $this->makeModerator('A');
        ModeratorGroupAssignment::addMember($chat->id, $moderator->id);

        $this->assertSame('overlap', $this->refusalReason(
            fn () => ModeratorGroupAssignment::addMember($chat->id, $moderator->id)
        ));
        $this->assertSame('future', $this->refusalReason(
            fn () => ModeratorGroupAssignment::addMember($this->makeChat()->id, $moderator->id, now()->addHour())
        ));
        $this->assertSame('before_declared', $this->refusalReason(
            fn () => ModeratorGroupAssignment::addMember(
                $this->makeChat()->id,
                $moderator->id,
                $moderator->created_at->copy()->subDay(),
            )
        ));

        $inactive = $this->makeModerator('Inactive');
        $inactive->forceFill(['is_active' => false])->save();
        $this->assertSame('inactive', $this->refusalReason(
            fn () => ModeratorGroupAssignment::addMember($chat->id, $inactive->id)
        ));

        $this->assertSame(1, ModeratorGroupAssignment::query()->where('telegram_chat_id', $chat->id)->count());
    }

    public function test_a_backdated_membership_counts_from_its_since(): void
    {
        $chat = $this->makeChat();
        $moderator = $this->makeModerator('A');
        $since = now()->subSeconds(30);
        $moderator->forceFill(['created_at' => now()->subDay()])->save();

        $membership = ModeratorGroupAssignment::addMember($chat->id, $moderator->id, $since);

        $this->assertTrue($membership->valid_from->eq($since->copy()->utc()));
        $this->assertSame([$moderator->id], ModeratorGroupAssignment::teamAt($chat->id, $since));
        $this->assertSame([], ModeratorGroupAssignment::teamAt($chat->id, $since->copy()->subSecond()));
    }

    public function test_deactivating_a_moderator_ends_every_current_membership_at_one_instant(): void
    {
        $leaving = $this->makeModerator('Leaving');
        $staying = $this->makeModerator('Staying');
        $chatOne = $this->makeChat();
        $chatTwo = $this->makeChat();
        $one = ModeratorGroupAssignment::addMember($chatOne->id, $leaving->id);
        $two = ModeratorGroupAssignment::addMember($chatTwo->id, $leaving->id);
        $colleague = ModeratorGroupAssignment::addMember($chatOne->id, $staying->id);

        $leaving->update(['is_active' => false]);

        $this->assertNotNull($one->refresh()->valid_to);
        $this->assertTrue($one->valid_to->eq($two->refresh()->valid_to));
        $this->assertNull($colleague->refresh()->valid_to);
    }
}
