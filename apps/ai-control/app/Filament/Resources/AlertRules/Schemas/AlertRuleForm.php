<?php

namespace App\Filament\Resources\AlertRules\Schemas;

use App\Filament\Resources\Incidents\Support\IncidentDisplay;
use App\Models\AlertRule;
use App\Models\TelegramChat;
use Closure;
use Filament\Forms\Components\CheckboxList;
use Filament\Forms\Components\Repeater;
use Filament\Forms\Components\Select;
use Filament\Forms\Components\TextInput;
use Filament\Forms\Components\Toggle;
use Filament\Schemas\Components\Section;
use Filament\Schemas\Components\Utilities\Get;
use Filament\Schemas\Schema;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Validation\ValidationException;

/**
 * TG-M6 S1: the trigger drives which fields show (R3, R4); thresholds and the repeat interval are
 * entered in minutes and stored in seconds; a group rule is offered only measured groups; quiet
 * hours are a list of `HH:MM` windows in `Asia/Riyadh` (R7); the enable switch carries FR-515's
 * one line. `AlertRule::violations()` is the one place the rules live — the fields only help.
 */
class AlertRuleForm
{
    private const HHMM = '/^([01]\d|2[0-3]):[0-5]\d$/';

    public static function configure(Schema $schema): Schema
    {
        return $schema
            ->components([
                Section::make(__('What it watches'))
                    ->schema([
                        Select::make('trigger')
                            ->label(__('Trigger'))
                            ->options(fn (): array => array_map(fn (string $label): string => __($label), AlertRule::TRIGGERS))
                            ->required()
                            ->live()
                            ->disabledOn('edit'),
                        Select::make('telegram_chat_id')
                            ->label(__('Group'))
                            ->placeholder(__('All groups'))
                            ->options(fn (?AlertRule $record): array => self::groupOptions($record))
                            ->searchable()
                            ->disabledOn('edit')
                            ->helperText(__('A group\'s own rule replaces the all-groups rule for that group. A disabled group rule mutes the trigger there.')),
                        TextInput::make('threshold_s')
                            ->label(__('Threshold (minutes)'))
                            ->numeric()
                            ->minValue(1)
                            ->visible(fn (Get $get): bool => in_array($get('trigger'), AlertRule::THRESHOLD_TRIGGERS, true))
                            ->required(fn (Get $get): bool => in_array($get('trigger'), AlertRule::THRESHOLD_TRIGGERS, true))
                            ->formatStateUsing(fn ($state): ?string => self::minutes($state))
                            ->dehydrateStateUsing(fn ($state): ?int => self::seconds($state)),
                    ]),
                Section::make(__('Which incidents'))
                    ->description(__('Nothing chosen means any.'))
                    ->visible(fn (Get $get): bool => in_array($get('trigger'), AlertRule::FILTER_TRIGGERS, true))
                    ->schema([
                        Select::make('min_severity')
                            ->label(__('Lowest severity'))
                            ->placeholder(__('Any'))
                            ->options([
                                'low' => __('Low'),
                                'medium' => __('Medium'),
                                'high' => __('High'),
                            ]),
                        CheckboxList::make('categories')
                            ->label(__('Categories'))
                            ->options([
                                'SPAM_OR_AD' => __('Spam or ad'),
                                'ABUSE' => __('Abuse'),
                                'OTHER' => __('Other'),
                            ])
                            ->columns(3),
                        CheckboxList::make('openers')
                            ->label(__('Opened by'))
                            ->options(array_combine(
                                AlertRule::OPENERS,
                                array_map(IncidentDisplay::openerLabel(...), AlertRule::OPENERS),
                            ))
                            ->columns(3),
                    ]),
                Section::make(__('Repeats and quiet hours'))
                    ->schema([
                        TextInput::make('repeat_every_s')
                            ->label(__('Repeat every (minutes)'))
                            ->numeric()
                            ->minValue(1)
                            ->formatStateUsing(fn ($state): ?string => self::minutes($state))
                            ->dehydrateStateUsing(fn ($state): ?int => self::seconds($state)),
                        TextInput::make('max_repeats')
                            ->label(__('Number of repeats'))
                            ->integer()
                            ->minValue(1)
                            ->helperText(__('Both or neither. A repeat goes out only while the subject still qualifies, and a missed one is never sent late.')),
                        Repeater::make('quiet_hours')
                            ->label(__('Quiet hours'))
                            ->helperText(__('In Asia/Riyadh time. An alert that fires inside a window is recorded as suppressed and never sent. A window that ends before it starts crosses midnight.'))
                            ->schema([
                                TextInput::make('from')
                                    ->label(__('From'))
                                    ->placeholder('22:00')
                                    ->required()
                                    ->regex(self::HHMM),
                                TextInput::make('to')
                                    ->label(__('To'))
                                    ->placeholder('06:00')
                                    ->required()
                                    ->regex(self::HHMM)
                                    ->different('from'),
                            ])
                            ->columns(2)
                            ->defaultItems(0)
                            ->addActionLabel(__('Add a quiet-hours window')),
                    ]),
                Toggle::make('is_enabled')
                    ->label(__('Enabled'))
                    ->helperText(__('A rule alerts on what crosses its threshold after it is switched on.')),
            ]);
    }

    /**
     * Measured groups, plus the rule's own group on an edit so its name still shows if it has
     * stopped being measured since.
     *
     * @return array<int, string>
     */
    private static function groupOptions(?AlertRule $record): array
    {
        return TelegramChat::query()
            ->where(fn ($query) => $query
                ->where('is_monitored', true)
                ->when($record?->telegram_chat_id !== null, fn ($q) => $q->orWhere('id', $record->telegram_chat_id)))
            ->orderBy('title')
            ->get()
            ->mapWithKeys(fn (TelegramChat $chat): array => [
                $chat->id => $chat->title ?? __('Chat :id', ['id' => $chat->chat_id]),
            ])
            ->all();
    }

    private static function minutes(mixed $seconds): ?string
    {
        if ($seconds === null || $seconds === '') {
            return null;
        }

        return rtrim(rtrim(number_format(((int) $seconds) / 60, 2, '.', ''), '0'), '.');
    }

    private static function seconds(mixed $minutes): ?int
    {
        if ($minutes === null || $minutes === '') {
            return null;
        }

        return (int) round(((float) $minutes) * 60);
    }

    /**
     * A field the chosen trigger hides is cleared, so a value typed before switching trigger is
     * never saved (R3, R4).
     *
     * @param  array<string, mixed>  $data
     * @return array<string, mixed>
     */
    public static function normalize(array $data): array
    {
        $trigger = $data['trigger'] ?? null;
        if (! in_array($trigger, AlertRule::THRESHOLD_TRIGGERS, true)) {
            $data['threshold_s'] = null;
        }
        if (! in_array($trigger, AlertRule::FILTER_TRIGGERS, true)) {
            $data['min_severity'] = null;
            $data['categories'] = null;
            $data['openers'] = null;
        }
        $data['quiet_hours'] = array_values($data['quiet_hours'] ?? []);

        return $data;
    }

    /**
     * Runs a save and moves the model's refusals under their form fields (`data.<attribute>`).
     *
     * @param  Closure(): Model  $save
     */
    public static function refusingInPlace(Closure $save): Model
    {
        try {
            return $save();
        } catch (ValidationException $refused) {
            throw ValidationException::withMessages(
                collect($refused->errors())
                    ->mapWithKeys(fn (array $messages, string $field): array => ["data.{$field}" => $messages])
                    ->all()
            );
        }
    }
}
