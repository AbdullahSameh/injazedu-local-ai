<?php

namespace App\Http\Middleware;

use App\Support\PanelLocale;
use Closure;
use Illuminate\Http\Request;
use Symfony\Component\HttpFoundation\Response;

/**
 * Applies the language chosen from the user menu (the `panel_locale` cookie). An absent or
 * unknown value leaves `config('app.locale')` — English — in force. Registered as persistent
 * panel middleware so Livewire's update requests render in the same language as the page.
 */
class SetPanelLocale
{
    public function handle(Request $request, Closure $next): Response
    {
        $locale = $request->cookie(PanelLocale::COOKIE);

        if (PanelLocale::isSupported($locale)) {
            app()->setLocale($locale);
        }

        return $next($request);
    }
}
