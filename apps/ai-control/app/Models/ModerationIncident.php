<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
use Illuminate\Support\Collection;
use Illuminate\Support\Facades\DB;
use InvalidArgumentException;

/**
 * One message that needed a moderator to act (`data-model.md` §1, `contracts/incident-lifecycle.md`).
 *
 * The table is owned by Alembic — this model never migrates it (config/database.php: "Alembic
 * owns this schema"). **State is derived by `moderation_incident_evidence` and
 * `moderation_incident_state` and never computed here** (lifecycle contract N6, research
 * Finding 3): there is no `status` column to read or write. `openOn()` (US1) and the three
 * guarded acts — `acknowledge()`, `resolve()`, `closeAsFalsePositive()` (US4) — mirror
 * `ModeratorGroupAssignment::handover()` and `ModelProfile::save()` so every invariant holds from
 * `tinker` too, not only from a Filament action.
 */
class ModerationIncident extends Model
{
    protected $table = 'moderation_incidents';

    public $timestamps = false;

    /**
     * The insert fields only — `openOn()` (US1) is the one legitimate `create()` path. No status,
     * no moment beyond `opened_at`/`detected_at`, no actor beyond `responsible_moderator_id`: the
     * rest is evidence (`moderation_actions`), never a column here.
     */
    protected $fillable = [
        'telegram_chat_id',
        'telegram_message_id',
        'opened_at',
        'detected_at',
        'source',
        'opened_by_user_id',
        'category',
        'severity',
        'message_classification_id',
        'prompted_by_classification_id',
        'responsible_moderator_id',
    ];

    protected function casts(): array
    {
        return [
            'opened_at' => 'datetime',
            'detected_at' => 'datetime',
            'created_at' => 'datetime',
        ];
    }

    public function chat(): BelongsTo
    {
        return $this->belongsTo(TelegramChat::class, 'telegram_chat_id');
    }

    /**
     * Opens exactly one incident against a stored, non-service message
     * (`contracts/incident-lifecycle.md` I1-I7, `control-panel-incidents.md` §2 P9): `opened_at`
     * from the message's own `sent_at`, `detected_at` from one PHP `now()` value bound once
     * (mirroring `ModeratorGroupAssignment::handover()`'s D-TG-47 rationale) and reused to
     * resolve `responsible_moderator_id` via TG-M2's `responsibleAt` scope — the owner at the
     * **flagging** moment, never a second definition of it. `uq_incident_anchor` is the
     * backstop: a duplicate anchor returns `null` rather than raising, exactly like Python's
     * `open_incident` (I2, R2). Writes nothing else and touches no attention item (I6, I7).
     *
     * `$promptedByClassificationId` (TG-M5, `control-panel-classification.md` V2): set only when
     * this flag came from the Possible Violations list — the incident is still fully
     * operator-opened (`message_classification_id` stays NULL, `ck_incident_operator_labels`),
     * recorded as *list-prompted* rather than *independent* (`classification-metrics.md` C3,
     * FR-044). `fk_incident_prompted_by` is the backstop: a prediction about another message is
     * refused by the database (`data-model.md` §4, probe 9 E2/E3).
     */
    public static function openOn(
        TelegramMessage $message,
        string $category,
        string $severity,
        User $by,
        ?int $promptedByClassificationId = null,
    ): ?self {
        if ($message->is_service) {
            throw new InvalidArgumentException('cannot open an incident on a service message');
        }

        $detectedAt = now();

        $responsibleModeratorId = ModeratorGroupAssignment::query()
            ->responsibleAt($message->telegram_chat_id, $detectedAt)
            ->value('moderator_id');

        $inserted = DB::table('moderation_incidents')->insertOrIgnore([
            'telegram_chat_id' => $message->telegram_chat_id,
            'telegram_message_id' => $message->message_id,
            'opened_at' => $message->sent_at->format('Y-m-d H:i:s.u'),
            'detected_at' => $detectedAt->format('Y-m-d H:i:s.u'),
            'source' => 'operator',
            'opened_by_user_id' => $by->id,
            'category' => $category,
            'severity' => $severity,
            'prompted_by_classification_id' => $promptedByClassificationId,
            'responsible_moderator_id' => $responsibleModeratorId,
        ]);

        if ($inserted === 0) {
            return null;
        }

        return static::query()
            ->where('telegram_chat_id', $message->telegram_chat_id)
            ->where('telegram_message_id', $message->message_id)
            ->first();
    }

