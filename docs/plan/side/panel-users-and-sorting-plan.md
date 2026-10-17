# Panel fixes after go-live: two sort orders, a Users screen, moderator ↔ panel account link

## Context

After the production deploy, the operator found three gaps in the Filament panel:
1. **Live Attention Queue** lists the oldest item first (`defaultSort('opened_at', 'asc')`, contract P1). The operator wants the newest first.
2. **Possible Violations:** the operator wants the newest post first.
   - The SQL already sorts this way (`ClassificationMetrics::possibleViolations()`, `ORDER BY m.sent_at DESC`).
   - But the column header doesn't show that it's sorted, and no test pins the order.
3. **There is no Users screen.**
   - Today the only way to add a panel account is the `app:seed-admin` command.
   - Moderators also have no link to a panel account.
   - Linking needs a new nullable column. Alembic owns the schema, so this means migration `0009`.

The work is done and tested locally, then deployed with `scripts/prod/deploy.sh` once the operator has merged it.

**Interpretation, which you can correct at approval:**
- "Descending by `opened_at`" means newest first.
- Both "Waiting" and "Posted" get clickable headers, so one click switches to oldest first.

---

## 1. Live Attention Queue: newest first, sortable

`apps/ai-control/app/Filament/Pages/LiveAttentionQueue.php`
- `TextColumn::make('opened_at')`: add `->sortable()`.
- Change `->defaultSort('opened_at', 'asc')` to `->defaultSort('opened_at', 'desc')`.
- Update the class docblock ("oldest first" becomes "newest first").

The figures table, `oldest_waiting_s` and every metric are unchanged. Only the list order changes.

## 2. Possible Violations: newest first, shown in the header

`apps/ai-control/app/Filament/Pages/PossibleViolations.php`
- `TextColumn::make('posted')`: add `->sortable()`.
- Add `->defaultSort('posted', 'desc')`.
- In the `records()` closure, take `?string $sortDirection` (Filament injects it; see `vendor/filament/tables/src/Concerns/HasRecords.php:108-110`). Keep C4's SQL order as is and only `->reverse()` the rows when the direction is `asc`.
  - No second query, and membership is still read only from C4 (N7).

## 3. Users screen (new resource)

Navigation group **Platform**, the same as Model Profiles. Files follow the Moderators layout:
`app/Filament/Resources/Users/{UserResource.php, Pages/{ListUsers,CreateUser,EditUser}.php, Schemas/UserForm.php, Tables/UsersTable.php}`.

**Form:**
- `name`: required, max 255.
- `email`: required, email format, `unique(ignoreRecord: true)`.
- `password`:
  - `->password()->revealable()`;
  - required on create; on edit, left blank means unchanged (`dehydrated(fn ($s) => filled($s))`);
  - `Password::defaults()` and `->confirmed()`, plus a `password_confirmation` field.
  - The model's `'password' => 'hashed'` cast does the hashing, so there is no manual `Hash::make`.
- `is_panel_operator`: label "Panel access", default on.
  - It is **disabled on your own record**, so an operator can't lock themselves out.
- **No delete action and no bulk action.** Access is withdrawn with the toggle. User ids are stamped on history (`closed_by_user_id`, `opened_by_user_id`, `panel_user_id`), so accounts are kept.

**Table:**
- name and email (searchable);
- panel access (boolean icon);
- linked moderator (`moderator.display_name`, `—` if none);
- created at;
- default sort by name.

**Model:** `User::moderator(): HasOne`.

Any panel operator can manage users. There are no roles today, which matches `canAccessPanel()`.

## 4. Moderator ↔ panel account (optional link)

**Migration** `apps/ai-api/alembic/versions/0009_moderator_panel_user.py`. It is the next free number: the plan of record says later moderation revisions take the next free numbers.
- `op.add_column("moderators", sa.Column("user_id", sa.BigInteger(), nullable=True))`.
- `UniqueConstraint uq_moderators_user_id`: one account maps to at most one moderator.
- **No FK to `users`**, following D-TG-102 (`closed_by_user_id`, `opened_by_user_id` and `panel_user_id` have none either).
- Downgrade drops the constraint, then the column.
- No `GRANT` is needed: the table-level grants cover the new column.

**Other changes:**
- Python ORM parity: add the column and constraint to the `moderators` table in `apps/ai-api/app/infrastructure/models_moderation.py` (around line 261). No Python logic reads it.
- `app/Models/Moderator.php`: add `user_id` to `$fillable` and add `user(): BelongsTo` (to `User`).
- `Moderators/Schemas/ModeratorForm.php`: add `Select::make('user_id')`, labelled "Panel account".
  - It shows on create and edit, is optional and searchable.
  - Options are `User` records shown as "name (email)", validated with `unique(ignoreRecord: true)`.
  - Helper text: linking grants or removes no access.
- `CreateModerator::mutateFormDataBeforeCreate` already passes unknown keys through, so it needs no change.
- `Moderators/Tables/ModeratorsTable.php`: add a "Panel account" column (`user.name`, `—` if none).

