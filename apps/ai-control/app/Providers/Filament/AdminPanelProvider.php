<?php

namespace App\Providers\Filament;

use App\Http\Controllers\SwitchPanelLocale;
use App\Http\Middleware\SetPanelLocale;
use App\Support\PanelLocale;
use Filament\Actions\Action;
use Filament\Http\Middleware\Authenticate;
use Filament\Http\Middleware\AuthenticateSession;
use Filament\Http\Middleware\DisableBladeIconComponents;
use Filament\Http\Middleware\DispatchServingFilamentEvent;
use Filament\Pages\Dashboard;
use Filament\Panel;
use Filament\PanelProvider;
use Filament\Support\Colors\Color;
use Filament\Support\Icons\Heroicon;
use Filament\Widgets\AccountWidget;
use Filament\Widgets\FilamentInfoWidget;
use Illuminate\Cookie\Middleware\AddQueuedCookiesToResponse;
use Illuminate\Cookie\Middleware\EncryptCookies;
use Illuminate\Foundation\Http\Middleware\VerifyCsrfToken;
use Illuminate\Routing\Middleware\SubstituteBindings;
use Illuminate\Session\Middleware\StartSession;
use Illuminate\Support\Facades\Route;
use Illuminate\View\Middleware\ShareErrorsFromSession;

class AdminPanelProvider extends PanelProvider
{
    public function panel(Panel $panel): Panel
    {
        return $panel
            ->default()
            ->id('admin')
            ->path('admin')
            ->login()
            ->colors([
                'primary' => Color::Amber,
            ])
            ->discoverResources(in: app_path('Filament/Resources'), for: 'App\Filament\Resources')
            ->discoverPages(in: app_path('Filament/Pages'), for: 'App\Filament\Pages')
            ->pages([
                Dashboard::class,
            ])
            ->discoverWidgets(in: app_path('Filament/Widgets'), for: 'App\Filament\Widgets')
            ->widgets([
                AccountWidget::class,
                FilamentInfoWidget::class,
            ])
            ->middleware([
                EncryptCookies::class,
                AddQueuedCookiesToResponse::class,
                StartSession::class,
                AuthenticateSession::class,
                ShareErrorsFromSession::class,
                VerifyCsrfToken::class,
                SubstituteBindings::class,
                DisableBladeIconComponents::class,
                DispatchServingFilamentEvent::class,
            ])
            // Persistent, so Livewire's update requests (sorting, filters, actions, polling)
            // render in the page's language too (`tg-panel-bilingual-plan.md` §1).
            ->middleware([
                SetPanelLocale::class,
            ], isPersistent: true)
            ->authMiddleware([
                Authenticate::class,
            ])
            ->authenticatedRoutes(function (): void {
                Route::post('/locale/{locale}', SwitchPanelLocale::class)
                    ->whereIn('locale', array_keys(PanelLocale::SUPPORTED))
                    ->name('locale');
            })
            // Offers the language not in use, named in its own script; posted like Filament's
            // own logout item.
            ->userMenuItems([
                Action::make('locale')
                    ->label(fn(): string => PanelLocale::SUPPORTED[PanelLocale::other(app()->getLocale())])
                    ->icon(Heroicon::OutlinedLanguage)
                    ->url(fn(): string => route('filament.admin.locale', [
                        'locale' => PanelLocale::other(app()->getLocale()),
                    ]))
                    ->postToUrl(),
            ]);
    }
}
