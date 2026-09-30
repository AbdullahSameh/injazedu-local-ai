# Contract: The Control Panel — Classification

**Feature**: `specs/008-tg-m5-ai-classification` · **Status**: durable from TG-M5 onwards.

What the panel shows of the model, where, in what words, and the one act it adds. The panel **reads**
predictions and never makes them: no model call, no classification, no reclassification, no schema change
(FR-059). Every figure and every list comes from `classification-metrics.md`, quoted once in
`App\Filament\Pages\Concerns\ClassificationMetrics`. Panel locale and chrome stay English and LTR; Arabic
content keeps `dir="auto"` per field (FR-060).

---

## §1 — Words

- **W1.** Confidence is always shown as the model's own report: a number to three places, labelled
  **"self-reported confidence"** — never as a percentage, never as "probability", "chance" or "likelihood"
  (FR-056). A feature test renders every page in §2–§4 and asserts none of those words appears beside a
  confidence, and no `%` sign follows one.
- **W2.** A prediction is always attributed: **"The model's view"**, with the model's roster name, the
  instruction version and the vocabulary version on any detail. An operator's labels are always
  **"operator-assigned"**. The two are never merged into one label.
- **W3.** TG-M4's wording rules hold unchanged on every incident page: the standing sentence, and no other
  `delet` / `remov` substring (TG-M4 D-TG-126). The new pages follow the same rule; the wording test gains
  them.
- **W4.** No average of anything and no combined score, on any page (FR-049, SC-013). TG-M4's no-average test
  gains the new pages.

---

## §2 — Existing screens, minimally changed

### §2.1 Live Attention Queue (FR-052)

- **Q1.** One column: **Model's view** — the category and self-reported confidence chosen by
  `classification-metrics.md` C6 for the row's item. Where no message of the item is classified, the anchor's
  status from C5 (§5).
- **Q2.** Nothing else changes: order, live ageing, the dismiss, hand-open and reassign actions, and TG-M4's
  "Open incident" row action. The model's view never filters, sorts or hides a row.

### §2.2 Incidents — list (FR-053)

- **L1.** One column: **Opened by** — "Operator" or "Model".
- **L2.** One filter: **Opened by**, the same two values.
- **L3.** The figures table: detection latency is shown per opener, from C8 (D-TG-159). Every other TG-M4
  figure is unchanged and includes model-opened incidents.

### §2.3 Incidents — detail (FR-054)

TG-M4's "Why flagged" answer changes; nothing else on the page does.

| Incident | "Why flagged" shows |
|---|---|
| operator-opened, independent | opened by (panel account) · operator-assigned category and severity · **The model's view** of the message (§5) |
| operator-opened, from the possible-violations list | as above, plus **"Flagged from the possible-violations list"** and the listing prediction's model and self-reported confidence |
| model-opened | **"Opened by the model"** · the opening prediction: category, severity, needs-response, needs-moderation, self-reported confidence, model, instruction version, vocabulary version, when it was made · labels marked **"the model's"** |

- **D1.** TG-M4's line "No model classification — arrives with TG-M5" is removed.
- **D2.** A model-opened incident offers exactly TG-M4's three acts — acknowledge, resolve, not a violation —
  under TG-M4's guard, unchanged. Closing it as not a violation is how the model's mistake is recorded (FR-039).

### §2.4 Model roster (FR-058)

- **R1.** The role select and filter offer `moderation`. The params helper text lists the classification keys:
  `num_ctx`, `num_predict`, `temperature`, `reasoning_effort`.
- **R2.** `App\Models\ModelProfile`'s existing guard keeps exactly one active profile per role and refuses to
  leave a role with none; it covers `moderation` unchanged. Activating a classification model never touches the
  `llm` role (SC-010).

---

## §3 — Possible Violations (new page, FR-041…FR-045)

A read-only custom page in the **Moderation Intelligence** navigation group, after Incidents.

| Column | Source (C4) |
|---|---|
| Group | the chat's title |
| Message | `original_text`, `dir="auto"`, truncated; "Text removed" once retention has taken it |
| Posted | `sent_at`, rendered in the operator's timezone |
| Model's view | category · severity · self-reported confidence |
| Why listed | **"Uncertain"** (below the incident threshold) or **"Inconsistent"** (the model contradicted itself) |
| Model | roster name · instruction version |

- **V1.** Rows are exactly C4's: live predictions routed `possible_violation` whose message anchors no incident.
  Default sort: newest posting first. Filters: group, posting period.
