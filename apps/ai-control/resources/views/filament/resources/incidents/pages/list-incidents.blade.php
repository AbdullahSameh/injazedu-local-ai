<x-filament-panels::page>
    {{ $this->content }}

    @include('filament.resources.incidents.standing-notices')

    {{--
        T062: the figures table — every number here is
        `App\Filament\Resources\Incidents\Concerns\IncidentMetrics`, quoted from
        `contracts/incident-metrics.md` §2-§4. No average and no composite score appears anywhere
        on this page (M14, D-TG-92, `control-panel-incidents.md` §5 P18).
    --}}
    <div class="fi-section rounded-xl bg-white shadow-sm ring-1 ring-gray-950/5 dark:bg-gray-900 dark:ring-white/10 mt-6 p-6">
        <h2 class="fi-section-header-heading text-base font-semibold text-gray-950 dark:text-white">
            {{ __('Figures') }}
        </h2>

        <form wire:submit.prevent class="flex flex-wrap items-end gap-4 mt-4">
            <div>
                <label for="incidentPeriodFrom" class="text-xs font-medium text-gray-500 dark:text-gray-400">{{ __('From (Asia/Riyadh)') }}</label>
                <input type="date" id="incidentPeriodFrom" wire:model.live="periodFrom"
                    class="fi-input block w-full rounded-lg border-gray-300 text-sm dark:border-gray-600 dark:bg-gray-800" />
            </div>
            <div>
                <label for="incidentPeriodTo" class="text-xs font-medium text-gray-500 dark:text-gray-400">{{ __('To (Asia/Riyadh, inclusive)') }}</label>
                <input type="date" id="incidentPeriodTo" wire:model.live="periodTo"
                    class="fi-input block w-full rounded-lg border-gray-300 text-sm dark:border-gray-600 dark:bg-gray-800" />
            </div>
        </form>

        @php($total = $this->totalFigures())

        <h3 class="text-sm font-semibold text-gray-700 dark:text-gray-300 mt-6">{{ __('Total') }}</h3>
        <div class="overflow-x-auto mt-2">
            <table class="w-full text-sm text-start">
                <thead>
                    <tr class="text-xs text-gray-500 dark:text-gray-400">
                        <th class="py-1 pe-4">{{ __('Flagged') }}</th>
                        <th class="py-1 pe-4">{{ __('Handled') }}</th>
                        <th class="py-1 pe-4">{{ __('Missed') }}</th>
                        <th class="py-1 pe-4">{{ __('Within window') }}</th>
                        <th class="py-1 pe-4">{{ __('False positive') }}</th>
                        <th class="py-1 pe-4">{{ __('Ack., not handled') }}</th>
                        <th class="py-1 pe-4">{{ __('Handled share') }}</th>
                    </tr>
                </thead>
                <tbody>
                    <tr class="border-t border-gray-100 dark:border-white/5">
                        <td class="py-1.5 pe-4">{{ $total['flagged'] }}</td>
                        <td class="py-1.5 pe-4">{{ $total['handled'] }}</td>
                        <td class="py-1.5 pe-4">{{ $total['missed'] }}</td>
                        <td class="py-1.5 pe-4">{{ $total['within_window'] }}</td>
                        <td class="py-1.5 pe-4">{{ $total['false_positive'] }}</td>
                        <td class="py-1.5 pe-4">{{ $total['acknowledged_not_handled'] }}</td>
                        <td class="py-1.5 pe-4">{{ $this->shareDisplay($total['handled_share']) }}</td>
                    </tr>
                </tbody>
            </table>
        </div>

        {{--
            TG-M5, D-TG-159: detection latency is grouped by opener (C8) — one row per opener
            ('Operator', 'Model'), never merged into a single system-wide figure. A source with
            no incidents in the period has no row here at all.
        --}}
        <h3 class="text-sm font-semibold text-gray-700 dark:text-gray-300 mt-6">{{ __('Detection latency by opener') }}</h3>
        <div class="overflow-x-auto mt-2">
            <table class="w-full text-sm text-start">
                <thead>
                    <tr class="text-xs text-gray-500 dark:text-gray-400">
                        <th class="py-1 pe-4">{{ __('Opened by') }}</th>
                        <th class="py-1 pe-4">{{ __('Flagged') }}</th>
                        <th class="py-1 pe-4">{{ __('Median') }}</th>
                        <th class="py-1 pe-4">P90</th>
                        <th class="py-1 pe-4">{{ __('Max') }}</th>
                    </tr>
                </thead>
                <tbody>
                    @forelse ($this->latencyRows($total['latency']) as $row)
                        <tr class="border-t border-gray-100 dark:border-white/5">
                            <td class="py-1.5 pe-4">{{ $row['opener'] }}</td>
                            <td class="py-1.5 pe-4">{{ $row['flagged'] }}</td>
                            <td class="py-1.5 pe-4">{{ $this->humanDuration($row['median']) }}</td>
                            <td class="py-1.5 pe-4">{{ $this->p90Display($row['p90'], $row['p90_suppressed'], $row['flagged']) }}</td>
                            <td class="py-1.5 pe-4">{{ $this->humanDuration($row['max']) }}</td>
                        </tr>
                    @empty
                        <tr>
                            <td colspan="5" class="py-2 text-gray-500 dark:text-gray-400">{{ __('No data for this period.') }}</td>
                        </tr>
                    @endforelse
                </tbody>
            </table>
        </div>

        <h3 class="text-sm font-semibold text-gray-700 dark:text-gray-300 mt-6">{{ __('By group') }}</h3>
        <div class="overflow-x-auto mt-2">
            <table class="w-full text-sm text-start">
                <thead>
                    <tr class="text-xs text-gray-500 dark:text-gray-400">
                        <th class="py-1 pe-4">{{ __('Group') }}</th>
                        <th class="py-1 pe-4">{{ __('Flagged') }}</th>
                        <th class="py-1 pe-4">{{ __('Handled') }}</th>
                        <th class="py-1 pe-4">{{ __('Missed') }}</th>
                        <th class="py-1 pe-4">{{ __('Within window') }}</th>
                        <th class="py-1 pe-4">{{ __('False positive') }}</th>
                        <th class="py-1 pe-4">{{ __('Handled share') }}</th>
                        <th class="py-1 pe-4">{{ __('Ack. (median / p90 / max)') }}</th>
                        <th class="py-1 pe-4">{{ __('Confirm. (median / p90 / max)') }}</th>
                        <th class="py-1 pe-4">{{ __('Enforce. (median / p90 / max)') }}</th>
                        <th class="py-1 pe-4">{{ __('Detection latency (median / p90 / max)') }}</th>
                    </tr>
                </thead>
                <tbody>
                    @forelse ($this->figuresByGroup() as $row)
                        <tr class="border-t border-gray-100 dark:border-white/5" dir="auto">
                            <td class="py-1.5 pe-4" dir="auto">{{ $row['label'] }}</td>
                            <td class="py-1.5 pe-4">{{ $row['flagged'] }}</td>
                            <td class="py-1.5 pe-4">{{ $row['handled'] }}</td>
                            <td class="py-1.5 pe-4">{{ $row['missed'] }}</td>
                            <td class="py-1.5 pe-4">{{ $row['within_window'] }}</td>
                            <td class="py-1.5 pe-4">{{ $row['false_positive'] }}</td>
                            <td class="py-1.5 pe-4">{{ $this->shareDisplay($row['handled_share']) }}</td>
                            @foreach (['acknowledgement', 'confirmation', 'enforcement'] as $timing)
                                <td class="py-1.5 pe-4">
                                    {{ $this->humanDuration($row['timings'][$timing]['median']) }} /
                                    {{ $this->p90Display($row['timings'][$timing]['p90'], $row['timings'][$timing]['p90_suppressed'], $row['timings'][$timing]['samples']) }} /
                                    {{ $this->humanDuration($row['timings'][$timing]['max']) }}
                                </td>
                            @endforeach
                            <td class="py-1.5 pe-4">
                                @forelse ($this->latencyRows($row['latency']) as $latencyRow)
                                    <div>
                                        {{ $latencyRow['opener'] }}:
                                        {{ $this->humanDuration($latencyRow['median']) }} /
                                        {{ $this->p90Display($latencyRow['p90'], $latencyRow['p90_suppressed'], $latencyRow['flagged']) }} /
                                        {{ $this->humanDuration($latencyRow['max']) }}
                                    </div>
                                @empty
                                    {{ __('no data') }}
                                @endforelse
                            </td>
                        </tr>
                    @empty
                        <tr>
                            <td colspan="11" class="py-2 text-gray-500 dark:text-gray-400">{{ __('No data for this period.') }}</td>
                        </tr>
                    @endforelse
                </tbody>
            </table>
        </div>

        {{--
            TG-M2.1 (`group-teams.md` §4): "My groups" is the same arithmetic as the group table, over
            the groups each moderator was on the team of when the incident was flagged (F1) — a miss
            counts once for every member (F2). "My work" is what they took themselves (F4). P15: no
            detection-latency column — the figure cannot be attributed to a moderator (FR-054).
        --}}
        @php($moderatorRows = $this->figuresByModerator())
        <h3 class="text-sm font-semibold text-gray-700 dark:text-gray-300 mt-6">{{ __('By moderator: my groups') }}</h3>
        <p class="text-xs text-gray-500 dark:text-gray-400 mt-1">
            {{ __('Incidents flagged in the groups each moderator was on the team of at the time. An incident nobody handled counts for every member of the team.') }}
        </p>
        <div class="overflow-x-auto mt-2">
            <table class="w-full text-sm text-start">
                <thead>
                    <tr class="text-xs text-gray-500 dark:text-gray-400">
                        <th class="py-1 pe-4">{{ __('Moderator') }}</th>
                        <th class="py-1 pe-4">{{ __('Flagged') }}</th>
                        <th class="py-1 pe-4">{{ __('Handled') }}</th>
                        <th class="py-1 pe-4">{{ __('Missed') }}</th>
                        <th class="py-1 pe-4">{{ __('Within window') }}</th>
                        <th class="py-1 pe-4">{{ __('False positive') }}</th>
                        <th class="py-1 pe-4">{{ __('Handled share') }}</th>
                        <th class="py-1 pe-4">{{ __('Ack. (median / p90 / max)') }}</th>
                        <th class="py-1 pe-4">{{ __('Confirm. (median / p90 / max)') }}</th>
                        <th class="py-1 pe-4">{{ __('Enforce. (median / p90 / max)') }}</th>
                    </tr>
                </thead>
                <tbody>
                    @forelse ($moderatorRows as $row)
                        <tr class="border-t border-gray-100 dark:border-white/5">
                            <td class="py-1.5 pe-4" dir="auto">{{ $row['label'] }}</td>
                            <td class="py-1.5 pe-4">{{ $row['flagged'] }}</td>
                            <td class="py-1.5 pe-4">{{ $row['handled'] }}</td>
                            <td class="py-1.5 pe-4">{{ $row['missed'] }}</td>
                            <td class="py-1.5 pe-4">{{ $row['within_window'] }}</td>
                            <td class="py-1.5 pe-4">{{ $row['false_positive'] }}</td>
                            <td class="py-1.5 pe-4">{{ $this->shareDisplay($row['handled_share']) }}</td>
                            @foreach (['acknowledgement', 'confirmation', 'enforcement'] as $timing)
                                <td class="py-1.5 pe-4">
                                    {{ $this->humanDuration($row['timings'][$timing]['median']) }} /
                                    {{ $this->p90Display($row['timings'][$timing]['p90'], $row['timings'][$timing]['p90_suppressed'], $row['timings'][$timing]['samples']) }} /
                                    {{ $this->humanDuration($row['timings'][$timing]['max']) }}
                                </td>
                            @endforeach
                        </tr>
                    @empty
                        <tr>
                            <td colspan="10" class="py-2 text-gray-500 dark:text-gray-400">{{ __('No data for this period.') }}</td>
                        </tr>
                    @endforelse
                </tbody>
            </table>
        </div>

        <h3 class="text-sm font-semibold text-gray-700 dark:text-gray-300 mt-6">{{ __('By moderator: my work') }}</h3>
        <p class="text-xs text-gray-500 dark:text-gray-400 mt-1">
            {{ __('Assigned: incidents this moderator acted on first, in Telegram or in the panel. Time to take: from the flag to that first act.') }}
        </p>
        <div class="overflow-x-auto mt-2">
            <table class="w-full text-sm text-start">
                <thead>
                    <tr class="text-xs text-gray-500 dark:text-gray-400">
                        <th class="py-1 pe-4">{{ __('Moderator') }}</th>
                        <th class="py-1 pe-4">{{ __('Assigned') }}</th>
                        <th class="py-1 pe-4">{{ __('Acknowledged / resolved / false positive') }}</th>
                        <th class="py-1 pe-4">{{ __('Taken by') }}</th>
                        <th class="py-1 pe-4">{{ __('Time to take (median / p90 / max)') }}</th>
                        <th class="py-1 pe-4">{{ __('Outside their groups') }}</th>
                    </tr>
                </thead>
                <tbody>
                    @forelse ($moderatorRows as $row)
                        @php($work = $row['work'])
                        <tr class="border-t border-gray-100 dark:border-white/5">
                            <td class="py-1.5 pe-4" dir="auto">{{ $row['label'] }}</td>
                            <td class="py-1.5 pe-4">{{ $work['assigned'] }}</td>
                            <td class="py-1.5 pe-4">{{ $work['assigned_acknowledged'] }} / {{ $work['assigned_resolved'] }} / {{ $work['assigned_false_positive'] }}</td>
                            <td class="py-1.5 pe-4">{{ $this->viaDisplay($work['via']) }}</td>
                            <td class="py-1.5 pe-4">
                                {{ $this->humanDuration($work['take']['median']) }} /
                                {{ $this->p90Display($work['take']['p90'], $work['take']['p90_suppressed'], $work['take']['samples']) }} /
                                {{ $this->humanDuration($work['take']['max']) }}
                            </td>
                            <td class="py-1.5 pe-4">{{ $work['outside'] }}</td>
                        </tr>
                    @empty
                        <tr>
                            <td colspan="6" class="py-2 text-gray-500 dark:text-gray-400">{{ __('No data for this period.') }}</td>
                        </tr>
                    @endforelse
                </tbody>
            </table>
        </div>
    </div>
</x-filament-panels::page>
