#!/bin/sh
# The production panel's entrypoint (Dockerfile.prod). Laravel's caches are built here, at start,
# from this container's environment — never at image build, so the image carries no configuration.
# Then it hands over to the command (FrankenPHP, or a one-off `php artisan …`).
set -e

php artisan optimize --no-interaction
php artisan filament:optimize --no-interaction

exec "$@"
