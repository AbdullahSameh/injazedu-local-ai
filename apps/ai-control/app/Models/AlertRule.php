<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
use Illuminate\Database\Eloquent\Relations\HasMany;
use Illuminate\Validation\ValidationException;
use LogicException;

/**
 * One alert rule (TG-M6, `specs/013-tg-m6-alerts/data-model.md` §2, `contracts/alerting.md` §2).
 * Rules are operator data: nothing is seeded and no threshold lives in code (R1, FR-510).
 *
 * The table is owned by Alembic — this model never migrates it. `violations()` mirrors R1-R8 so a
 * refusal reads as a sentence before the database's CHECKs ever see the row; `booted()` applies
 * it on every save, from `tinker` too, and stamps `enabled_at` on each change from disabled to
 * enabled (R8, FR-515). A rule that has fired is never deleted: `deleting` throws, and the
 * `alerts` foreign key's `RESTRICT` backs it (D-TG-212, FR-514).
 */
class AlertRule extends Model
{
    protected $table = 'alert_rules';

    /** R2: the five triggers, with their English labels (translated on read). */
    public const TRIGGERS = [
        'question_waiting' => 'Question waiting',
        'incident_flagged' => 'Incident flagged',
        'incident_unhandled' => 'Incident unhandled',
        'group_silent' => 'Group silent',
        'bot_not_admin' => 'Bot not administrator',
    ];

    /** R3: a threshold is required for these and forbidden for the others. */
    public const THRESHOLD_TRIGGERS = ['question_waiting', 'incident_unhandled', 'group_silent'];

    /** R4: filters are allowed only on the two incident triggers. */
    public const FILTER_TRIGGERS = ['incident_flagged', 'incident_unhandled'];

    /** R4: `low < medium < high`. */
    public const SEVERITIES = ['low', 'medium', 'high'];

    /** `ck_incident_category`. */
    public const CATEGORIES = ['SPAM_OR_AD', 'ABUSE', 'OTHER'];

    /** `moderation_incidents.source`. */
    public const OPENERS = ['rule', 'ai', 'operator'];

    private const HHMM = '/^([01]\d|2[0-3]):[0-5]\d$/';

    private const SMALLINT_MAX = 32767;

    private const INTEGER_MAX = 2147483647;

    protected $fillable = [
        'trigger',
        'telegram_chat_id',
        'threshold_s',
        'min_severity',
        'categories',
        'openers',
        'repeat_every_s',
        'max_repeats',
        'quiet_hours',
        'is_enabled',
    ];

    protected $attributes = [
        'quiet_hours' => '[]',
        'is_enabled' => false,
    ];

    protected function casts(): array
    {
        return [
            'telegram_chat_id' => 'integer',
            'threshold_s' => 'integer',
            'categories' => 'array',
            'openers' => 'array',
            'repeat_every_s' => 'integer',
            'max_repeats' => 'integer',
            'quiet_hours' => 'array',
            'is_enabled' => 'boolean',
            'enabled_at' => 'datetime',
            'updated_by_user_id' => 'integer',
        ];
    }

    protected static function booted(): void
    {
        static::saving(function (AlertRule $rule): void {
            // An empty selection means "any", as NULL does (R4); an empty JSON array would match
            // nothing in the evaluator.
            foreach (['categories', 'openers'] as $filter) {
                if ($rule->{$filter} === []) {
                    $rule->{$filter} = null;
                }
            }
            $rule->quiet_hours = array_values($rule->quiet_hours ?? []);

            $violations = self::violations(
                $rule->comparable(),
                $rule->exists ? $rule->getKey() : null,
                chatChanged: ! $rule->exists || $rule->isDirty('telegram_chat_id'),
            );
            if ($violations !== []) {
                throw ValidationException::withMessages($violations);
            }

            // R8: stamped on each change from disabled to enabled, never on another save.
            if ($rule->is_enabled && (! $rule->exists || ! $rule->getOriginal('is_enabled'))) {
                $rule->enabled_at = now();
            }
            if (auth()->check()) {
                $rule->updated_by_user_id = (int) auth()->id();
            }
        });

        static::deleting(function (AlertRule $rule): void {
            if ($rule->alerts()->exists()) {
                throw new LogicException('an alert rule that has fired is never deleted; disable it');
            }
        });
    }

    public function chat(): BelongsTo
    {
        return $this->belongsTo(TelegramChat::class, 'telegram_chat_id');
    }

    public function alerts(): HasMany
    {
        return $this->hasMany(Alert::class, 'alert_rule_id');
    }

    public static function triggerLabel(?string $trigger): string
    {
        return isset(self::TRIGGERS[$trigger]) ? __(self::TRIGGERS[$trigger]) : (string) $trigger;
    }

