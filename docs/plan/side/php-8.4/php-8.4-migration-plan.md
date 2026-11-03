# PHP 8.2 → 8.4 Migration Plan (ai-control and kunooz.ai)

> Written 2026-10-25. **Completed 2026-11-02**: every phase is done; the progress log is the record.
> Deadline: **2026-12-31**, when PHP 8.2's security support ends.
> Follows `docs/plan/side/php-cve/contabo-php-cve-2026-security-audit.md` (P2-4).

## Why, and what is in scope

PHP 8.2 gets no security fixes after 2026-12-31. Two of the VPS's sites still run it:

| Site | Runs on | Where PHP is set |
|---|---|---|
| ai-control.injazedu.co (injazedu panel) | FrankenPHP 1.13.3 / PHP 8.2.35, in Docker | `apps/ai-control/Dockerfile.prod` (production) and `apps/ai-control/Dockerfile` (development) |
| kunooz.ai (k-wating-list) | the server's own `php8.2-fpm` (Sury PPA) | the server: installed packages and the nginx vhost's socket |
| phpMyAdmin (127.0.0.1:8088, tunnel only) | the same `php8.2-fpm` | the same |

The clinic (amin.kunooz.ai) already runs PHP 8.4.27 and is out of scope. The ai-api service is Python and is
also out of scope.

PHP 8.4 gets security fixes until **2028-12-31**.

---

## What was checked (2026-10-25)

