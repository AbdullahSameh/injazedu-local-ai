<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
use LogicException;

/**
 * One model's claim about one message (`data-model.md` §2, `contracts/classification-pipeline.md`
 * §5). **A prediction is a claim, recorded once with its provenance and never changed**: `booted()`
 * below throws from `tinker` too, not only from a Filament action, mirroring
 * `ModerationAction::booted()` (D-TG-147).
 *
 * The table is owned by Alembic — this model never migrates it (config/database.php: "Alembic
 * owns this schema"). Routes and eligibility are **read** from the stored columns below, never
 * computed here (`contracts/classification-pipeline.md` §3, §6, N7).
 */
class MessageClassification extends Model
{
    protected $table = 'message_classifications';

    public $timestamps = false;

    protected function casts(): array
    {
        return [
            'needs_response' => 'boolean',
            'needs_moderation' => 'boolean',
            'confidence' => 'decimal:3',
            'confidence_floor' => 'decimal:3',
            'incident_threshold' => 'decimal:3',
            'is_current' => 'boolean',
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
            throw new LogicException('message_classifications is immutable — a prediction is never updated');
        });

        static::deleting(function (): void {
            throw new LogicException('message_classifications is immutable — a prediction is never deleted');
        });
    }
}
