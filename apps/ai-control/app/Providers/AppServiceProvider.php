<?php

namespace App\Providers;

use Illuminate\Support\Facades\DB;
use Illuminate\Support\ServiceProvider;

class AppServiceProvider extends ServiceProvider
{
    /**
     * Register any application services.
     */
    public function register(): void
    {
        //
    }

    /**
     * Bootstrap any application services.
     */
    public function boot(): void
    {
        // Alembic owns this schema (research D-07) — Laravel must never migrate:fresh/reset/wipe it.
        DB::prohibitDestructiveCommands(! $this->app->environment('testing'));
    }
}
