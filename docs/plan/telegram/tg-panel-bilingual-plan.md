> **Status (2026-10-13): implemented and uncommitted.** The operator commits the working tree (Principle IV).
>
> **Operator decisions:** full RTL in Arabic, the choice kept in a cookie, every screen translated.
>
> **What was built:**
> - `lang/ar.json`: 338 entries.
> - `lang/ar/validation.php`.
> - `PanelLocale`, `SetPanelLocale` (persistent) and `SwitchPanelLocale` (`filament.admin.locale`).
> - The user-menu item.
> - Logical-direction classes in the custom views.
>
> **Tests:** `PanelLocaleTest`, `PanelTranslationCoverageTest`, `PanelArabicScreensTest` and
> `IncidentWordingArabicTest`. The suite is 180/180, with the original 140 unchanged.
>
> **The §4 glossary is the agent's draft;** the operator reviews it in `lang/ar.json`.
>
> **Deviations from the plan:**
> - **Durations** use Carbon's full Arabic words. Carbon has no Arabic short units, and with Laravel's
>   English fallback a short duration would print "20m" (`PanelLocale::hasShortDurationUnits`).
> - **Some codes stay raw in both languages:** the accuracy page's technical breakdowns (`reason:n`,
>   `anchor_status`, `judged_asking`), because they are the metrics contract's vocabulary.
> - **Other badge codes** (status, category, severity, chat type, bot standing, assignment role) go through
>   `__($code)`. English still prints the code, and Arabic prints a word.
> - **`IncidentWordingTest`'s fixture builders** moved verbatim into
>   `tests/Feature/Concerns/BuildsIncidentWordingFixtures.php`, so the Arabic twin reads the same screens.

# Bilingual control panel (English default, Arabic) with a language switch in the user menu

## Context

The pilot goes live with a large group while TG-M6–M8 are built. The moderation team reads
English poorly, but every screen in `apps/ai-control` (Filament 5.7.8, Laravel 12) is English.
That is on purpose: D-TG-56 (TG-M2 research), FR-060 and P4 in the `control-panel-*.md` contracts
say "panel locale and chrome stay English and LTR; Arabic content keeps `dir="auto"` per field".

**This change reverses that decision.** Operator decisions, 2026-10-13:
1. **Full RTL in Arabic.** Filament sets `<html dir>` from `filament-panels::layout.direction`
   (`base.blade.php:16`), which is `rtl` for `ar`, so the whole panel mirrors. English stays LTR.
   The per-field `dir="auto"` from D-TG-56 stays in both languages.
2. **The choice is kept in a long-lived cookie.** No schema change; Alembic owns `users`. The choice
   survives logout on the same browser, and a new browser starts in English. A session copy would
   add nothing, so there is none.
3. **Every screen is translated:** queue, incidents, possible violations, accuracy figures, groups,
   moderators, model profiles and login (~190 PHP strings and ~50 Blade text nodes).

English stays the default and stays **byte-identical**. That keeps all 30 existing feature tests
(77 `assertSee*`) and every pinned word in the contracts ("self-reported confidence",
"dismissed (any reason)", the standing deletion sentence) unchanged.

## Approach

### 1. Locale plumbing: one definition, one middleware, one route

- **`app/Support/PanelLocale.php`** (new) holds the single definition:
  - `SUPPORTED = ['en' => 'English', 'ar' => 'العربية']`;
  - `COOKIE = 'panel_locale'`;
  - `DEFAULT = 'en'`;
  - `isSupported(string)` and `other(string)`, the language to offer.
- **`app/Http/Middleware/SetPanelLocale.php`** (new) reads `$request->cookie(PanelLocale::COOKIE)`
  and calls `app()->setLocale()` only when the locale is supported. Otherwise it leaves
  `config('app.locale')` (`en`) alone. Laravel's `LocaleUpdated` sets Carbon's locale too, so
  `forHumans()` durations and `translatedFormat()` dates come out in Arabic (checked: Western digits,
  "ساعة دقيقتين 5 ثواني").
- **`AdminPanelProvider`** changes:
  - Register the middleware in a second call, `->middleware([SetPanelLocale::class], isPersistent: true)`.
    `isPersistent` is required: without it, Livewire update requests (sorting, filters, actions,
    polling the queue) would re-render in English. The second call appends after
    `EncryptCookies` (verified in `HasMiddleware::middleware()`).
  - Add `->authenticatedRoutes(fn () => Route::post('locale/{locale}', SwitchPanelLocale::class)->whereIn('locale', array_keys(PanelLocale::SUPPORTED))->name('locale'))`.
    The route is `filament.admin.locale` and sits beside Filament's own logout route, under the
    panel's auth and CSRF.
  - Add `->userMenuItems([...])` with one `Action::make('locale')`:
    - its label is `PanelLocale::SUPPORTED[PanelLocale::other(app()->getLocale())]`, so the menu
      offers "العربية" in English and "English" in Arabic, each written in its own script so a
      reader of either language can find it;
    - `->icon(Heroicon::OutlinedLanguage)`;
    - `->url(fn () => route('filament.admin.locale', ['locale' => PanelLocale::other(app()->getLocale())]))->postToUrl()`.
      `postToUrl()` works the way Filament's own logout item does (`CanOpenUrl::postToUrl`).
