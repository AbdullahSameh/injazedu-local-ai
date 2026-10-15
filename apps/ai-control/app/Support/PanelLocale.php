<?php

namespace App\Support;

/**
 * The panel's languages — the one definition (`tg-panel-bilingual-plan.md` §1). English is the
 * default and is never translated: its strings are the keys of `lang/ar.json`. Each language is
 * named in its own script so a reader of either can find the switch.
 */
class PanelLocale
{
    public const SUPPORTED = [
        'en' => 'English',
        'ar' => 'العربية',
    ];

    public const DEFAULT = 'en';

    public const COOKIE = 'panel_locale';

    public static function isSupported(mixed $locale): bool
    {
        return is_string($locale) && array_key_exists($locale, self::SUPPORTED);
    }

    /**
     * Whether durations may use short units ("20m"). Carbon has none for Arabic, and with
     * Laravel's English fallback it would print the English ones on an Arabic screen.
     */
    public static function hasShortDurationUnits(): bool
    {
        return app()->getLocale() !== 'ar';
    }

    /** The language the user menu offers: the one not in use. */
    public static function other(string $locale): string
    {
        return $locale === 'ar' ? 'en' : 'ar';
    }
}
