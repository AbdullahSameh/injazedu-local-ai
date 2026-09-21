# Contract: The Control Panel's Moderation Surface

**Status**: the first screens in the Moderation Intelligence domain, and the first navigation groups in
the panel's history. This document is what TG-M3's queue page, TG-M4's incidents resource, TG-M6's
alert rules and TG-M7's dashboards inherit.

**Framework, measured**: Filament **v5.7.8**, Laravel 12, PHP 8.2, PHPUnit 11 (not Pest). Resources are
auto-discovered — `AdminPanelProvider` already calls `discoverResources(in: app_path('Filament/Resources'),
for: 'App\Filament\Resources')` — so nothing is registered by hand.

---

## §0 — ⚠ Per-navigation-group text direction does not exist in this framework

The source plan's §17 asks for *"`direction: rtl` and Arabic labels for this navigation group only"*.
The installed framework cannot do the first half:

```
vendor/filament/filament/resources/views/components/layout/base.blade.php:16
    dir="{{ __('filament-panels::layout.direction') ?? 'ltr' }}"

vendor/filament/filament/resources/lang/en/layout.php:5   'direction' => 'ltr'
vendor/filament/filament/resources/lang/ar/layout.php:5    'direction' => 'rtl'
```

One translation key, resolved from the application locale, written once onto `<html>`. There is no
per-resource, per-page or per-group direction anywhere in v5.7.8. Switching the locale to `ar` turns
the **entire** panel RTL and translates all of its chrome, including the model-roster screen — which is
exactly what "for this navigation group only" forbids.

**Normative resolution (D-TG-56).** The panel locale and `dir` are **not** changed. Direction is set
per field of Arabic content:

- text columns and inputs carrying group titles, moderator names and notes get `dir="auto"`;
- labels and the navigation group name are Arabic string literals on the resources, which needs no
  locale.

`auto` rather than `rtl` is deliberate and is the better answer even where `rtl` were available: the
plan's own §17 example lists *"الرخصة المهنية"* beside *"STEP"*, so the column genuinely mixes scripts,
and `auto` lets the browser choose per value from the first strong character. A fixed `rtl` would
mis-place the punctuation of a Latin-script title just as a fixed `ltr` mis-places an Arabic one.

A full panel localisation stays out of scope. If it is ever wanted, it is a locale change, it affects
the whole panel by design, and it is a milestone of its own.

---

## §1 — Navigation

**Normative.** Two navigation groups after this milestone, declared as plain strings:

```php
protected static string|UnitEnum|null $navigationGroup = 'Moderation Intelligence';
```

The type is `string|UnitEnum|null` — measured at
`vendor/filament/filament/src/Resources/Resource/Concerns/HasNavigation.php:24`. Note it is `UnitEnum`,
**not** `BackedEnum`, which is what `$navigationIcon` takes; getting them the wrong way round is a
fatal error rather than a lint warning.

| Resource | Group | Milestone |
|---|---|---|
| Telegram Groups | `Moderation Intelligence` | TG-M2 |
| Moderators (+ Assignments) | `Moderation Intelligence` | TG-M2 |
| Model Profiles | `Platform` | **edited here** |

`ModelProfileResource` gaining `'Platform'` is the one-line change to existing panel code the source
plan names, and it exists solely so the panel's first navigation group does not leave that screen
orphaned at the root. It is additive: no behaviour, no query, no form field changes.

**Directory layout** follows the installed convention exactly, as `ModelProfiles/` already does:

```
app/Filament/Resources/TelegramChats/
├── TelegramChatResource.php
├── Pages/{ListTelegramChats,EditTelegramChat}.php
├── Schemas/TelegramChatForm.php
└── Tables/TelegramChatsTable.php

app/Filament/Resources/Moderators/
├── ModeratorResource.php
├── Pages/{ListModerators,CreateModerator,EditModerator}.php
├── Schemas/ModeratorForm.php
├── Tables/ModeratorsTable.php
└── RelationManagers/AssignmentsRelationManager.php
```

---

## §2 — Telegram Groups

**Purpose.** Turn measurement on, one group at a time, and make coverage loss visible.

**Columns.** Platform identifier · kind · title (`dir="auto"`) · bot standing and when observed ·
whether the bot may remove messages · when anything last happened · measured.

**The measured toggle** is the deliberate act of FR-018. It writes one boolean and **starts nothing** —
no bulk job, no queue message. Catching a group up on events captured before the switch is the operator's
explicit command (`message-derivation.md` §7), and the screen's help text names it.

**No create, no delete.** Groups are discovered by capture, never typed in, and deleting one would
orphan messages and assignments. The resource exposes list and edit only.

**Coverage, visible at a glance (FR-049).** Two states must be distinguishable without opening a
record, because both are silent by nature:

| State | Why it matters |
|---|---|
| Measured, no current primary owner | Items and incidents will accumulate with nobody responsible |
| Measured, bot is not an administrator | Several event kinds stop arriving **with no error anywhere** — the source plan's §27 calls this the single most likely way the system quietly stops working |

A coverage-losing standing change never clears `is_monitored`: the group stays measured so the loss
shows. Switching it off would tidy away the failure.

