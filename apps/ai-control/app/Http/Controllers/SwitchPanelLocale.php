<?php

namespace App\Http\Controllers;

use App\Support\PanelLocale;
use Filament\Facades\Filament;
use Illuminate\Http\RedirectResponse;
use Illuminate\Http\Request;

/**
 * The user menu's language switch: remembers the choice in a long-lived cookie (no schema
 * change — Alembic owns `users`) and returns to the page it was chosen on. The route only
 * accepts `PanelLocale::SUPPORTED` keys. "The page it was chosen on" is the session's last
 * full-page URL, never the `Referer` header, so the switch can only ever land inside the panel.
 */
class SwitchPanelLocale extends Controller
{
    public function __invoke(Request $request, string $locale): RedirectResponse
    {
        cookie()->queue(cookie()->forever(PanelLocale::COOKIE, $locale));

        return redirect()->to($request->session()->previousUrl() ?? Filament::getUrl());
    }
}
