<?php

// The panel's half of `MODERATION_PERCENTILE_MIN_SAMPLES` (`apps/ai-api/app/infrastructure/
// config.py`'s own copy, TG-M3, D-TG-91) — the p90 suppression floor
// (`contracts/attention-metrics.md` M6). Same default (10) on both sides; neither reads the
// other's process.

return [
    'percentile_min_samples' => (int) env('MODERATION_PERCENTILE_MIN_SAMPLES', 10),
];