- **`app/Http/Controllers/SwitchPanelLocale.php`** (new, invokable):
  - queues `cookie()->forever(PanelLocale::COOKIE, $locale)`;
  - returns `back(fallback: Filament::getUrl())`.
  - Panel middleware already includes `AddQueuedCookiesToResponse`.

### 2. Translation files

- **`lang/ar.json`** (new) maps each English string, used as the key, to its Arabic text.
  - There is **no `lang/en.json`**: with no entry, `__()` returns the key, so English output is
    unchanged by construction.
  - Placeholders keep Laravel's `:name` form.
- **`lang/ar/validation.php`** (new) holds Arabic validation messages, but only for the rules the
  forms use: `ModeratorForm`, `ModelProfileForm`, `TelegramChatForm`, the hand-open, the incident
  actions. List the rules first with `grep -rn "required\|unique\|max\|integer\|rules(" app/Filament`.
  Laravel ships English only.
- Filament's own chrome (tables, filters, pagination, actions, modals, login, user menu, "Sign out")
  is already translated by `vendor/filament/*/resources/lang/ar`, so it needs no work.
- `.dockerignore` does not exclude `lang/`, so `COPY . .` picks it up. Rebuild the `ai-control` image.

### 3. Wrapping strings: one pattern per kind of literal