    public function responsibleModerator(): BelongsTo
    {
        return $this->belongsTo(Moderator::class, 'responsible_moderator_id');
    }

    /**
     * The anchor message — this incident's own `(telegram_chat_id, telegram_message_id)`,
     * `fk_incident_message`'s target — mirroring `AttentionItem::anchorMessage()`. A plain query,
     * not an Eloquent relation: the join key is composite. Always finds a row (the FK guarantees
     * it); `original_text` alone may be `NULL` once TG-M10's purge reaches it.
     */
    public function anchorMessage(): ?TelegramMessage
    {
        return TelegramMessage::query()
            ->where('telegram_chat_id', $this->telegram_chat_id)
            ->where('message_id', $this->telegram_message_id)
            ->first();
    }

    /**
     * `SELECT * FROM moderation_incident_state WHERE incident_id = ?` — the status, every moment
     * and every actor, exactly as the view derives them (lifecycle contract S1-S6). `null` only
     * if this incident's own row were absent, which its own existence rules out; the view always
     * has exactly one row per incident.
     */
    public function state(): ?object
    {
        return DB::table('moderation_incident_state')
            ->where('incident_id', $this->id)
            ->first();
    }

    /**
     * `SELECT * FROM moderation_incident_evidence WHERE incident_id = ?`, ordered
     * `(occurred_at, source_rank, evidence_id)` — D-TG-106's tie-break, the trail's own order.
     */
    public function evidence(): Collection
    {
        return DB::table('moderation_incident_evidence')
            ->where('incident_id', $this->id)
            ->orderBy('occurred_at')
            ->orderBy('source_rank')
            ->orderBy('evidence_id')
            ->get();
    }

    /**
     * The lifecycle contract's §5 advisory-lock literal — identical, byte for byte, to Python's
     * `locks.py::_INCIDENT_LOCK_KEY` (H4, D-TG-114), so the two languages serialise against each
     * other, not just against themselves.
     */
    private const LOCK_KEY = 'moderation:incidents';

    /**
     * The three guarded human acts (`contracts/incident-lifecycle.md` §5, `control-panel-
     * incidents.md` §3): each takes the shared advisory lock, reads the status from
     * `moderation_incident_state` — never a column — and inserts one `moderation_actions` row
     * only if H1 allows it from that status. A disallowed state, or a second click that lands
     * after another transaction already moved the status, inserts nothing and returns `false`:
     * that is what a double submission or a stale page looks like, not an error (H2, H5).
     *
     * Each act is itself the evidence — `panel_user_id` and `occurred_at` (the transaction's own
     * `now()`) are what the trail and the view read back; no moderator is ever credited for a
     * panel act (H7).
     */
    public function acknowledge(User $by): bool
    {
        return $this->insertGuardedAction(
            allowedFrom: ['open'],
            by: $by,
            actionType: 'panel_acknowledge',
            actionStrength: 'acknowledgement',
        );
    }

    public function resolve(User $by, string $note): bool
    {
        return $this->insertGuardedAction(
            allowedFrom: ['open', 'acknowledged'],
            by: $by,
            actionType: 'panel_resolve',
            actionStrength: 'confirmation',
            note: $note,
        );
    }

    public function closeAsFalsePositive(User $by, string $reason): bool
    {
        return $this->insertGuardedAction(
            allowedFrom: ['open', 'acknowledged'],
            by: $by,
            actionType: 'panel_false_positive',
            actionStrength: null,
            note: $reason,
        );
    }

    /**
     * @param  array<int, string>  $allowedFrom
     */
    private function insertGuardedAction(
        array $allowedFrom,
        User $by,
        string $actionType,
        ?string $actionStrength,
        ?string $note = null,
    ): bool {
        return DB::transaction(function () use ($allowedFrom, $by, $actionType, $actionStrength, $note): bool {
            DB::select('SELECT pg_advisory_xact_lock(hashtext(?))', [self::LOCK_KEY]);

            $status = DB::table('moderation_incident_state')
                ->where('incident_id', $this->id)
                ->value('status');

            if (! in_array($status, $allowedFrom, true)) {
                return false;
            }

            DB::table('moderation_actions')->insert([
                'telegram_chat_id' => $this->telegram_chat_id,
                'action_type' => $actionType,
                'action_strength' => $actionStrength,
                'occurred_at' => now(),
                'panel_user_id' => $by->id,
                'moderation_incident_id' => $this->id,
                'detail' => json_encode([]),
                'note' => $note,
            ]);

            return true;
        });
    }
}