**The course reference** is a plain integer field with no relational link and no validation. The
reference application holds invite URLs rather than numeric chat identifiers, a bot cannot resolve a
link to an identifier, and that directory is read-only — so the mapping is manual, by design, and
nothing is consulted across the host boundary.

---

## §3 — Moderators, and Assignments

**Purpose.** Name the people, and hand over ownership without ever producing two owners or none.

**Creating a moderator** takes a stable display name and **either** an observed sender identity
**or** a numeric platform identifier that has not been observed yet — the latter creating a placeholder
identity. The runbook's TG-M2 step has the operator collect identifiers before anyone has necessarily
posted, so the not-yet-observed path is the normal one, not a fallback.

**Candidates, proposed not granted (FR-031).** When mapping a moderator for a group, the people the
platform has been observed treating as its administrators are offered as candidates, read from the
already-stored captured events. The panel makes **no** platform call — FR-050 forbids it and the data is
already here. Confirming a candidate is what creates the mapping. An administrator on the platform is
not a moderator in this domain, and the two lists are allowed to differ.

**Deactivating** a moderator changes only their availability for new assignments. Their record, their
assignment history and every `is_from_moderator` already written stay exactly as they are.

**Assignments are a relation manager**, not a resource of their own: they are never navigated to
independently, and they must be created through the handover action rather than a free-form create
form, which a top-level resource would invite bypassing.

**The reassign action.** One action, performing the whole protocol of `moderator-ownership.md` §2:

**Normative.** It MUST close the incumbent and open the successor in one transaction, using **one**
timestamp value bound to both sides, and it MUST delegate to the Eloquent model method rather than
inlining the two writes.

```php
$at = now();                                  // ONE value — see below
DB::transaction(function () use ($at, …) { … });
```

Two separate `now()` calls are the bug, and it is invisible: Laravel's `now()` is evaluated per call,
so the incumbent's `valid_to` and the successor's `valid_from` differ by microseconds and leave a hole
in ownership history that **no constraint detects** and that `responsible_at` reports as "nobody
responsible". Measured at ~10 ms in research probe 3.

Delegation to the model (not the action) mirrors `ModelProfile::save()`, which wraps itself in
`DB::transaction()` and enforces its own invariant at the model layer *"so they hold regardless of
entry point (panel, tinker, a future artisan command) — not only when a Filament form happens to be in
front of them."* That sentence is the precedent; this action follows it.

**The history view** lists every past and current assignment with its role, its interval and its note,
in chronological order. Nothing in it is deletable.

---

## §4 — What the panel may not do

**Normative.** Unchanged from the existing panel's standing, and restated because this milestone
triples its surface:

| Prohibition | Why |
|---|---|
| No schema change | Alembic owns the schema; `config/database.php` records it and `DB::prohibitDestructiveCommands()` is on outside testing |
| No `GRANT` needed, none added | `ALTER DEFAULT PRIVILEGES FOR ROLE ai_migrator` already reaches `ai_control` in both databases (research probe 9). This is the first milestone where the panel touches new tables, so it was checked before any code was written |
| No platform call | The panel never speaks to Telegram. Everything it shows is stored state |
| No model call | Not in this milestone, and not from the panel in any later one |
| No bulk derivation | The one action with real data-volume consequences is a command, not a button |
| No delete of a group, a message, or an assignment | All are history |

---

## §5 — Tests

Following Principle I, and consistent with the existing `ModelProfileResourceTest`:

**Tested** — the invariants, not the framework:

| Behaviour | Why it earns a test |
|---|---|
| Reassign leaves exactly **one** owner at the exact handover instant | Finding 2: the failure is silent and the screen looks right |
| Reassign with a failure induced partway leaves the incumbent current and no successor open | Atomicity is the whole point of the single transaction |
| A second current primary is refused | The database invariant, attempted through the model |
| Opening/closing does not delete or rewrite a closed interval | The history is the product |
| The measured toggle starts no job | R2 of `message-derivation.md` §7 |
| Mapping a not-yet-observed identifier creates exactly one placeholder | The runbook's normal path |
| The panel makes no platform call and runs no schema change | Standing prohibitions, cheap to assert |

**Exempt** — recorded so the omissions are deliberate: Filament table rendering, pagination, column
sorting and filtering; form validation messages; Eloquent attribute casting; navigation-group
placement; the exact wording of help text; anything that would be a test of Filament rather than of
this domain.

**Isolation.** `DatabaseTransactions` against `injaz_ai_test`, as the existing feature tests do —
never `RefreshDatabase`, `DatabaseMigrations` or `migrate:fresh` (Constitution II). `phpunit.xml` takes
the connection from `.env.testing`, deliberately not sqlite, so the `_test` guard is real.

---

## §6 — Inherited by later milestones

So the next four milestones do not each re-decide these:

1. The navigation group name is `'Moderation Intelligence'`, a plain string.
2. Direction is per-field `dir="auto"`; the locale is never switched.
3. Anything that mutates an interval goes through the model, in one transaction, with one timestamp.
4. Anything with real data volume is a command, not a button.
5. The panel reads stored state only — no platform call, no model call, no schema change.
6. Screens are tested for invariants; Filament's own behaviour is not re-tested.