| Literal today | Change | Example files |
|---|---|---|
| `->label('Group')`, `->placeholder()`, `->heading()`, `->modalHeading()`, `->helperText()`, notifications | `__('Group')` | every `Tables/*`, `Schemas/*`, `Actions/*`, `LiveAttentionQueue.php`, `PossibleViolations.php` |
| `static $navigationGroup` / `$navigationLabel` / `$title` (a property initialiser can't call `__()`) | delete the property, override `getNavigationGroup()`, `getNavigationLabel()` and `getTitle()` returning `__()` | `IncidentResource`, `ModeratorResource`, `TelegramChatResource`, `ModelProfileResource`, the 3 pages |
| Resource model names Filament derives from the class ("New moderator", breadcrumbs) | add `getModelLabel()` / `getPluralModelLabel()` returning `__()` | the 4 resources |
| `private const …_LABELS` maps (constants can't call `__()`) | keep the English values as keys, translate on read: `__(self::KIND_LABELS[$kind] ?? $kind)` | `IncidentDisplay`, `ModelView`, `IncidentsTable` (STATUSES/CATEGORIES/SEVERITIES), `OpenIncidentAction` |
| Concatenated sentences (`'Not sent to the model — '.$x`, `number_format(...).' self-reported confidence'`) | one key with a placeholder: `__('Not sent to the model — :reason', ['reason' => …])`. **The English rendering must match exactly.** | `ModelView`, `IncidentDisplay`, `*Metrics` concerns |
| Raw codes shown as-is today (`SPAM_OR_AD` in `ModelView::status`, `LiveAttentionQueue:256`, attention intents) | `__($code)`: English still prints the code, Arabic prints a label | `ModelView`, `LiveAttentionQueue`, `ClassificationAccuracy` |
| Blade text nodes, headers, "No data for this period." | `{{ __('…') }}` | the 6 views under `resources/views/filament/` |

**Never translated:**
- message text, group titles, moderator names;
- model names, `prompt_version`s, SHA pins, ids;
- the `Asia/Riyadh` identifier and numbers.

**RTL hygiene in custom views.** Their Tailwind utilities (`pr-4`, `text-left`, `mt-6`, `flex`)
are **not in Filament's compiled CSS** (checked: 0 matches in `public/css/filament/filament/app.css`).
They do nothing today, so cells already inherit the page's `dir`. Change them anyway, `text-left` →
`text-start` and `pr-4` → `pe-4` (≈140 occurrences, mechanical), so a later custom theme cannot break
RTL. Keep `dir="auto"` everywhere it is today.

### 4. The Arabic wording keeps the same promises as the English

Draft `ar.json` from a glossary, and **have the operator approve the glossary before the full file is
written**. Proposed core terms:

| English | Arabic (proposed) |
|---|---|
| Moderation Intelligence / Platform | ذكاء الإشراف / المنصة |
| Live Attention Queue | قائمة المتابعة المباشرة |
| Incidents / Possible Violations | المخالفات / مخالفات محتملة |
| Classification Accuracy | دقة التصنيف |
| Groups / Moderators / Model Profiles | المجموعات / المشرفون / ملفات النماذج |
| Model's view | رأي النموذج |
| self-reported confidence | ثقة يقدّرها النموذج بنفسه |
| Member discussion / Not a real question | نقاش بين الأعضاء / ليس سؤالاً فعلياً |
| dismissed (any reason) | مُستبعَد (لأي سبب) |
| Expelled from the group (not banned) | أُخرج من المجموعة (دون حظر) |

The Arabic wording keeps the same rules as the English:
- **Confidence** always says the model reported it itself. No "احتمال" (probability), "نسبة"
  (percentage) or `%`.
- **Incident screens:**
  - Only the standing sentence and the "Text removed" marker may mention deletion: حذف / إزالة /
    أُزيل / محذوف.
  - `expulsion` is never "إزالة" (removal).
- **The queue's "Message removed"** dismissal stays phrased as the operator's own judgement.
- **No average or composite score:** there is nothing new to compute.

### 5. Tests (new; existing tests stay untouched)

- **`tests/Feature/PanelLocaleTest.php`**:
  - With no cookie, a panel page renders `lang="en"` and `dir="ltr"`, and the user menu offers "العربية".
  - Posting `filament.admin.locale` with `ar` queues the cookie and redirects back. With the cookie,
    the page renders `lang="ar"` and `dir="rtl"`, an Arabic navigation label, and offers "English".
  - An unsupported locale gets 404. A guest is redirected to the login page.
  - A garbage cookie value falls back to English.
  - `SetPanelLocale` is in Livewire's persistent middleware.
- **`tests/Feature/PanelTranslationCoverageTest.php`**:
  - Scan `app/` and `resources/views/` for literal `__('…')` / `__("…")` keys. Each must exist in
    `lang/ar.json` with a non-empty value.
  - Each Arabic value's set of `:placeholders` must equal its key's.
  - No `ar.json` key may be unused, so no translation goes stale.
- **`tests/Feature/IncidentWordingArabicTest.php`** repeats `IncidentWordingTest`'s fixture under the
  `ar` cookie. It strips the Arabic standing sentence and marker, then asserts no
  `حذف|إزال|أزيل|محذوف` remains on the list or view page.
- **The Arabic confidence rule:** `ModelView::confidence()` under `ar` contains the approved
  "self-reported" term and no `%` / احتمال / نسبة.

### 6. Records (docs only, after approval)

- Save this plan as `docs/plan/telegram/tg-panel-bilingual-plan.md`.
- **CLAUDE.md** "Panel rules": "the panel locale and chrome stay English and LTR" becomes "bilingual:
  English default, Arabic (RTL) chosen per browser from the user menu; Arabic content keeps
  `dir="auto"` per field; new UI strings go through `__()` with an `ar.json` entry (tested)".
- Add a one-line dated "superseded by" note, without rewriting closed history, to:
  - D-TG-56 in `specs/005-tg-m2-groups-and-ownership/research.md`;
  - P4 in `specs/006-tg-m3-response-tracking/contracts/control-panel-attention.md`;
  - line 8 of `specs/008-tg-m5-ai-classification/contracts/control-panel-classification.md`.
- From now on, every M6–M8 panel string goes through `__()` and needs an `ar.json` entry. The
  coverage test fails otherwise.

## Implementation order

1. The plumbing (§1) and `PanelLocaleTest`, before any string is touched.
2. The operator approves the glossary (§4).
3. Wrap strings and fill `ar.json` one screen at a time: Live Attention Queue → Incidents (list, view,
   actions, notices) → Possible Violations → Classification Accuracy → Groups → Moderators → Model
   Profiles → validation. Run the suite after each screen. The English assertions must stay green.
4. The coverage test and the Arabic wording and confidence tests.
5. The logical-direction class changes (§3), then the docs (§6).

## Verification

- `make check`: the full PHP feature suite, unchanged and green, plus the new tests.
  If `injaz_ai_test` is empty, run `make test-db-reset` first (shared dev Postgres).
- In the browser, after `docker compose build ai-control && make up`:
  - log in at `/admin`, open the user menu, choose "العربية";
  - the page reloads RTL in Arabic;
  - sort or filter the Live Attention Queue and let it poll. It must stay Arabic (persistent
    middleware);
  - open an incident: durations and dates are in Arabic, and Arabic message text still reads right
    with `dir="auto"`;
  - log out: the login page stays Arabic;
  - switch back to "English": every screen matches the pre-change English.
- `grep -rn "->label('" app/Filament` finds no unwrapped literal. The coverage test enforces the same.
