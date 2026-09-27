# Contract: Incident Figures — the exact SQL

**Feature**: `specs/007-tg-m4-policy-incidents` · **Status**: durable from TG-M4 onwards; TG-M7 arranges
these figures and does not redefine them.

Every incident figure the panel shows is one of the statements below, quoted — in Python by
`app/application/moderation/metrics.py`, in PHP by `app/Filament/Resources/Incidents/Concerns/
IncidentMetrics.php`. Neither side re-expresses the other's arithmetic (D-TG-118). Every statement reads
`moderation_incident_state` (`data-model.md` §3.2) and never recomputes a state.

Parameters: `:period_from`, `:period_to` (UTC, half-open), `:max_age_s` (`MODERATION_INCIDENT_MAX_AGE_S`),
`:moderator_id` and `:chat_id` (NULL = no filter).

---

## §1 — Selection

- **M1.** An incident is in a period when `detected_at >= :period_from AND detected_at < :period_to` —
  the **detection** moment, never `opened_at` and never `created_at` (FR-064).
- **M2.** Per-moderator figures filter on `responsible_moderator_id`; per-group figures on
  `telegram_chat_id`. A NULL `:moderator_id` means "no filter", never "unassigned only" — the TG-M3
  convention (its M-A4).
- **M3.** The ceiling is `detected_at + make_interval(secs => :max_age_s)`, written `ceiling` below.

---

## §2 — Outcomes

```sql
SELECT
  count(*)                                                                    AS flagged,
  count(*) FILTER (WHERE s.status = 'closed_false_positive')                  AS false_positive,
  count(*) FILTER (WHERE s.status <> 'closed_false_positive'
                     AND s.resolved_at <= i.detected_at + make_interval(secs => :max_age_s))
                                                                              AS handled,
  count(*) FILTER (WHERE s.status <> 'closed_false_positive'
                     AND (s.resolved_at IS NULL
                          OR s.resolved_at > i.detected_at + make_interval(secs => :max_age_s))
                     AND now() >  i.detected_at + make_interval(secs => :max_age_s))
                                                                              AS missed,
  count(*) FILTER (WHERE s.status <> 'closed_false_positive'
                     AND s.resolved_at IS NULL
                     AND now() <= i.detected_at + make_interval(secs => :max_age_s))
                                                                              AS within_window,
  count(*) FILTER (WHERE s.status <> 'closed_false_positive'
                     AND (s.resolved_at IS NULL
                          OR s.resolved_at > i.detected_at + make_interval(secs => :max_age_s))
                     AND s.first_acknowledgement_at
                         <= i.detected_at + make_interval(secs => :max_age_s))
                                                                              AS acknowledged_not_handled
FROM moderation_incidents i
JOIN moderation_incident_state s ON s.incident_id = i.id
WHERE i.detected_at >= :period_from AND i.detected_at < :period_to
  AND (:moderator_id IS NULL OR i.responsible_moderator_id = :moderator_id)
  AND (:chat_id      IS NULL OR i.telegram_chat_id        = :chat_id);
```

- **M4.** *Handled* means resolved **by** the ceiling, judged by the resolution evidence's own moment
  (the third clarification, FR-059, FR-060). A resolution before the flag is handled.
- **M5.** *Missed* means the ceiling has passed without such a resolution — still open or acknowledged,
  **or resolved afterwards**. Its state may be `resolved`; its outcome stays missed, and a period's figures
  do not move when a late resolution arrives.
- **M6.** *Within window* means not yet resolved and the ceiling not yet passed.
- **M7.** *False positive* is in none of the three and is reported only as itself (FR-037).
  `handled + missed + within_window + false_positive = flagged`, always.
- **M8.** *Acknowledged, not handled* is the acknowledged share of `missed + within_window`, with the
  acknowledgement dated by the ceiling — shown beside them and never counted as handled (FR-061).
- **M9.** **Handled share** = `handled / NULLIF(handled + missed, 0)` — computed by the caller from this
  row, never with within-window incidents in the denominator (FR-062). NULL renders "—", not "0%".
- **M10.** The single documented instability: evidence *dated* by the ceiling but *processed* after it
  moves an incident from missed to handled. That corrects the record with a fact that arrived late; it is
  the only way a settled outcome can change.

---

## §3 — The three timings

