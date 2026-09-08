<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Support\Facades\DB;
use Illuminate\Validation\ValidationException;

/**
 * One row = one model, at one endpoint, for one role (data-model.md §1).
 *
 * The table is owned by Alembic revision 0002_model_gateway — this model never migrates it
 * (config/database.php: "Alembic owns this schema"). The two invariants below are enforced
 * here, at the model layer, so they hold regardless of entry point (panel, tinker, a future
 * artisan command) — not only when a Filament form happens to be in front of them.
 */
class ModelProfile extends Model
{
    protected $table = 'model_profiles';

    protected $fillable = [
        'name',
        'provider',
        'base_url',
        'model',
        'role',
        'params',
        'dim',
        'api_key_env',
        'is_active',
        'notes',
    ];

    protected function casts(): array
    {
        return [
            'params' => 'array',
            'dim' => 'integer',
            'is_active' => 'boolean',
        ];
    }

    /**
     * Wrap every save in a transaction: the incumbent's deactivation (below) and this row's
     * own write must commit or roll back together (FR-043).
     */
    public function save(array $options = []): bool
    {
        return DB::transaction(fn () => parent::save($options));
    }

    protected static function booted(): void
    {
        static::saving(function (ModelProfile $profile): void {
            if ($profile->exists && $profile->isDirty('dim')) {
                throw ValidationException::withMessages([
                    'dim' => "A profile's vector width is immutable once set — "
                        .'create a new profile instead of editing this one (FR-017).',
                ]);
            }

            if (! $profile->isDirty('is_active')) {
                return;
            }

            $othersForRole = static::query()
                ->where('role', $profile->role)
                ->where('id', '!=', $profile->id ?? 0);

            if ($profile->is_active) {
                // Activating this row deactivates the incumbent, in the same transaction
                // as this row's own save (D-36's partial unique index backstops it in the
                // database; this makes the panel honour it too).
                (clone $othersForRole)->where('is_active', true)->update(['is_active' => false]);

                return;
            }

            // Only a genuine deactivation of a previously-active row can "leave the role
            // with no active profile" — a brand-new row or one that was already inactive
            // isn't removing anything (every attribute reads as "dirty" on a fresh create).
            $wasActive = $profile->exists && (bool) $profile->getOriginal('is_active');
            if ($wasActive && ! (clone $othersForRole)->where('is_active', true)->exists()) {
                throw ValidationException::withMessages([
                    'is_active' => "Refusing to leave role '{$profile->role}' with no active "
                        .'profile — activate a replacement first (FR-011).',
                ]);
            }
        });
    }
}
