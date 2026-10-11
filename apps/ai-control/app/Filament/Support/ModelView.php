<?php

namespace App\Filament\Support;

use App\Models\MessageClassification;
use App\Models\MessageClassificationAttempt;
use App\Models\ModelProfile;

/**
 * The one renderer for "the model's view" (`control-panel-classification.md` §1 W1-W2, §5).
 * Every page that shows a prediction, or the reason there is none, formats it through here —
 * never a second wording, never a computed status (P2): `status()` **reads** the precedence
 * `classification-metrics.md` C5 and `data-model.md` §3 already define, it does not decide one.
 */
class ModelView
{
    /**
     * §5 exclusion reasons → words. `data-model.md` §3's eight-reason vocabulary, exactly.
     */
    private const EXCLUSION_LABELS = [
        'moderator' => "moderator's message",
        'service' => 'service announcement',
        'media' => 'media',
        'no_text' => 'no text',
        'group_itself' => 'sent as the group',
        'linked_channel' => "linked channel's post",
        'acknowledgement' => 'acknowledgement only',
        'text_removed' => 'text no longer held',
    ];

    /**
     * §5 failure kinds → words. M1's gateway categories that can reach the classifier, plus
     * `confidence_out_of_range` (D-TG-135).
     */
    private const FAILURE_LABELS = [
        'provider_unreachable' => 'runtime unreachable',
        'model_timeout' => 'timed out',
        'circuit_open' => 'temporarily unavailable',
        'model_truncated' => 'answer cut off',
        'structured_output_invalid' => 'answer malformed',
        'confidence_out_of_range' => 'confidence out of range',
        'model_not_available' => 'model not available',
        'provider_rejected' => 'request rejected',
        'provider_auth' => 'authentication failed',
    ];

    /**
     * W1: three places, always labelled "self-reported confidence" — never `%`, never
     * "probability", "chance" or "likelihood".
     */
    public static function confidence(string|float $confidence): string
    {
        return number_format((float) $confidence, 3).' self-reported confidence';
    }

    public static function exclusionLabel(string $reason): string
    {
        return self::EXCLUSION_LABELS[$reason] ?? $reason;
    }

    public static function failureLabel(string $reason): string
    {
        return self::FAILURE_LABELS[$reason] ?? $reason;
    }

    /**
     * §5, read in precedence: no active classification model (checked first) · a current
     * prediction · an exclusion · the latest failure · not classified yet. Never blank.
     */
    public static function status(int $telegramChatId, int $telegramMessageId): string
    {
        if (! self::hasActiveModel()) {
            return 'No classification model is active.';
        }

        $classification = MessageClassification::query()
            ->where('telegram_chat_id', $telegramChatId)
            ->where('telegram_message_id', $telegramMessageId)
            ->where('is_current', true)
            ->first();

        if ($classification !== null) {
            return $classification->category.' · '.self::confidence($classification->confidence);
        }

        $exclusion = MessageClassificationAttempt::query()
            ->where('telegram_chat_id', $telegramChatId)
            ->where('telegram_message_id', $telegramMessageId)
            ->where('outcome', 'excluded')
            ->first();

        if ($exclusion !== null) {
            return 'Not sent to the model — '.self::exclusionLabel($exclusion->reason);
        }

        $failure = MessageClassificationAttempt::query()
            ->where('telegram_chat_id', $telegramChatId)
            ->where('telegram_message_id', $telegramMessageId)
            ->where('outcome', 'failed')
            ->orderByDesc('created_at')
            ->orderByDesc('id')
            ->first();

        if ($failure !== null) {
            return 'The model could not classify this message — '.self::failureLabel($failure->reason);
        }

        return 'Not classified yet — awaiting the model, or recorded before classification began.';
    }

    private static function hasActiveModel(): bool
    {
        return ModelProfile::query()
            ->where('role', 'moderation')
            ->where('is_active', true)
            ->exists();
    }
}