```sql
SELECT
  count(*) FILTER (WHERE t_ack  >= 0)                                          AS ack_samples,
  count(*) FILTER (WHERE t_ack  <  0)                                          AS ack_before_flagging,
  percentile_cont(0.5) WITHIN GROUP (ORDER BY t_ack)  FILTER (WHERE t_ack  >= 0) AS ack_median,
  percentile_cont(0.9) WITHIN GROUP (ORDER BY t_ack)  FILTER (WHERE t_ack  >= 0) AS ack_p90,
  max(t_ack)  FILTER (WHERE t_ack  >= 0)                                       AS ack_max,

  count(*) FILTER (WHERE t_conf >= 0)                                          AS conf_samples,
  count(*) FILTER (WHERE t_conf <  0)                                          AS conf_before_flagging,
  percentile_cont(0.5) WITHIN GROUP (ORDER BY t_conf) FILTER (WHERE t_conf >= 0) AS conf_median,
  percentile_cont(0.9) WITHIN GROUP (ORDER BY t_conf) FILTER (WHERE t_conf >= 0) AS conf_p90,
  max(t_conf) FILTER (WHERE t_conf >= 0)                                       AS conf_max,

  count(*) FILTER (WHERE t_enf  >= 0)                                          AS enf_samples,
  count(*) FILTER (WHERE t_enf  <  0)                                          AS enf_before_flagging,
  percentile_cont(0.5) WITHIN GROUP (ORDER BY t_enf)  FILTER (WHERE t_enf  >= 0) AS enf_median,
  percentile_cont(0.9) WITHIN GROUP (ORDER BY t_enf)  FILTER (WHERE t_enf  >= 0) AS enf_p90,
  max(t_enf)  FILTER (WHERE t_enf  >= 0)                                       AS enf_max
FROM (
  SELECT extract(epoch FROM s.first_acknowledgement_at - i.detected_at) AS t_ack,
         extract(epoch FROM s.first_confirmation_at    - i.detected_at) AS t_conf,
         extract(epoch FROM s.first_enforcement_at     - i.detected_at) AS t_enf
  FROM moderation_incidents i
  JOIN moderation_incident_state s ON s.incident_id = i.id
  WHERE s.status <> 'closed_false_positive'
    AND i.detected_at >= :period_from AND i.detected_at < :period_to
    AND (:moderator_id IS NULL OR i.responsible_moderator_id = :moderator_id)
    AND (:chat_id      IS NULL OR i.telegram_chat_id        = :chat_id)
) t;
```

- **M11.** Each timing is its **own** earliest evidence minus the detection moment (FR-051…FR-053). An
  incident contributes to none, one, two or all three; a missing kind contributes nothing — the NULL
  difference fails both `>= 0` and `< 0` (FR-055).
- **M12.** Earliest evidence **before** the flag is counted in `*_before_flagging` and contributes to no
  percentile and no maximum; no negative or zero stand-in is ever produced (the first clarification,
  FR-056). Evidence exactly at the flag is a zero-second sample.
- **M13.** The p90 of each timing is withheld with a stated reason when its own `*_samples` is below
  `MODERATION_PERCENTILE_MIN_SAMPLES` — each timing judged on its own count. Median and maximum are shown
  with their count beside them (FR-063).
- **M14.** No `avg(` appears in this file or in any statement quoting it, and no statement combines
  figures into one number (FR-065).
- **M15.** There is no removal or deletion timing, and no column from which one could be computed
  (FR-057).

---

## §4 — Detection latency — a figure about the system

```sql
SELECT count(*)                                                         AS flagged,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY lat)                 AS latency_median,
       percentile_cont(0.9) WITHIN GROUP (ORDER BY lat)                 AS latency_p90,
       max(lat)                                                         AS latency_max
FROM (
  SELECT extract(epoch FROM i.detected_at - i.opened_at) AS lat
  FROM moderation_incidents i
  WHERE i.detected_at >= :period_from AND i.detected_at < :period_to
    AND (:chat_id IS NULL OR i.telegram_chat_id = :chat_id)
) l;
```

- **M16.** The statement takes **no moderator parameter**: it cannot be attributed to a moderator by
  construction (FR-054). It is shown per group and in total, never per moderator.
- **M17.** It includes false positives: a wrong flag took exactly as long to raise as a right one
  (D-TG-121). p90 suppression as M13, on `flagged`.

---

## §5 — "No data" is not zero

- **M18.** `percentile_cont` and `max` over zero qualifying rows return NULL. The panel renders NULL as
  "no evidence" for a single incident's timing and "no data" for an aggregate — never "0s" (TG-M3's M8).
- **M19.** A single incident's timings on its detail page are the same differences read from
  `moderation_incident_state` for that one row — with a negative difference rendered as "acted before
  flagging", never as a duration.

---

## §6 — Verified by

`tests/moderation/incidents/test_metrics.py` loads a fixed fixture — incidents with one, two and three
kinds of evidence, pre-flag evidence, a late resolution, a false positive, an unassigned incident, and a
group below the percentile floor — and asserts every figure against hand-computed values;
`IncidentMetricsTest.php` asserts the panel renders the same numbers, the suppression reason, "no data",
and no average.
