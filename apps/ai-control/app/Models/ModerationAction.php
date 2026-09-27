<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use LogicException;

/**
 * One observed act — append-only evidence (`data-model.md` §2, D-TG-113). Rows are **never**
 * updated and never deleted (FR-018, lifecycle contract V14, N7): `booted()` below throws from
 * `tinker` too, not only from a Filament action, because the invariant every derived state in
 * `moderation_incident_state` depends on is that once a row exists, it always exists exactly as
 * written.
 *
 * The table is owned by Alembic — this model never migrates it (config/database.php: "Alembic
 * owns this schema").
 */
class ModerationAction extends Model
{
    protected $table = 'moderation_actions';

    public $timestamps = false;

    protected function casts(): array
    {
        return [
            'occurred_at' => 'datetime',
            'created_at' => 'datetime',
            'actor_is_anonymous' => 'boolean',
            'detail' => 'array',
        ];
    }

    protected static function booted(): void
    {
        static::updating(function (): void {
            throw new LogicException('moderation_actions is append-only');
        });

        static::deleting(function (): void {
            throw new LogicException('moderation_actions is append-only');
        });
    }
}