- **V2.** One row action, **"Flag message"**: TG-M4's opening form (category and severity required, chosen by the
  operator), which calls `ModerationIncident::openOn($message, $category, $severity, $user,
  promptedByClassificationId: $row->id)`. The incident is operator-opened in every respect (FR-043); it is
  recorded as list-prompted (FR-044); the row then leaves the list.
- **V3.** No other action: no dismissal, no relabel, no bulk action, no model call (FR-045). Recording that a
  listed message was *not* a violation is a review verdict — TG-M8.
- **V4.** Empty state: *"Nothing listed. A message appears here when the model thinks it may need moderation
  but is not confident or consistent enough to open an incident."* With no active classification model the
  page says so instead.
- **V5.** The page never implies the model saw anything happen to a message: it lists what the model thinks a
  message *is*, never what anyone *did*.

---

## §4 — Classification Accuracy (new page, FR-046…FR-051, FR-057)

A read-only custom page in the navigation group. Filters: **period** (posting time, half-open — K1) and
**group** (or all measured groups). Every section is grouped by model, instruction version and vocabulary
version, one block per combination, never pooled (K3). A heading on the page: *"Estimates over the human
labels available. The labels are few and not random; treat every ratio as a floor for discussion, not a
measurement."*

| Section | Figures (all as numerator / denominator) | Source |
|---|---|---|
| **Rule set baseline** | precision per rule version; recall (a floor) | C7, read per M19 |
| **Questions** | rule-kept: model agrees needs an answer · rule-dismissed: model would also have flagged · operator-added: model caught the miss · items no model classified, per label · unverified model-only judgements (a count, never a ratio) | C1, C2 |
| **Violations** | independent flags: model agreed · of those, same category · list-prompted flags: the same, **shown apart** · false-positive closures: model would have raised · model-opened incidents: closed as false positive · listed now | C3, C4 |
| **What happened to every message** | classified · excluded, by reason · failed, by latest kind · not classified yet | C5 |

- **A1.** A ratio with a zero denominator reads "no labelled examples" (M21). A model with no predictions in the
  period has no block (M22).
- **A2.** No percentage is computed or shown; the numerator and denominator are the figure.
- **A3.** No control on the page changes anything.

---

## §5 — When there is no prediction (FR-055)

Wherever **The model's view** would appear, a message with no current prediction shows its C5 status:

| Status | Shown as |
|---|---|
| excluded | *"Not sent to the model — "* + the reason: *moderator's message* · *service announcement* · *media* · *no text* · *sent as the group* · *linked channel's post* · *acknowledgement only* · *text no longer held* |
| failed | *"The model could not classify this message — "* + the kind, in words (*runtime unreachable*, *timed out*, *answer cut off*, *answer malformed*, *confidence out of range*, …) |
| not classified yet | *"Not classified yet — awaiting the model, or recorded before classification began."* |
| no active classification model | *"No classification model is active."* — checked first, from `model_profiles` |

Never blank (FR-055).

---

## §6 — Configuration

The panel reads **no new environment key**. The thresholds a prediction was routed under are shown from the
prediction itself; the panel never reads the classifier's current thresholds, so it can never display a routing
the classifier did not make.

---

## §7 — What the panel may not do

- **P1.** Call a model, classify or reclassify a message, or trigger the catch-up command (FR-059).
- **P2.** Compute a route, an eligibility, a consistency or a classification status in PHP — each is read
  (the stored route; C4's list; C5's status). A helper that decides one is a violation.
- **P3.** Update or delete a prediction or an attempt row. `App\Models\MessageClassification` and
  `App\Models\MessageClassificationAttempt` throw from `updating` and `deleting`, as TG-M4's `ModerationAction`
  does (D-TG-147).
- **P4.** Act on several rows at once, anywhere in this contract.
- **P5.** Post, ban, restrict, delete or react; change the store's shape.

---

## §8 — Verified by

`PossibleViolationsPageTest.php` (membership, the flag action records list-prompted and removes the row, no other
action, empty and no-model states), `ClassificationAccuracyPageTest.php` (figures and denominators against C1–C8's
fixture, never pooled, no average, no percentage), `ModelViewDisplayTest.php` (queue column, incident "why
flagged" for all three kinds, §5's statuses, W1's words), `ClassificationImmutabilityTest.php`, the extended
`IncidentWordingTest.php` and no-average test, and `ModelProfileRoleTest.php` (the `moderation` role, one active,
activation leaves `llm` alone).