**Code compatibility (on the Mac's Homebrew PHP 8.4.2):**
- ai-control: the full feature suite passes (224 tests, 3107 assertions), with no deprecations, warnings or
  notices reported.
- k-wating-list: 16 tests pass and 19 fail, exactly as on 8.2. The 19 are leftover starter-kit tests for
  routes that are commented out, and they are unrelated to the PHP version.
- `php -l` on 8.4 over `app/`, `config/`, `routes/` and `database/` of both projects: no errors and no
  deprecations, for example no implicitly nullable parameters.
- `composer check-platform-reqs --lock --no-dev` on 8.4: nothing missing for either project.
- Both `composer.json` files require `"php": "^8.2"`, which already allows 8.4.

**Images:** these tags exist:
- `dunglas/frankenphp:1.13.3-php8.4.27-bookworm`, the same FrankenPHP and Debian as today;
- `php:8.4.27-cli-trixie`. Today's development image, `php:8.2-cli`, is also trixie.

**Server (read-only and apt dry-runs):**
- `php8.4-cli` 8.4.27 and most 8.4 extensions are already installed (from the CVE patch).
  - **Installing** `php8.4-fpm`, `php8.4-xml` and `php8.4-bcmath` adds exactly those three packages and
    upgrades nothing else.
  - **Purging** `php8.2*` later removes only the 8.2 packages; phpMyAdmin stays installed.
- **What uses the 8.2 socket:** only two nginx sites, `kunooz.ai` and `phpmyadmin-local`, both via
  `fastcgi_pass unix:/run/php/php8.2-fpm.sock`.
  - No cron job, queue worker or systemd unit uses host PHP.
  - `/etc/cron.d/php` is Debian's session cleaner, which covers every installed version.
- **The 8.2 FPM pool** (`www.conf`) is the package default: `www-data`, `pm.max_children = 5`.
- **The 8.2 FPM `php.ini`** differs from `php.ini-production` only in `post_max_size`/`upload_max_filesize`
  (64M). Those are overridden anyway by `conf.d/99-security.ini`, which sets upload progress off, 8M and 2M.
- **The host's default `php`** (the alternatives link) is **8.5** with almost no extensions. That is why
  host commands are run as `php8.2 …` today.
- **Packages left over:**
  - the `php8.5-*` CLI packages are unused;
  - `libapache2-mod-php8.2` is installed, although Apache is not;
  - `phpmyadmin` is Ubuntu's `5.2.1+dfsg-3`.

**The Mac:** Homebrew has `php` (8.4.2), `php@8.3`, `php@8.2` (8.2.27), `php@8.1` and `php@7.4`.
- `~/.zshrc` lines 108–109 put `php@8.2` first on the `PATH`, which is how the PHP version is chosen today.
- `make check` runs the panel tests with whatever `php` is first.
- Note: Homebrew's unversioned `php` formula moves to the newest PHP on `brew upgrade` (8.5). The plan
  therefore installs `php@8.4` by name.

---

## Decisions for the operator

| # | Decision | Recommendation |
|---|---|---|
| D1 | The target version | **8.4**: the same as the clinic, tests already pass, security fixes until 2028-12-31. 8.5 would last a year longer (to 2029-12-31), but it is newer and was not tested here |
| D2 | PHP on the Mac | **Install `php@8.4` and change `~/.zshrc` lines 108–109 from `php@8.2` to `php@8.4`**, your usual way of switching. If another local project still needs 8.2, switch back for that project only. Either way, `make check` gets a guard that refuses to run the panel tests on PHP < 8.4 |
| D3 | phpMyAdmin on the host | **Keep it, moved to 8.4**, and check it once through the tunnel. Ubuntu's 5.2.1 may log PHP 8.4 deprecation notices; they are not shown to the browser. The alternative is to remove it and use a desktop MySQL client over the same SSH tunnel |
| D4 | Raise `"php"` to `^8.4` in both `composer.json` files | **Yes, once each site runs 8.4.** Composer then refuses to install on 8.2 by accident |

## Progress log

**2026-10-25 — Phase A done (the Mac).**
- **D2, as the operator chose it:** `php@8.2` stays installed *and* stays the default.
  - A hook in `~/.zshrc` (after the `php@8.2` PATH lines; backup in `~/.zshrc.bak-php84-20261025`) puts
    `php@8.4` first on every `cd` into `~/Projects/injazedu-local-ai`, `~/Projects/kunooz/k-wating-list`
    or `~/Projects/clinic`, and takes it off again outside them.
  - To add a project, add its folder to `_php84_dirs`.
  - Checked in new shells:
    - `php` and `composer` run on 8.4.27 inside the three projects;
    - they run on 8.2.27 in another project (`~/Projects/aspire`) and in `~`.
- **`brew install php@8.4`** installed 8.4.27, which has `pdo_pgsql`, `pgsql`, `pdo_mysql`, `pdo_sqlite`,
  `intl`, `zip`, `mbstring`, `gd` and OPcache.
- **A side effect, fixed:** the install moved the shared `net-snmp` library from 5.9.4 to 5.9.5.
  - The old unversioned `php` formula (8.4.2) linked the old library, so it broke. That is
    `/opt/homebrew/bin/php`, which nothing reaches by name, because `php@8.2` comes first on the PATH.
  - Cause: the install was run with `HOMEBREW_NO_INSTALLED_DEPENDENTS_CHECK=1`, which stopped Homebrew from
    rebuilding that dependent.
  - Fixed with `brew upgrade php`, so the unversioned formula is now 8.5.12, as a normal `brew upgrade` would
    make it. The 8.4.2 keg is kept.
  - `php@8.4`, `8.3`, `8.2`, `8.1` and `7.4` were checked, and all run.
- **`make check` on 8.4.27:** all checks passed.
  - The panel feature tests show `Runtime: PHP 8.4.27`: 224 tests, 3107 assertions.
  - pytest: 1441 passed.

**2026-10-25 — Phase B prepared locally (not committed).**
- **The changes:**
  - `Dockerfile.prod` → `dunglas/frankenphp:1.13.3-php8.4.27-bookworm`.
  - `Dockerfile` (development) → `php:8.4.27-cli-trixie`.
  - `composer.json` → `"php": "^8.4"`.
  - `composer.lock`: `composer update --lock` on 8.4 changed the platform entry and the hash. It also
    changed phpdotenv's source URL, because that project moved from `vlucas/` to the `phpdotenv/` GitHub
    organization. The commit and version are the same; no package changed.
  - `scripts/check.sh`: a guard before the PHP feature test. It refuses `php` < 8.4 with a message: tested,
    refused on 8.2.27, passed on 8.4.27.
  - `docs/runbooks/m0-foundation.md` → "PHP ≥ 8.4".
- **`make check` on 8.4.27:** all checks passed (panel 224 tests, pytest 1441).
- **The production image, built locally:**
  - FrankenPHP 1.13.3 / PHP 8.4.27;
  - upload progress 0, `post_max_size` 2M, OPcache on, the four extensions present;
  - `composer audit` clean, running as `panel`;
  - `/up` and `/admin/login` answer 200, and no errors or deprecations were logged.
- **The development image, built locally:** PHP 8.4.27 with its extensions; `/up` and `/admin/login`
  answer 200.
- Both test images were deleted afterwards.
- The local development stack's `ai-control` container still runs the old 8.2 image. It moves to 8.4 at
  its next rebuild (`docker compose build ai-control`).

**2026-10-25 — Phase B deployed** (`745b329` → `be0af04`, PR #20; log `~/deploy-be0af04.log`).
- **Before the deploy,** the old 8.2 image was tagged `injazedu-local-ai-ai-control:pre-php84-20261025`.
- **The deploy:** no migrations were pending (`0012 (head)`). Only `ai-control` was recreated; the Python
  services kept running.
- **The live container:**
  - FrankenPHP 1.13.3 / PHP 8.4.27;
  - upload progress 0, OPcache on;
  - `composer audit` clean, running as `panel`.
- **Endpoints:**
  - `/admin/login` answers 200 from the server and from outside;
  - `ai.injazedu.co/health/live` answers 200;
  - a multipart POST still gets 415;
  - no errors or deprecations in the log.
- **Rollback:** `scripts/prod/deploy.sh 745b329e0d42e618c2d8d42addb58e5890ba0bf5`.
- **Next:** Phase C (kunooz.ai and phpMyAdmin onto host 8.4).
- **Add to the 2026-11-01 cleanup:** the `pre-php84-20261025` image.

**2026-10-25 — Phase C prepared:** `~/p84-host-fpm.sh` is on the server (not run yet).
- **Run it:** `ssh -t sambo@84.46.248.13 sudo bash ~/p84-host-fpm.sh`.
- **Report:** `~/p84-host-fpm-report.txt`. **Backups:** `/root/php84-backup/<ts>/`.
- **What it does, in order:**
  1. Re-runs the apt dry run and stops if it would install anything beyond the three packages or remove
     anything.
  2. Installs them, with needrestart only listing.
  3. Copies `99-security.ini` and checks FPM 8.4. It stops if FPM 8.4 lacks any module FPM 8.2 loads
     (49), if upload progress isn't off, or if the socket is missing.
  4. Runs the canary on `127.0.0.1:8089`, which mirrors the live vhost plus `HTTPS on`:
     - `/en` and `/ar/waiting-list` and `/login`: expect 200;
     - `/log-viewer`: expect 403;
     - `POST /register`: expect 405.
     It removes the canary either way.
  5. Switches both vhosts with `sed`, then runs `nginx -t` and a reload.
  6. Runs the same checks live, plus phpMyAdmin's 401. If they fail, it restores the vhosts from the backup
     and reloads.
  7. Sets `update-alternatives --set php /usr/bin/php8.4`.
- `php8.2-fpm` stays running.

**2026-10-25 18:31Z — Phase C done** (report `~/p84-host-fpm-report.txt`; backups in
`/root/php84-backup/20261025T183129Z/`).
- **The first attempt didn't reach the server.** No session was recorded and nothing changed. The second
  run worked.
- **Installed:** exactly `php8.4-fpm`, `php8.4-xml` and `php8.4-bcmath` (8.4.27, Sury), as the dry run
  showed.
- **FPM 8.4:**
  - `php-fpm8.4 -t` passes;
  - it loads every module FPM 8.2 loaded;
  - upload progress Off, `post_max_size` 8M, `upload_max_filesize` 2M, `display_errors` and `expose_php`
    Off;
  - the pool is the package default (`www-data`, 5 children).
- **The canary on 8.4:** `/en` and `/ar/waiting-list` 200, `/login` 200, `/log-viewer` 403, `POST /register`
  405.
- **Live:**
  - both vhosts are on `php8.4-fpm.sock` (per `nginx -T`), and the same answers come back;
  - phpMyAdmin answers 401, its password prompt;
  - from outside: the same 200s and the 405.
- **The host's `php`** is now 8.4.27. `php artisan` (Laravel 12.70.1) and `composer` run on 8.4 without a
  suffix.
- `php8.2-fpm` is still active and unused, for rollback until Phase E.
- **The `locale: Cannot set LC_*` lines** in the report come from the Mac's SSH `SendEnv LC_*`. They are
  harmless.
- **Still open:**
  - the operator logs in to phpMyAdmin once through the tunnel (D3);
  - then Phase D;
  - Phase E no earlier than 2026-11-01.

**2026-10-25 — Phase D prepared locally** (k-wating-list, not committed).
- **The changes:**
  - `composer.json` → `"php": "^8.4"`;
  - `composer update --lock` on 8.4.27 changed only the lock's platform entry and hash; no package changed.
- **Checks:**
  - `composer validate` passes;
  - `check-platform-reqs --lock --no-dev`: nothing missing;
  - tests on 8.4: the same 16 passed / 19 failed (the unrelated starter-kit set) as on 8.2.
- **Deploy:** `git pull --ff-only`, then `composer install --no-dev --no-interaction --optimize-autoloader`.
  The host's `composer` runs on 8.4 since Phase C.

**2026-10-25 — Phase D deployed** (k-wating-list `19b5778` → `fddec6b`).
- The pull also brought the earlier `.DS_Store` cleanup (`d819263`).
- `composer install --no-dev` ran on PHP 8.4.27. It had nothing to install and regenerated the autoloader.
- `composer audit`: none.
- **Checks:** `/en` and `/ar/waiting-list` and `/login` 200, `/log-viewer` 403, `POST /register` 405; from
  outside, 200.
- **D3 checked:** the operator logged in to phpMyAdmin on 8.4 through the tunnel, and it works.
  - It shows "The phpMyAdmin configuration storage is not completely configured". That is phpMyAdmin's
    optional `phpmyadmin` database (bookmarks, query history, designer, relations), not PHP 8.4. It can be
    ignored.
- **Phases A–D are done.** Only Phase E is left: retire PHP 8.2 on the host, no earlier than 2026-11-01,
  with the CVE cleanup.

**2026-11-01 — the CVE cleanup (no sudo part) done; Phase E prepared.**
- **Removed on the server:**
  - the images `injazedu-local-ai-ai-control:pre-cve-20261025`, `clinic-app:pre-cve-20261025`,
    `evidence/ai-control:20261025` and `injazedu-local-ai-ai-control:pre-php84-20261025`. No container used
    them. The Phase B rollback image is gone with them, so a rollback to PHP 8.2 means rebuilding `745b329`;
  - `~/p0-*`, `~/p1-*`, `~/p1-3-backup/`, `~/p84-host-fpm.sh` and its report, `~/deploy-745b329.log` and
    `~/deploy-be0af04.log`.
  - Kept: `/var/www/injazedu-ai/evidence/` (the P0-1 logs and session file, about 100 KB),
    `/var/www/injazedu-ai/dumps/` (including the 2026-10-24 dump) and the older `~/deploy-*.log` files.
- **Found before Phase E:**
  - nginx sends nothing to PHP 8.2: both PHP vhosts use `php8.4-fpm.sock`. The `php-fpm.sock` alternative
    still points at the 8.2 socket, but nothing uses it.
  - `libapache2-mod-php8.2` and `libapache2-mod-php` are **not installed**, so they are out of the purge.
  - The dry run, run unprivileged, removes exactly 20 packages: 13 `php8.2*`, 6 `php8.5*` and `php-mcrypt`.
    `phpmyadmin` stays, because `php8.4-cli` and `php8.4-xml` provide its `php-cli` and `php-xml`. `libmcrypt4`
    becomes autoremovable and is left alone.
  - No cron, systemd or supervisor entry and nothing in `/var/www/k-wating-list` names `php8.2`.
- **The script** is `~/p84-retire-82.sh`, run as `ssh -t sambo@84.46.248.13 sudo bash ~/p84-retire-82.sh`.
  Its report is `~/p84-retire-82-report.txt`. It does this:
  1. checks the preconditions and the sites;
  2. stops and disables php8.2-fpm and checks the sites again; if they fail, it starts 8.2 again and stops;
  3. checks the dry run against the 20 packages, and stops on any difference;
  4. purges, removes the leftover `/etc/php/8.2` and `/etc/php/8.5`, then checks:
     - `php` is 8.4 and only the 8.4 socket is left;
     - FPM 8.4 loads the same modules as before;
     - phpMyAdmin is still installed;
     - the sites answer;
  5. only if every check passed, removes `/root/php-cve-backup/` and `/root/php84-backup/`.
  - The site checks are kunooz.ai's waiting-list pages and `/login` (200), `/log-viewer` (403) and `POST /register` (405);
    phpMyAdmin (401); ai-control `/up` (200); and amin.kunooz.ai `/admin/login` (200). All of them passed
    unprivileged before the run.
- **The repo follow-up is done locally (not committed):**
  - `scripts/prod/sudo/04-maintenance-upgrade.sh`: `php8.2-fpm` becomes `php8.4-fpm` in four places,
    including the restart-list regex;
  - `docs/runbooks/production-deployment.md`: line 501, and line 517, where `arch.kunooz.ai`, retired in
    P1-2, became phpMyAdmin on `127.0.0.1:8088`.

**2026-11-02 — Phase E done** (the operator ran `~/p84-retire-82.sh`, 16:21–16:23 UTC). **The PHP 8.4 move is complete.**
- php8.2-fpm was stopped and disabled, and every site still answered. The dry run matched the 20 packages, and
  they were purged.
- `update-alternatives` moved `phar`, `phar.phar` and `phpdbg` to 8.4 on its own.
- The only leftover was `/etc/php/8.2/fpm/conf.d/99-security.ini`, and the script removed it. `/etc/php` now holds
  only 8.4.
- **Checks:**
  - `php` and FPM are 8.4.27;
  - `/run/php` holds only `php8.4-fpm.sock`, plus the dangling `php-fpm.sock` symlink. It is on tmpfs, unused,
    and gone at the next boot;
  - FPM 8.4 loads the same 50 modules as before;
  - `phpmyadmin` is still installed;
  - all eight site checks answered as before and after; from outside, kunooz.ai, ai-control and amin.kunooz.ai
    answer 200.
- The only PHP packages left are `php8.4-*` and the 8.4 metapackages. The only systemd PHP units are
  `php8.4-fpm` and `phpsessionclean`.
- **The CVE cleanup is finished too:** `/root/php-cve-backup/` and `/root/php84-backup/` were removed (vhost and
  `.htpasswd` copies, 56 KB), and the script and its report were deleted afterwards.
- **Rollback** (emergencies only: 8.2 gets no security fixes after 2026-12-31): `apt-get install php8.2-fpm` from Sury,
  then point the vhosts' `fastcgi_pass` back and reload nginx. There are no backup copies any more; the
  edit is one line per vhost.

---

## The steps

> **Rules (as for the CVE work):**
> - One site at a time.
> - Every change is tested locally first and has a rollback.
> - You commit and merge; nothing is committed without asking.
> - Sudo steps are a script that you run over `ssh -t`.
> - No full `apt upgrade`, no reboot, no database change.

### Phase A — the Mac (local, about 10 minutes)

1. `brew install php@8.4`, which gets the current 8.4 patch release.
2. In `~/.zshrc`, replace lines 108–109:
   ```
   export PATH="/opt/homebrew/opt/php@8.4/bin:$PATH"
   export PATH="/opt/homebrew/opt/php@8.4/sbin:$PATH"
   ```
   Then open a new terminal. `php -v` should show 8.4.x.
3. **Check:** `make check` passes. The panel tests now run on 8.4.

**Rollback:** put the two `php@8.2` lines back.

### Phase B — ai-control (repo change + deploy; about 30–60 s of panel restart)

**Repo change** (one PR):
- `apps/ai-control/Dockerfile.prod`: the base image becomes `dunglas/frankenphp:1.13.3-php8.4.27-bookworm`,
  and the comment is updated.
- `apps/ai-control/Dockerfile` (development): `FROM php:8.2-cli` becomes `FROM php:8.4.27-cli-trixie`. The
  same extensions are installed: `pdo_pgsql pgsql zip intl`.
- `apps/ai-control/composer.json` (D4): `"php": "^8.4"`, then `composer update --lock` on 8.4. That
  refreshes only the lock's hash and platform entry, with no package changes.
- `scripts/check.sh`: before the PHP feature test, add a guard. It stops with a clear message if `php` is
  older than 8.4 (`PHP_VERSION_ID < 80400`).
- `docs/runbooks/m0-foundation.md`: "PHP ≥ 8.2" becomes "≥ 8.4".

**Local checks:**
- `make check` passes on 8.4.
- Build `Dockerfile.prod`, then check:
  - `frankenphp version` shows PHP 8.4.27;
  - upload progress is off;
  - `composer audit` is clean;
  - `/up` and `/admin/login` answer 200.
- Build and start the development image.

**Deploy:**
- Run `scripts/prod/deploy.sh <sha>` on the server. It has no migration and recreates only `ai-control`.
- **Check in production:**
  - the container shows PHP 8.4.27;
  - `/admin/login` answers 200, inside and outside;
  - a multipart POST still gets 415;
  - the logs are clean;
  - you log in once yourself.
- **Rollback:** `scripts/prod/deploy.sh <previous sha>`. The deploy prints the command.

### Phase C — kunooz.ai and phpMyAdmin onto host PHP 8.4 (sudo script; no downtime)

You run one script, `sudo bash ~/p84-host-fpm.sh`, over `ssh -t`. It:
1. **Backs up** both vhosts to `/root/php84-backup/<ts>/`.
2. **Installs** `php8.4-fpm php8.4-xml php8.4-bcmath`, using `--no-install-recommends`, `NEEDRESTART_MODE=l`
   and `--force-confold`. Per the dry run, it adds exactly these three packages.
3. **Copies** `99-security.ini` to `/etc/php/8.4/fpm/conf.d/`, then checks:
   - `php-fpm8.4 -t`;
   - that FPM 8.4 has upload progress off and `post_max_size` 8M.
4. **Runs a canary first**, without touching the live site: a temporary nginx server on `127.0.0.1:8089`
   serves the k-wating-list code through the **8.4** socket. The script requests these pages there:
   - `/en/waiting-list`: expect 200;
   - `/login`: expect 200;
   - `/log-viewer`: expect 403;
   - `POST /register`: expect 405.
   If any answer is wrong, it removes the canary and stops, and nothing live has changed.
5. **Switches** the `kunooz.ai` and `phpmyadmin-local` vhosts from `php8.2-fpm.sock` to `php8.4-fpm.sock`,
   runs `nginx -t` and reloads nginx, which drops no connections. It repeats the checks on the live
   kunooz.ai. If they fail, it switches back and reloads.
6. **Removes the canary** server.
7. **Points the host's `php` at 8.4** (`update-alternatives --set php /usr/bin/php8.4`), so `php artisan` and
   `composer` work without a version suffix.
8. **Leaves `php8.2-fpm` running but unused**, so a rollback is instant.

**Your check (D3):** open phpMyAdmin through the tunnel and log in:
`ssh -N -L 8088:127.0.0.1:8088 sambo@84.46.248.13`, then http://localhost:8088.

**Rollback:** run `sed` on the two vhosts back to `php8.2-fpm.sock`, then `nginx -t && systemctl reload
nginx`. It takes seconds.

### Phase D — k-wating-list repo (small PR, after Phase C)

- `composer.json` (D4): `"php": "^8.4"`, then `composer update --lock` on 8.4.
- **Deploy:** `git pull --ff-only`, then `composer install --no-dev --optimize-autoloader`. The host's
  `composer` runs on 8.4 after Phase C.
- **Checks:** the waiting-list pages and `/login` answer 200, `/log-viewer` 403, and `POST /register` 405.

### Phase E — retire PHP 8.2 on the host (sudo script; at least a week after Phase C, before 2026-12-31)

1. Run `systemctl disable --now php8.2-fpm`. Then check that kunooz.ai and phpMyAdmin still answer.
2. Show an `apt-get -s purge` dry run, and only then purge:
   - `php8.2*`;
   - the unused `php8.5*` CLI packages, which also removes the `php-mcrypt` metapackage.
   - (`libapache2-mod-php8.2` and `libapache2-mod-php` were listed here, but on 2026-11-01 neither was
     installed.)
   - It removes nothing else: no autoremove without review. phpMyAdmin must stay installed.
3. **Checks:**
   - `php -v` shows 8.4;
   - kunooz.ai and phpMyAdmin answer;
   - `ls /run/php/` shows only the 8.4 socket.
4. **Repo follow-up** (injazedu): `php8.2-fpm` becomes `php8.4-fpm` in:
   - `scripts/prod/sudo/04-maintenance-upgrade.sh` (four places, with the restart-list regex);
   - `docs/runbooks/production-deployment.md`, line 501.

**Rollback:** reinstall `php8.2-fpm` (Sury) and switch the sockets back. Once 8.2 is past its end of life,
this is for emergencies only.

---

## Order and downtime

| Phase | When | Downtime |
|---|---|---|
| A — the Mac | first | none |
| B — ai-control | after A | about 30–60 s, panel only |
| C — kunooz.ai and phpMyAdmin | any time (independent of B) | none (nginx reload) |
| D — k-wating-list constraint | after C | none |
| E — remove 8.2 | at least a week after C, by 2026-12-31 | none |

B and C don't depend on each other. C first is also fine: it has no downtime and an instant rollback.

## Risks

- **Patch-level drift:** tests ran on 8.4.2; production will run 8.4.27, the same minor version.
  - Phase B's image build and checks run on 8.4.27 itself.
  - Phase C's canary exercises 8.4.27 on the server before kunooz.ai switches.
- **Locks resolved on 8.2:** `check-platform-reqs` on 8.4 is clean. D4's `composer update --lock` changes
  only the platform entry.
- **phpMyAdmin 5.2.1 on 8.4:** possible deprecation notices in the FPM log. If it doesn't work, there are
  two fallbacks:
  - keep its vhost on 8.2 until Phase E;
  - or remove it (D3).
- **Other projects on the Mac:** some may need 8.2. D2 keeps switching back a two-line change.

## Out of scope

- The clinic, which is already on 8.4.27.
- The ai-api, which is Python.
- unattended-upgrades for the Sury PPA (the CVE audit's P2-1, separate).
- The 2026-11-01 cleanup of the CVE work.

## Checklist

- [x] Decisions D1–D4 confirmed
- [x] A — `php@8.4` on the Mac; `make check` green on 8.4
- [x] B — PR: both Dockerfiles, `composer.json`/lock, the `check.sh` guard, the runbook line → local image checks → deploy → login checked
- [x] C — `~/p84-host-fpm.sh`: install, canary, switch, alternatives → phpMyAdmin checked through the tunnel
- [x] D — PR: k-wating-list `composer.json`/lock → pull + install → checks
- [x] E — (≥ 1 week after C) disable and purge 8.2 and the stray 8.5 → PR: maintenance script + runbook lines
