<?php

namespace App\Filament\Resources\Incidents\Actions;

use App\Models\ModerationIncident;
use App\Models\TelegramMessage;
use App\Models\User;
use Closure;
use Filament\Actions\Action;
use Filament\Forms\Components\Select;
use Illuminate\Support\Facades\Auth;
use Illuminate\Support\Str;

/**
 * One reusable action, two entry points (`control-panel-incidents.md` §2): the Incidents list's
 * header action asks for the message too; the Live Attention Queue's row action already has it
 * from the item's own anchor (FR-072, D-TG-125). Both call the same guarded write,
 * `ModerationIncident::openOn`.
 */
class OpenIncidentAction
{
    /** `ck_incident_category` (`data-model.md` §1, D-TG-101), exactly. */
    private const CATEGORIES = [
        'SPAM_OR_AD' => 'Spam or ad',
        'ABUSE' => 'Abuse',
        'OTHER' => 'Other',
    ];

    /** `ck_incident_severity`, exactly. */
    private const SEVERITIES = [
        'low' => 'Low',
        'medium' => 'Medium',
        'high' => 'High',
    ];

    public static function forList(): Action
    {
        return Action::make('open_incident')
            ->label('Open incident')
            ->schema([
                Select::make('telegram_message_id')
                    ->label('Message')
                    ->helperText(
                        'Only messages that are not service messages and do not already anchor '
                            .'an incident are listed.'
                    )
                    ->options(fn (): array => self::openableMessageOptions())
                    ->searchable()
                    ->required()
                    ->rule(fn (): Closure => self::messageValidationRule()),
                self::categorySelect(),
                self::severitySelect(),
            ])
            ->action(function (array $data): void {
                $message = TelegramMessage::findOrFail($data['telegram_message_id']);
                self::open($message, $data['category'], $data['severity']);
            });
    }

    public static function forQueueRow(): Action
    {
        return Action::make('open_incident')
            ->label('Open incident')
            ->schema([
                self::categorySelect(),
                self::severitySelect(),
            ])
            ->action(function (array $data, $record): void {
                self::open($record->anchorMessage(), $data['category'], $data['severity']);
            });
    }

    private static function categorySelect(): Select
    {
        return Select::make('category')->label('Category')->options(self::CATEGORIES)->required();
    }

    private static function severitySelect(): Select
    {
        return Select::make('severity')->label('Severity')->options(self::SEVERITIES)->required();
    }

    private static function open(?TelegramMessage $message, string $category, string $severity): void
    {
        if ($message === null) {
            return;
        }
        /** @var User $user */
        $user = Auth::user();
        ModerationIncident::openOn($message, $category, $severity, $user);
    }

    /**
     * P7: recent messages in measured groups that are not service messages and do not already
     * anchor an incident — excluded by the composite `(telegram_chat_id, message_id)`, never
     * `message_id` alone (research Finding 2, D-TG-71 applies unchanged).
     *
     * @return array<int, string>
     */
    public static function openableMessageOptions(): array
    {
        return TelegramMessage::query()
            ->where('is_service', false)
            ->whereNotExists(function ($query): void {
                $query->selectRaw('1')
                    ->from('moderation_incidents')
                    ->whereColumn(
                        'moderation_incidents.telegram_chat_id',
                        'telegram_messages.telegram_chat_id'
                    )
                    ->whereColumn(
                        'moderation_incidents.telegram_message_id',
                        'telegram_messages.message_id'
                    );
            })
            ->orderByDesc('sent_at')
            ->limit(200)
            ->get()
            ->mapWithKeys(fn (TelegramMessage $message): array => [
                $message->id => sprintf(
                    '#%d — %s',
                    $message->message_id,
                    Str::limit($message->original_text ?? '(text removed)', 60),
                ),
            ])
            ->all();
    }

    /**
     * A validation rule re-checking both exclusions at submit — `uq_incident_anchor` is the
     * backstop either way (P7).
     */
    private static function messageValidationRule(): Closure
    {
        return function (string $attribute, $value, Closure $fail): void {
            $message = TelegramMessage::find($value);
            if ($message === null) {
                $fail('That message no longer exists.');

                return;
            }
            if ($message->is_service) {
                $fail('Service messages cannot be flagged.');

                return;
            }
            $alreadyAnchors = ModerationIncident::query()
                ->where('telegram_chat_id', $message->telegram_chat_id)
                ->where('telegram_message_id', $message->message_id)
                ->exists();
            if ($alreadyAnchors) {
                $fail('This message already anchors an incident.');
            }
        };
    }
}
