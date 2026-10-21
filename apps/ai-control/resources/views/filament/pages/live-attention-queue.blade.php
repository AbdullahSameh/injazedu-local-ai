{{--
    T058 (US4, P7): a standing footnote, not action-specific text — no screen text anywhere may
    suggest Telegram itself reported a deletion. Telegram reports no message deletion in groups
    and no deleter; "message removed" on the Dismiss action above is always the operator's own
    judgement, recorded as theirs.
--}}
<x-filament-panels::page>
    {{ $this->table }}

    <p class="fi-in-text text-sm text-gray-500 dark:text-gray-400 mt-4">
        {{ __('Telegram does not report message deletion in groups; no removal evidence is available.') }}
    </p>

    {{--
        T074 (US6): the figures table — every number here is
        `App\Filament\Pages\Concerns\AttentionMetrics`, quoted from
        `contracts/attention-metrics.md` §2-§4. No average and no composite score appears
        anywhere on this page (M7, M17, M18, D-TG-92) — the moment one is tempting to add, it
        belongs in a different milestone, not this one.
    --}}
    <div class="fi-section rounded-xl bg-white shadow-sm ring-1 ring-gray-950/5 dark:bg-gray-900 dark:ring-white/10 mt-6 p-6">
        <h2 class="fi-section-header-heading text-base font-semibold text-gray-950 dark:text-white">
            {{ __('Figures') }}
        </h2>

        <form wire:submit.prevent class="flex flex-wrap items-end gap-4 mt-4">
            <div>
                <label for="periodFrom" class="text-xs font-medium text-gray-500 dark:text-gray-400">{{ __('From (Asia/Riyadh)') }}</label>
                <input type="date" id="periodFrom" wire:model.live="periodFrom"
                    class="fi-input block w-full rounded-lg border-gray-300 text-sm dark:border-gray-600 dark:bg-gray-800" />
            </div>
            <div>
                <label for="periodTo" class="text-xs font-medium text-gray-500 dark:text-gray-400">{{ __('To (Asia/Riyadh, inclusive)') }}</label>
                <input type="date" id="periodTo" wire:model.live="periodTo"
                    class="fi-input block w-full rounded-lg border-gray-300 text-sm dark:border-gray-600 dark:bg-gray-800" />
            </div>
        </form>

        <h3 class="text-sm font-semibold text-gray-700 dark:text-gray-300 mt-6">{{ __('By group') }}</h3>
        <div class="overflow-x-auto mt-2">
            <table class="w-full text-sm text-start">
                <thead>
                    <tr class="text-xs text-gray-500 dark:text-gray-400">
                        <th class="py-1 pe-4">{{ __('Group') }}</th>
                        <th class="py-1 pe-4">{{ __('Asked') }}</th>
                        <th class="py-1 pe-4">{{ __('Answered') }}</th>
                        <th class="py-1 pe-4">{{ __('Median') }}</th>
                        <th class="py-1 pe-4">P90</th>
                        <th class="py-1 pe-4">{{ __('Max') }}</th>
                        <th class="py-1 pe-4">{{ __('Unanswered') }}</th>
                        <th class="py-1 pe-4">{{ __('Oldest waiting') }}</th>
                    </tr>
                </thead>
                <tbody>
                    @forelse ($this->figuresByGroup() as $row)
                        <tr class="border-t border-gray-100 dark:border-white/5" dir="auto">
                            <td class="py-1.5 pe-4" dir="auto">{{ $row['label'] }}</td>
                            <td class="py-1.5 pe-4">{{ $row['opened'] }}</td>
                            <td class="py-1.5 pe-4">{{ $row['answered'] }}</td>
                            <td class="py-1.5 pe-4">{{ $this->humanDuration($row['median_frt']) }}</td>
                            <td class="py-1.5 pe-4">{{ $this->p90Display($row) }}</td>
                            <td class="py-1.5 pe-4">{{ $this->humanDuration($row['max_frt']) }}</td>
                            <td class="py-1.5 pe-4">{{ $row['unanswered'] }} ({{ $this->shareDisplay($row['unanswered_share']) }})</td>
                            <td class="py-1.5 pe-4">{{ $this->humanDuration($row['oldest_waiting_s']) }}</td>
                        </tr>
                    @empty
                        <tr>
                            <td colspan="8" class="py-2 text-gray-500 dark:text-gray-400">{{ __('No data for this period.') }}</td>
                        </tr>
                    @endforelse
                </tbody>
            </table>
        </div>

        {{--
            TG-M2.1 (`group-teams.md` §4): "My groups" is the same arithmetic as the group table,
            over the groups each moderator was on the team of when the question was asked (F1) — a
            miss counts once for every member (F2). "My work" is what they took and answered (F3).
        --}}
        @php($moderatorRows = $this->figuresByModerator())
        <h3 class="text-sm font-semibold text-gray-700 dark:text-gray-300 mt-6">{{ __('By moderator: my groups') }}</h3>
        <p class="text-xs text-gray-500 dark:text-gray-400 mt-1">
            {{ __('Questions asked in the groups each moderator was on the team of at the time. A question nobody answered counts for every member of the team.') }}
        </p>
        <div class="overflow-x-auto mt-2">
            <table class="w-full text-sm text-start">
                <thead>
                    <tr class="text-xs text-gray-500 dark:text-gray-400">
                        <th class="py-1 pe-4">{{ __('Moderator') }}</th>
                        <th class="py-1 pe-4">{{ __('Asked') }}</th>
                        <th class="py-1 pe-4">{{ __('Answered') }}</th>
                        <th class="py-1 pe-4">{{ __('Median') }}</th>
                        <th class="py-1 pe-4">P90</th>
                        <th class="py-1 pe-4">{{ __('Max') }}</th>
                        <th class="py-1 pe-4">{{ __('Unanswered') }}</th>
                    </tr>
                </thead>
                <tbody>
                    @forelse ($moderatorRows as $row)
                        <tr class="border-t border-gray-100 dark:border-white/5">
                            <td class="py-1.5 pe-4" dir="auto">{{ $row['label'] }}</td>
                            <td class="py-1.5 pe-4">{{ $row['opened'] }}</td>
                            <td class="py-1.5 pe-4">{{ $row['answered'] }}</td>
                            <td class="py-1.5 pe-4">{{ $this->humanDuration($row['median_frt']) }}</td>
                            <td class="py-1.5 pe-4">{{ $this->p90Display($row) }}</td>
                            <td class="py-1.5 pe-4">{{ $this->humanDuration($row['max_frt']) }}</td>
                            <td class="py-1.5 pe-4">{{ $row['unanswered'] }} ({{ $this->shareDisplay($row['unanswered_share']) }})</td>
                        </tr>
                    @empty
                        <tr>
                            <td colspan="7" class="py-2 text-gray-500 dark:text-gray-400">{{ __('No data for this period.') }}</td>
                        </tr>
                    @endforelse
                </tbody>
            </table>
        </div>

        <h3 class="text-sm font-semibold text-gray-700 dark:text-gray-300 mt-6">{{ __('By moderator: my work') }}</h3>
        <p class="text-xs text-gray-500 dark:text-gray-400 mt-1">
            {{ __('Assigned: questions this moderator took first, by reply, dismissal or reaction, and how each ended. Answered: questions they answered themselves, whoever had taken them.') }}
        </p>
        <div class="overflow-x-auto mt-2">
            <table class="w-full text-sm text-start">
                <thead>
                    <tr class="text-xs text-gray-500 dark:text-gray-400">
                        <th class="py-1 pe-4">{{ __('Moderator') }}</th>
                        <th class="py-1 pe-4">{{ __('Assigned') }}</th>
                        <th class="py-1 pe-4">{{ __('Taken by reply / dismissal / reaction') }}</th>
                        <th class="py-1 pe-4">{{ __('Answered / dismissed / open / expired') }}</th>
                        <th class="py-1 pe-4">{{ __('Answered by them') }}</th>
                        <th class="py-1 pe-4">{{ __('Median') }}</th>
                        <th class="py-1 pe-4">P90</th>
                        <th class="py-1 pe-4">{{ __('Outside their groups') }}</th>
                    </tr>
                </thead>
                <tbody>
                    @forelse ($moderatorRows as $row)
                        @php($work = $row['work'])
                        <tr class="border-t border-gray-100 dark:border-white/5">
                            <td class="py-1.5 pe-4" dir="auto">{{ $row['label'] }}</td>
                            <td class="py-1.5 pe-4">{{ $work['assigned'] }}</td>
                            <td class="py-1.5 pe-4">{{ $work['via_reply'] }} / {{ $work['via_dismissal'] }} / {{ $work['via_reaction'] }}</td>
                            <td class="py-1.5 pe-4">{{ $work['assigned_answered'] }} / {{ $work['assigned_dismissed'] }} / {{ $work['assigned_open'] }} / {{ $work['assigned_expired'] }}</td>
                            <td class="py-1.5 pe-4">{{ $work['answered_by_me']['answered'] }}</td>
                            <td class="py-1.5 pe-4">{{ $this->humanDuration($work['answered_by_me']['median_frt']) }}</td>
                            <td class="py-1.5 pe-4">{{ $this->p90Display($work['answered_by_me']) }}</td>
                            <td class="py-1.5 pe-4">{{ $work['outside'] }}</td>
                        </tr>
                    @empty
                        <tr>
                            <td colspan="8" class="py-2 text-gray-500 dark:text-gray-400">{{ __('No data for this period.') }}</td>
                        </tr>
                    @endforelse
                </tbody>
            </table>
        </div>
    </div>
</x-filament-panels::page>
