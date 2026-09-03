# Intentionally empty

Alembic (`apps/ai-api/alembic/`) owns the schema for this database, including the `users` table
this panel authenticates against. Laravel never runs a migration here — see research D-06/D-07 and
`contracts/database-roles.md` in `specs/001-m0-foundation/`.

`DB::prohibitDestructiveCommands()` is enabled for every non-testing environment
(`app/Providers/AppServiceProvider.php`) so `migrate:fresh`, `migrate:refresh`, `migrate:reset`, and
`db:wipe` are refused even if someone tries.
