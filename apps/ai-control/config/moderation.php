<?php

// The panel's half of `MODERATION_PERCENTILE_MIN_SAMPLES` (`apps/ai-api/app/infrastructure/
// config.py`'s own copy, TG-M3, D-TG-91) — the p90 suppression floor
// (`contracts/attention-metrics.md` M6) — of `MODERATION_INCIDENT_MAX_AGE_S` (TG-M4,
// `contracts/incident-metrics.md`) — the "missed" ceiling — and, since TG-M5.3, of
// `MODERATION_BURST_GAP_S`, the settle gap the attention judgement figures read as `:gap_s`
// (`specs/011-…/contracts/attention-metrics.md` C10b's timeliness). Same defaults on both sides;
// neither reads the other's process.
//
// Both reads are blank-safe (research Finding 2, D-TG-122): `.env` lacking the key and Compose
// passing an empty string are the same "not configured" state. Laravel's `env()` returns that
// empty string as-is — `(int) ''` is `0` — so a bare `env('KEY', default)` reads the default only
// when the key is entirely absent, not when it is set-but-empty. `filled()` treats `null` and `''`
// alike, which is the fix.

return [
    'percentile_min_samples' => filled($v = env('MODERATION_PERCENTILE_MIN_SAMPLES')) ? (int) $v : 10,
    'incident_max_age_s' => filled($v = env('MODERATION_INCIDENT_MAX_AGE_S')) ? (int) $v : 86400,
    'burst_gap_s' => filled($v = env('MODERATION_BURST_GAP_S')) ? (int) $v : 90,
];
