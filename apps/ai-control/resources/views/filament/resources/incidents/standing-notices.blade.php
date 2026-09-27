{{--
    `control-panel-incidents.md` §1.4: the standing sentence appears on the view page and beneath
    the list, always (P4) — the exact wording `live-attention-queue.blade.php` already carries, so
    the two milestones never say this two different ways. The bot-not-administrator notice (P5)
    and the channel-sender notice (P6) are per-incident: they render only when `$record` is given
    and their own condition holds, so the list page (no single incident) shows the standing
    sentence alone.
--}}
<p class="fi-in-text text-sm text-gray-500 dark:text-gray-400 mt-4">
    Telegram does not report message deletion in groups; no removal evidence is available.
</p>

@isset($record)
    @if ($record !== null)
        @php
            $chat = $record->chat;
            $anchor = $record->anchorMessage();
        @endphp

        @if ($chat !== null && $chat->bot_status !== 'administrator')
            <p class="fi-in-text text-sm text-gray-500 dark:text-gray-400 mt-2">
                The bot is not currently an administrator in this group, so reactions and membership changes there cannot be observed.
            </p>
        @endif

        @if ($anchor !== null && $anchor->sender_chat_id !== null && $anchor->telegram_user_id === null)
            <p class="fi-in-text text-sm text-gray-500 dark:text-gray-400 mt-2">
                This message was sent on behalf of a channel or the group itself. No membership evidence can arrive for it; it can only be resolved by confirmation.
            </p>
        @endif
    @endif
@endisset
