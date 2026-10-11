<x-filament-panels::page>
    {{--
        `control-panel-classification.md` §4 A1-A3: an estimate over the human labels already
        recorded, never a measurement — every figure is a numerator / denominator, grouped by
        model, instruction version and vocabulary version, never pooled (K3). No average, no
        percentage, no combined score anywhere on this page.
    --}}
    <div class="fi-section rounded-xl bg-white shadow-sm ring-1 ring-gray-950/5 dark:bg-gray-900 dark:ring-white/10 p-6">
        <p class="text-sm text-gray-600 dark:text-gray-400">
            Estimates over the human labels available. The labels are few and not random; treat
            every ratio as a floor for discussion, not a measurement.
        </p>

        <form wire:submit.prevent class="flex flex-wrap items-end gap-4 mt-4">
            <div>
                <label for="accuracyPeriodFrom" class="text-xs font-medium text-gray-500 dark:text-gray-400">From (Asia/Riyadh)</label>
                <input type="date" id="accuracyPeriodFrom" wire:model.live="periodFrom"
                    class="fi-input block w-full rounded-lg border-gray-300 text-sm dark:border-gray-600 dark:bg-gray-800" />
            </div>
            <div>
                <label for="accuracyPeriodTo" class="text-xs font-medium text-gray-500 dark:text-gray-400">To (Asia/Riyadh, inclusive)</label>
                <input type="date" id="accuracyPeriodTo" wire:model.live="periodTo"
                    class="fi-input block w-full rounded-lg border-gray-300 text-sm dark:border-gray-600 dark:bg-gray-800" />
            </div>
            <div>
                <label for="accuracyGroup" class="text-xs font-medium text-gray-500 dark:text-gray-400">Group</label>
                <select id="accuracyGroup" wire:model.live="chatId"
                    class="fi-select block w-full rounded-lg border-gray-300 text-sm dark:border-gray-600 dark:bg-gray-800">
                    <option value="">All measured groups</option>
                    @foreach ($this->groupOptions() as $id => $title)
                        <option value="{{ $id }}" dir="auto">{{ $title }}</option>
                    @endforeach
                </select>
            </div>
        </form>
    </div>

    {{--
        Rule set baseline: C7, read per M19 — precision per rule version, recall a floor. The
        dismissal count is every reason; its breakdown (TG-M5.3 K7, K11) sits under the table.
    --}}
    <div class="fi-section rounded-xl bg-white shadow-sm ring-1 ring-gray-950/5 dark:bg-gray-900 dark:ring-white/10 mt-6 p-6">
        <h2 class="fi-section-header-heading text-base font-semibold text-gray-950 dark:text-white">
            Rule set baseline
        </h2>
        <div class="overflow-x-auto mt-2">
            <table class="w-full text-sm text-left">
                <thead>
                    <tr class="text-xs text-gray-500 dark:text-gray-400">
                        <th class="py-1 pr-4">Rule version</th>
                        <th class="py-1 pr-4">Rule-opened</th>
                        <th class="py-1 pr-4">Rule-dismissed (any reason)</th>
                        <th class="py-1 pr-4">Precision</th>
                        <th class="py-1 pr-4">Operator-added</th>
                        <th class="py-1 pr-4">Recall (a floor)</th>
                    </tr>
                </thead>
                <tbody>
                    @forelse ($this->ruleBaseline() as $row)
                        <tr class="border-t border-gray-100 dark:border-white/5">
                            <td class="py-1.5 pr-4">{{ $row['rule_version'] ?? 'Operator additions' }}</td>
                            <td class="py-1.5 pr-4">{{ $row['rule_opened'] }}</td>
                            <td class="py-1.5 pr-4">{{ $row['rule_dismissed'] }}</td>
                            <td class="py-1.5 pr-4">
                                {{ $this->ratio($row['rule_opened'] - $row['rule_dismissed'], $row['rule_opened']) }}
                            </td>
                            <td class="py-1.5 pr-4">{{ $row['operator_added'] }}</td>
                            <td class="py-1.5 pr-4">—</td>
                        </tr>
                    @empty
                        <tr>
                            <td colspan="6" class="py-2 text-gray-500 dark:text-gray-400">No labelled examples.</td>
                        </tr>
                    @endforelse
                </tbody>
            </table>
        </div>
        {{-- TG-M5.3 K7, K12: why each rule version's items were dismissed — counts, never ratios. --}}
        @foreach ($this->ruleBaseline()->filter(fn (array $row): bool => $row['rule_opened'] > 0) as $row)
            <p class="text-xs text-gray-500 dark:text-gray-400 mt-2">
                Rule version {{ $row['rule_version'] }}, rule-dismissed by reason:
                {{ $this->dismissalBreakdown($row) }}
            </p>
        @endforeach
        {{-- M19, amended by TG-M5.1: the recall floor's operator-added count never sees a rule miss the model caught. --}}
        @php($modelKept = $this->modelKeptQuestions())
        @if ($modelKept > 0)
            <p class="text-xs text-gray-500 dark:text-gray-400 mt-2">
                Model-opened and kept: {{ $modelKept }} — questions the rule set missed and the model opened,
                which nobody dismissed. They are not in the operator-added count, so the recall floor reads
                higher while AI-assisted opening is on.
            </p>
        @endif
    </div>

    {{-- What happened to every message: C5, never grouped by model. --}}
    @php($volume = $this->volume())
    <div class="fi-section rounded-xl bg-white shadow-sm ring-1 ring-gray-950/5 dark:bg-gray-900 dark:ring-white/10 mt-6 p-6">
        <h2 class="fi-section-header-heading text-base font-semibold text-gray-950 dark:text-white">
            What happened to every message
        </h2>
        <div class="overflow-x-auto mt-2">
            <table class="w-full text-sm text-left">
                <thead>
                    <tr class="text-xs text-gray-500 dark:text-gray-400">
                        <th class="py-1 pr-4">Messages</th>
                        <th class="py-1 pr-4">Classified</th>
                        <th class="py-1 pr-4">Excluded (by reason)</th>
                        <th class="py-1 pr-4">Failed (by latest kind)</th>
                        <th class="py-1 pr-4">Not classified yet</th>
                    </tr>
                </thead>
                <tbody>
                    <tr class="border-t border-gray-100 dark:border-white/5">
                        <td class="py-1.5 pr-4">{{ $volume['messages'] }}</td>
                        <td class="py-1.5 pr-4">{{ $volume['classified'] }}</td>
                        <td class="py-1.5 pr-4">
                            {{ $volume['excluded'] }}
                            @if ($volume['excluded_by_reason'] !== [])
                                ({{ collect($volume['excluded_by_reason'])->map(fn ($n, $reason) => "{$reason}:{$n}")->implode(', ') }})
                            @endif
                        </td>
                        <td class="py-1.5 pr-4">
                            {{ $volume['failed'] }}
                            @if ($volume['failed_by_reason'] !== [])
                                ({{ collect($volume['failed_by_reason'])->map(fn ($n, $reason) => "{$reason}:{$n}")->implode(', ') }})
                            @endif
                        </td>
                        <td class="py-1.5 pr-4">{{ $volume['not_classified_yet'] }}</td>
                    </tr>
                </tbody>
            </table>
        </div>
    </div>

    {{-- One block per model, instruction version and vocabulary version — never pooled (K3). --}}
    @forelse ($this->blocks() as $block)
        <div class="fi-section rounded-xl bg-white shadow-sm ring-1 ring-gray-950/5 dark:bg-gray-900 dark:ring-white/10 mt-6 p-6">
            <h2 class="fi-section-header-heading text-base font-semibold text-gray-950 dark:text-white" dir="auto">
                {{ $block['model'] }} · {{ $block['prompt_version'] }} · vocabulary v{{ $block['taxonomy_version'] }}
            </h2>

            <h3 class="text-sm font-semibold text-gray-700 dark:text-gray-300 mt-4">Questions</h3>
            <ul class="text-sm mt-1 space-y-1">
                <li>Rule-kept, model agrees needs an answer: {{ $this->ratio($block['questions']['rule_kept']['judged_needs_response'], $block['questions']['rule_kept']['classified']) }}</li>
                <li>Rule-dismissed, model would also have flagged: {{ $this->ratio($block['questions']['rule_dismissed']['judged_needs_response'], $block['questions']['rule_dismissed']['classified']) }}</li>
                <li>Operator-added, model caught the miss: {{ $this->ratio($block['questions']['operator_added']['judged_needs_response'], $block['questions']['operator_added']['classified']) }}</li>
                <li>Unverified model-only judgements (a count, never a ratio): {{ $block['questions']['unverified'] }}</li>
            </ul>

            {{--
                C9′'s `classification` row (TG-M5.1 items, opened from a prediction): dismissed (any
                reason) ÷ opened was the TG-M5.1 pilot's false-positive gate. The breakdown beneath
                it is diagnostic: counts only, and no gate reads it (TG-M5.3 K10).
            --}}
            @if ($block['model_questions']['opened'] > 0)
                <h3 class="text-sm font-semibold text-gray-700 dark:text-gray-300 mt-4">Questions the model opened</h3>
                <ul class="text-sm mt-1 space-y-1">
                    <li>
                        Model-opened, dismissed (any reason): {{ $this->ratio($block['model_questions']['dismissed'], $block['model_questions']['opened']) }}
                        <span class="block text-xs text-gray-500 dark:text-gray-400">{{ $this->dismissalBreakdown($block['model_questions']) }}</span>
                    </li>
                    <li>Model-opened, answered: {{ $this->ratio($block['model_questions']['answered'], $block['model_questions']['opened']) }}</li>
                    <li>Model-opened, still unanswered (open or expired): {{ $this->ratio($block['model_questions']['unanswered'], $block['model_questions']['opened']) }}</li>
                </ul>
            @endif

            <h3 class="text-sm font-semibold text-gray-700 dark:text-gray-300 mt-4">Violations</h3>
            <ul class="text-sm mt-1 space-y-1">
                <li>Independent flags, model agreed: {{ $this->ratio($block['violations']['indep_agreed'], $block['violations']['indep_flags']) }}</li>
                <li>Of those, same category: {{ $this->ratio($block['violations']['indep_same_cat'], $block['violations']['indep_agreed']) }}</li>
                <li>List-prompted flags, model agreed (shown apart): {{ $this->ratio($block['violations']['prompted_agreed'], $block['violations']['prompted_flags']) }}</li>
                <li>Of those, same category: {{ $this->ratio($block['violations']['prompted_same_cat'], $block['violations']['prompted_agreed']) }}</li>
                <li>False-positive closures, model would have raised: {{ $this->ratio($block['violations']['fp_model_raised'], $block['violations']['fp_closures']) }}</li>
                <li>Model-opened incidents, closed as false positive: {{ $this->ratio($block['violations']['model_opened_fp'], $block['violations']['model_opened']) }}</li>
                <li>Listed now: {{ $block['violations']['listed_now'] }}</li>
            </ul>
        </div>
    @empty
        <div class="fi-section rounded-xl bg-white shadow-sm ring-1 ring-gray-950/5 dark:bg-gray-900 dark:ring-white/10 mt-6 p-6">
            <p class="text-sm text-gray-500 dark:text-gray-400">No labelled examples for any model in this period.</p>
        </div>
    @endforelse

    {{--
        TG-M5.3, C10a (`specs/011-…/contracts/attention-metrics.md` §2-§3, M26-M27): the attention
        judgement's coverage, never grouped by model. It is a separate question from the
        classification above, with its own record; the two are never pooled.
    --}}
    @php($attentionVolume = $this->attentionVolume())
    <div class="fi-section rounded-xl bg-white shadow-sm ring-1 ring-gray-950/5 dark:bg-gray-900 dark:ring-white/10 mt-6 p-6">
        <h2 class="fi-section-header-heading text-base font-semibold text-gray-950 dark:text-white">
            Attention judgements: what happened to every message
        </h2>
        <div class="overflow-x-auto mt-2">
            <table class="w-full text-sm text-left">
                <thead>
                    <tr class="text-xs text-gray-500 dark:text-gray-400">
                        <th class="py-1 pr-4">Messages</th>
                        <th class="py-1 pr-4">Judged</th>
                        <th class="py-1 pr-4">Excluded (by reason)</th>
                        <th class="py-1 pr-4">Failed (by latest kind)</th>
                        <th class="py-1 pr-4">Not judged yet</th>
                    </tr>
                </thead>
                <tbody>
                    <tr class="border-t border-gray-100 dark:border-white/5">
                        <td class="py-1.5 pr-4">{{ $attentionVolume['messages'] }}</td>
                        <td class="py-1.5 pr-4">{{ $attentionVolume['judged'] }}</td>
                        <td class="py-1.5 pr-4">
                            {{ $attentionVolume['excluded'] }}
                            @if ($attentionVolume['excluded_by_reason'] !== [])
                                ({{ collect($attentionVolume['excluded_by_reason'])->map(fn ($n, $reason) => "{$reason}:{$n}")->implode(', ') }})
                            @endif
                        </td>
                        <td class="py-1.5 pr-4">
                            {{ $attentionVolume['failed'] }}
                            @if ($attentionVolume['failed_by_reason'] !== [])
                                ({{ collect($attentionVolume['failed_by_reason'])->map(fn ($n, $reason) => "{$reason}:{$n}")->implode(', ') }})
                            @endif
                        </td>
                        <td class="py-1.5 pr-4">{{ $attentionVolume['not_judged_yet'] }}</td>
                    </tr>
                </tbody>
            </table>
        </div>
        {{-- M27 --}}
        <p class="text-xs text-gray-500 dark:text-gray-400 mt-2">
            A message posted while no attention instruction was configured stays "not judged yet":
            there is no catch-up, so the period chosen decides what this count means.
        </p>

        {{--
            TG-M5.3, C10c (`attention-metrics.md` §2, M30-M32): the misses a person noticed — the
            operator-added items, by their anchor's attention status and by burst size. Counts only.
        --}}
        @php($operatorAdded = $this->attentionOperatorAdded())
        <h3 class="text-sm font-semibold text-gray-950 dark:text-white mt-6">
            Operator-added items, by anchor status and burst size
        </h3>
        @if ($operatorAdded === [])
            <p class="text-sm text-gray-500 dark:text-gray-400 mt-2">No operator-added items in this period.</p>
        @else
            <div class="overflow-x-auto mt-2">
                <table class="w-full text-sm text-left">
                    <thead>
                        <tr class="text-xs text-gray-500 dark:text-gray-400">
                            <th class="py-1 pr-4">Anchor's attention status</th>
                            <th class="py-1 pr-4">Single message</th>
                            <th class="py-1 pr-4">Multi-message</th>
                        </tr>
                    </thead>
                    <tbody>
                        @foreach ($operatorAdded as $operatorAddedRow)
                            <tr class="border-t border-gray-100 dark:border-white/5">
                                <td class="py-1.5 pr-4">{{ $operatorAddedRow['anchor_status'] }}</td>
                                <td class="py-1.5 pr-4">{{ $operatorAddedRow['single'] }}</td>
                                <td class="py-1.5 pr-4">{{ $operatorAddedRow['multi'] }}</td>
                            </tr>
                        @endforeach
                    </tbody>
                </table>
            </div>
        @endif
        {{-- M30, M31, M32 --}}
        <p class="text-xs text-gray-500 dark:text-gray-400 mt-2">
            Multi-message: the anchor's sender posted another message in the same thread within the
            burst gap; review multi-message rows by hand, and record in the pilot notes which were a
            request spread over several messages. "judged_asking" means the model said asking but no
            model item opened; this figure does not say why.
        </p>
    </div>

    {{-- TG-M5.3, C10b: one block per model and attention instruction — never pooled (K3, M28-M29). --}}
    @foreach ($this->attentionBlocks() as $attentionBlock)
        <div class="fi-section rounded-xl bg-white shadow-sm ring-1 ring-gray-950/5 dark:bg-gray-900 dark:ring-white/10 mt-6 p-6">
            <h2 class="fi-section-header-heading text-base font-semibold text-gray-950 dark:text-white" dir="auto">
                {{ $attentionBlock['model'] }} · {{ $attentionBlock['prompt_version'] }} · attention judgement
            </h2>

            <h3 class="text-sm font-semibold text-gray-700 dark:text-gray-300 mt-4">Live judgements</h3>
            <ul class="text-sm mt-1 space-y-1">
                <li>Judged: {{ $attentionBlock['judgements']['judged'] }}</li>
                <li>
                    By intent: {{ $this->intentBreakdown($attentionBlock['judgements']) }}
                    <span class="block text-xs text-gray-500 dark:text-gray-400">
                        Counts, not questions: a message whose own words open the rule set is never
                        judged, so most rule-signalled questions are not counted here.
                    </span>
                </li>
                <li>
                    Judged on time: {{ $this->ratio($attentionBlock['judgements']['on_time'], $attentionBlock['judgements']['judged']) }}
                    <span class="block text-xs text-gray-500 dark:text-gray-400">
                        On time: recorded no later than the message's own settle window
                        (sent time + the burst gap), so its burst is judged with it.
                    </span>
                </li>
            </ul>

            {{--
                C9′'s `attention` row (TG-M5.3, M23′-M24): the questions this judgement opened.
                Dismissed (any reason) ÷ opened is the TG-M5.3 pilot's false-positive gate; the
                breakdown beneath it is diagnostic, counts only, and no gate reads it (K10).
            --}}
            @if ($attentionBlock['model_questions']['opened'] > 0)
                <h3 class="text-sm font-semibold text-gray-700 dark:text-gray-300 mt-4">Questions the model opened</h3>
                <ul class="text-sm mt-1 space-y-1">
                    <li>
                        Model-opened, dismissed (any reason): {{ $this->ratio($attentionBlock['model_questions']['dismissed'], $attentionBlock['model_questions']['opened']) }}
                        <span class="block text-xs text-gray-500 dark:text-gray-400">{{ $this->dismissalBreakdown($attentionBlock['model_questions']) }}</span>
                    </li>
                    <li>Model-opened, answered: {{ $this->ratio($attentionBlock['model_questions']['answered'], $attentionBlock['model_questions']['opened']) }}</li>
                    <li>Model-opened, still unanswered (open or expired): {{ $this->ratio($attentionBlock['model_questions']['unanswered'], $attentionBlock['model_questions']['opened']) }}</li>
                </ul>
            @endif
        </div>
    @endforeach
</x-filament-panels::page>