    /**
     * Every R1-R8 refusal for a rule's would-be values, keyed by attribute. `$ignoreId` is the
     * rule itself on an edit, so it never collides with its own scope. A group must be monitored
     * when it is chosen; a rule already on a group that has since stopped being measured can
     * still be edited or disabled.
     *
     * @param  array<string, mixed>  $rule
     * @return array<string, string>
     */
    public static function violations(array $rule, ?int $ignoreId = null, bool $chatChanged = true): array
    {
        $errors = [];
        $trigger = $rule['trigger'] ?? null;
        $chatId = $rule['telegram_chat_id'] ?? null;

        if (! array_key_exists((string) $trigger, self::TRIGGERS)) {
            return ['trigger' => __('Choose a trigger.')];
        }

        $threshold = $rule['threshold_s'] ?? null;
        if (in_array($trigger, self::THRESHOLD_TRIGGERS, true)) {
            if ($threshold === null) {
                $errors['threshold_s'] = __('This trigger needs a threshold.');
            } elseif ((int) $threshold <= 0 || (int) $threshold > self::INTEGER_MAX) {
                $errors['threshold_s'] = __('The threshold must be a positive number of minutes.');
            }
        } elseif ($threshold !== null) {
            $errors['threshold_s'] = __('This trigger takes no threshold.');
        }

        $filters = ['min_severity', 'categories', 'openers'];
        if (! in_array($trigger, self::FILTER_TRIGGERS, true)) {
            foreach ($filters as $filter) {
                if (($rule[$filter] ?? null) !== null) {
                    $errors[$filter] = __('Filters apply only to the two incident triggers.');
                }
            }
        } else {
            $severity = $rule['min_severity'] ?? null;
            if ($severity !== null && ! in_array($severity, self::SEVERITIES, true)) {
                $errors['min_severity'] = __('Choose low, medium or high.');
            }
            foreach (['categories' => self::CATEGORIES, 'openers' => self::OPENERS] as $filter => $allowed) {
                $chosen = $rule[$filter] ?? null;
                if ($chosen !== null && (! is_array($chosen) || array_diff($chosen, $allowed) !== [])) {
                    $errors[$filter] = __('Choose from the listed values only.');
                }
            }
        }

        $every = $rule['repeat_every_s'] ?? null;
        $max = $rule['max_repeats'] ?? null;
        if (($every === null) !== ($max === null)) {
            $errors[$every === null ? 'repeat_every_s' : 'max_repeats'] =
                __('Set both the repeat interval and the number of repeats, or neither.');
        } elseif ($every !== null) {
            if ((int) $every <= 0 || (int) $every > self::INTEGER_MAX) {
                $errors['repeat_every_s'] = __('The repeat interval must be a positive number of minutes.');
            }
            if ((int) $max <= 0 || (int) $max > self::SMALLINT_MAX) {
                $errors['max_repeats'] = __('The number of repeats must be a positive whole number.');
            }
        }

        $windows = $rule['quiet_hours'] ?? [];
        if (! is_array($windows)) {
            $errors['quiet_hours'] = __('Each quiet-hours window needs a start and an end as HH:MM, and they must differ.');
        } else {
            foreach ($windows as $window) {
                $from = is_array($window) ? ($window['from'] ?? null) : null;
                $to = is_array($window) ? ($window['to'] ?? null) : null;
                if (! is_string($from) || ! is_string($to)
                    || ! preg_match(self::HHMM, $from) || ! preg_match(self::HHMM, $to) || $from === $to) {
                    $errors['quiet_hours'] = __('Each quiet-hours window needs a start and an end as HH:MM, and they must differ.');
                    break;
                }
            }
        }

        if ($chatId !== null && $chatChanged) {
            $monitored = TelegramChat::query()->whereKey($chatId)->value('is_monitored');
            if ($monitored !== true) {
                $errors['telegram_chat_id'] = __('A group rule can only be set on a measured group.');
            }
        }

        // R5 / FR-513: one all-groups rule per trigger, one rule per trigger per group.
        $taken = self::query()
            ->where('trigger', $trigger)
            ->when(
                $chatId === null,
                fn ($query) => $query->whereNull('telegram_chat_id'),
                fn ($query) => $query->where('telegram_chat_id', $chatId),
            )
            ->when($ignoreId !== null, fn ($query) => $query->whereKeyNot($ignoreId))
            ->exists();
        if ($taken) {
            $errors[$chatId === null ? 'trigger' : 'telegram_chat_id'] = $chatId === null
                ? __('An all-groups rule for this trigger already exists. Edit it instead.')
                : __('This group already has a rule for this trigger. Edit it instead.');
        }

        return $errors;
    }

    /**
     * This rule's values as `violations()` reads them.
     *
     * @return array<string, mixed>
     */
    private function comparable(): array
    {
        return [
            'trigger' => $this->trigger,
            'telegram_chat_id' => $this->telegram_chat_id,
            'threshold_s' => $this->threshold_s,
            'min_severity' => $this->min_severity,
            'categories' => $this->categories,
            'openers' => $this->openers,
            'repeat_every_s' => $this->repeat_every_s,
            'max_repeats' => $this->max_repeats,
            'quiet_hours' => $this->quiet_hours,
        ];
    }
}
