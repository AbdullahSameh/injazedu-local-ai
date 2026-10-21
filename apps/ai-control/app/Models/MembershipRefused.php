<?php

namespace App\Models;

use DomainException;

/**
 * A team-membership write the TG-M2.1 contract refuses (`specs/012-tg-m2-1-group-teams/contracts/
 * group-teams.md` T4-T5), mirroring Python's `MembershipRefusedError`. `reason` is one of
 * `inactive`, `overlap`, `future`, `before_declared` or `not_current`; `message()` is the operator's
 * sentence for it.
 */
class MembershipRefused extends DomainException
{
    public function __construct(public readonly string $reason)
    {
        parent::__construct($reason);
    }

    public function message(): string
    {
        return match ($this->reason) {
            'inactive' => __('This moderator is inactive and cannot join a team.'),
            'overlap' => __('This moderator is already on this group\'s team at that time.'),
            'future' => __('A membership cannot start in the future.'),
            'before_declared' => __('A membership cannot start before the moderator was declared — their earlier messages were never recorded as a moderator\'s.'),
            'not_current' => __('That membership has already ended.'),
            default => $this->reason,
        };
    }
}