## 5. Translations and contracts

- **Translations:** every new label and helper goes through `__()`, with Arabic entries in `apps/ai-control/lang/ar.json` and the English left byte-identical. `PanelTranslationCoverageTest` enforces this.
- **Contract amendments (dated 2026-10-17):**
  - `specs/006-tg-m3-response-tracking/contracts/control-panel-attention.md`: P1 becomes newest first, with a sortable header.
  - `specs/008-tg-m5-ai-classification/contracts/control-panel-classification.md` §3: V1 gains the sortable "Posted" header.
  - `specs/005-tg-m2-groups-and-ownership/contracts/control-panel-moderation.md` §3: the moderator gets an optional panel account, and there is a new Users screen.
- **Plan file:** saved to `docs/plan/side/panel-users-and-sorting-plan.md`.

## 6. Tests

**PHP** (`apps/ai-control/tests/Feature`, `DatabaseTransactions` against `injaz_ai_test`):
- `LiveAttentionQueueTest`: `test_open_items_are_ordered_longest_waiting_first` becomes `…_newest_first`, plus a test that sorting `opened_at` ascending flips the order.
- `PossibleViolationsPageTest`: rows are ordered newest posted first, and `asc` reverses them.
- New `UserResourceTest`:
  - the list loads;
  - create hashes the password, and the new user can sign in and reach `/admin`;
  - edit with a blank password keeps the old hash;
  - a duplicate email is rejected;
  - the access toggle is disabled on your own record;
  - there is no delete or bulk action;
  - a user with access off is refused at `/admin`.
- `ModeratorResourceTest`: a moderator is created with and without a linked account; it can be linked or unlinked on edit; linking an account that is already linked fails validation.

**Python:** `apps/ai-api/tests/moderation/actors/test_migration_0009.py`, modelled on `test_migration_0008.py`:
- the upgrade adds exactly the column and the constraint;
- a planted duplicate `user_id` raises `uq_moderators_user_id`;
- the downgrade restores the `0008` schema object by object.

`test_migrations.py` (empty → head → down → up) covers the round trip.

## 7. Local verification (Mac)

1. Rebuild the migrate image, then run `make migrate`: dev DB at `0009`.
2. `make test-db-reset`: `injaz_ai_test` rebuilt to head.
3. `make check`: ruff, mypy, pytest (with the migration tests), PHPUnit, secret scan. All must pass.
4. Manual check in the browser on the local panel:
   - both lists are newest first, and the header click flips them;
   - create a user, sign in as them in a private window, then switch their access off and confirm they're refused;
   - link that user to a moderator, then unlink;
   - check the Arabic locale on each new screen.
5. I give you the diff summary and the `git switch -c …` / `add` / `commit` / `push` commands. **You** commit, push and merge.

## 8. Production deploy (after merge)

| Step | Who | Action |
|---|---|---|
| 1 | Me | `ssh sambo@84.46.248.13 'cd /var/www/injazedu-ai/repo && git fetch'`, then `scripts/prod/deploy.sh <merged-sha>`. It builds (migrate image included), `pg_dump`s to `../dumps`, lists the pending `0009`, and **asks before applying**. I confirm only `0009`: it is additive, a nullable column on 0–N moderator rows, and no existing data changes. |
| 2 | — | `up -d` recreates the changed containers. **ai-telegram restarts for a few seconds.** Its offset is in `ingestion_state` and Telegram holds updates for 24 h, so nothing is lost. |
| 3 | Me | Verify:<br>• `alembic current` = `0009`;<br>• `/health` ok;<br>• `/up` 200;<br>• ai-telegram has 0 conflicts or errors and `last_success_at` is advancing;<br>• `tg_doctor` exit 0;<br>• the group is still **unmonitored** unless you've enabled it;<br>• the neighbours are still 302 / 200 / 401. |
| 4 | You | In the panel: Users → create the new accounts, then link them in Moderators. |

**Rollback:** `deploy.sh` prints the redeploy command for `50cb31f`/`b1945a7`. The old code ignores the extra nullable column, so a code rollback needs no downgrade. The dump is there if ever required.

**Never on production:** `make check`, `db:seed`, `migrate-down`.

## Critical files

- `apps/ai-control/app/Filament/Pages/LiveAttentionQueue.php`
- `apps/ai-control/app/Filament/Pages/PossibleViolations.php`
- `apps/ai-control/app/Filament/Resources/Users/**` (new)
- `apps/ai-control/app/Filament/Resources/Moderators/{Schemas/ModeratorForm.php, Tables/ModeratorsTable.php}`
- `apps/ai-control/app/Models/{User.php, Moderator.php}`
- `apps/ai-control/lang/ar.json`
- `apps/ai-api/alembic/versions/0009_moderator_panel_user.py` (new)
- `apps/ai-api/app/infrastructure/models_moderation.py`
- The tests listed in §6 and the three contract files in §5.
