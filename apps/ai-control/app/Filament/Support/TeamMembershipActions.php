<?php

namespace App\Filament\Support;

use App\Models\MembershipRefused;
use App\Models\Moderator;
use App\Models\ModeratorGroupAssignment;
use App\Models\TelegramChat;
use Closure;
use Filament\Actions\Action;
use Filament\Forms\Components\DateTimePicker;
use Filament\Forms\Components\Select;
use Filament\Forms\Components\Textarea;
use Filament\Notifications\Notification;
use Filament\Support\Icons\Heroicon;
use Illuminate\Support\Carbon;

/**
 * TG-M2.1 S4's three team writes, offered on both Moderators › Assignments and Groups › Team
 * (`specs/012-tg-m2-1-group-teams/contracts/group-teams.md` T4-T5). Each delegates to the model —
 * `addMember`, `end`, `replaceWith` — where the rules live, so the screens never write a row
 * themselves (D-TG-58). A refusal is a notification, and nothing is written.
 */
final class TeamMembershipActions
{
    /**
     * "Add to group" / "Add member": `$fixed` returns the side already chosen by the page — the
     * moderator on a moderator's page, the group on a group's page — and the form asks for the
     * other side, a "since" (default now) and a note. A "since" in the future or before the
     * moderator was declared is refused by the model, as a notification (T4).
     *
     * @param  Closure(): array{telegram_chat_id?: int, moderator_id?: int}  $fixed
     */
    public static function add(string $name, string $label, Closure $fixed): Action
    {
        return Action::make($name)
            ->label($label)
            ->icon(Heroicon::OutlinedUserPlus)
            ->schema(fn (): array => array_values(array_filter([
                array_key_exists('telegram_chat_id', $fixed()) ? null : Select::make('telegram_chat_id')
                    ->label(__('Group'))
                    ->options(fn (): array => TelegramChat::query()
                        ->orderBy('title')
                        ->get()
                        ->mapWithKeys(fn (TelegramChat $chat): array => [
                            $chat->id => $chat->title ?? __('Chat :id', ['id' => $chat->chat_id]),
                        ])
                        ->all())
                    ->searchable()
                    ->required(),
                array_key_exists('moderator_id', $fixed()) ? null : Select::make('moderator_id')
                    ->label(__('Moderator'))
                    ->options(fn (): array => self::activeModeratorOptions())
                    ->searchable()
                    ->required(),
                DateTimePicker::make('valid_from')
                    ->label(__('Since'))
                    ->helperText(__('Defaults to now. Set an earlier time to record when this moderator actually started — never before they were declared as a moderator.'))
                    ->timezone('Asia/Riyadh')
                    ->default(now())
                    ->required(),
                Textarea::make('note')->label(__('Note'))->extraInputAttributes(['dir' => 'auto']),
            ])))
            ->action(function (array $data) use ($fixed): void {
                $data = array_merge($data, $fixed());
                try {
                    ModeratorGroupAssignment::addMember(
                        (int) $data['telegram_chat_id'],
                        (int) $data['moderator_id'],
                        Carbon::parse($data['valid_from']),
                        $data['note'] ?? null,
                    );
                } catch (MembershipRefused $refused) {
                    self::refuse($refused);
                }
            });
    }

    /**
     * "End": closes one current membership now (T5). Every other member is untouched.
     */
    public static function end(): Action
    {
        return Action::make('end_membership')
            ->label(__('End'))
            ->icon(Heroicon::OutlinedUserMinus)
            ->color('gray')
            ->visible(fn (ModeratorGroupAssignment $record): bool => $record->valid_to === null)
            ->requiresConfirmation()
            ->modalDescription(__('The membership ends now. Its history stays exactly as it is.'))
            ->action(fn (ModeratorGroupAssignment $record): bool => $record->end());
    }

    /**
     * "Replace with…": the handover protocol for one member (T5) — this membership closes and the
     * successor's opens at one instant, with no gap and no overlap.
     */
    public static function replace(): Action
    {
        return Action::make('replace_membership')
            ->label(__('Replace with…'))
            ->icon(Heroicon::OutlinedArrowsRightLeft)
            ->visible(fn (ModeratorGroupAssignment $record): bool => $record->valid_to === null
                && $record->assignment_role === 'primary')
            ->schema([
                Select::make('moderator_id')
                    ->label(__('Successor'))
                    ->options(fn (): array => self::activeModeratorOptions())
                    ->searchable()
                    ->required(),
                Textarea::make('note')->label(__('Note'))->extraInputAttributes(['dir' => 'auto']),
            ])
            ->action(function (ModeratorGroupAssignment $record, array $data): void {
                try {
                    $record->replaceWith((int) $data['moderator_id'], $data['note'] ?? null);
                } catch (MembershipRefused $refused) {
                    self::refuse($refused);
                }
            });
    }

    /**
     * @return array<int, string>
     */
    private static function activeModeratorOptions(): array
    {
        return Moderator::query()
            ->where('is_active', true)
            ->orderBy('display_name')
            ->pluck('display_name', 'id')
            ->all();
    }

    private static function refuse(MembershipRefused $refused): void
    {
        Notification::make()
            ->danger()
            ->title(__('Not saved'))
            ->body($refused->message())
            ->send();
    }
}
