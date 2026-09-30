<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
use LogicException;

/**
 * One message the classifier reached but that produced no prediction — an exclusion or a failure
 * (`data-model.md` §3, `contracts/classification-pipeline.md` §3, §8). Appended, never revised:
 * `booted()` below throws from `tinker` too, mirroring `ModerationAction::booted()` (D-TG-147).
 *
 * The table is owned by Alembic — this model never migrates it (config/database.php: "Alembic
 * owns this schema").
 */
class MessageClassificationAttempt extends Model
{
    protected $table = 'message_classification_attempts';

    public $timestamps = false;

    protected function casts(): array
    {
        return [
            'created_at' => 'datetime',
        ];
    }

    public function modelProfile(): BelongsTo
    {
        return $this->belongsTo(ModelProfile::class, 'model_profile_id');
    }

    protected static function booted(): void
    {
        static::updating(function (): void {
            throw new LogicException(
                'message_classification_attempts is immutable — an attempt is never updated'
            );
        });

        static::deleting(function (): void {
            throw new LogicException(
                'message_classification_attempts is immutable — an attempt is never deleted'
            );
        });
    }
}
