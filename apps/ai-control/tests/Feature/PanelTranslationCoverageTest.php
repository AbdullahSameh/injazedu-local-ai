<?php

namespace Tests\Feature;

use App\Filament\Pages\LiveAttentionQueue;
use App\Filament\Resources\Incidents\Actions\OpenIncidentAction;
use App\Filament\Resources\Incidents\Support\IncidentDisplay;
use App\Filament\Resources\Incidents\Tables\IncidentsTable;
use App\Filament\Support\ModelView;
use RecursiveDirectoryIterator;
use RecursiveIteratorIterator;
use ReflectionClass;
use Tests\TestCase;

/**
 * The bilingual panel's completeness gate (`tg-panel-bilingual-plan.md` §5): every English
 * string the panel passes through `__()` has a non-blank Arabic entry in `lang/ar.json` carrying
 * the same `:placeholders`, and no Arabic entry outlives the English it translated. English is the
 * key, so there is no `lang/en.json` — the English screens are byte-identical by construction.
 */
class PanelTranslationCoverageTest extends TestCase
{
    /**
     * Label maps translated on read (`__(self::MAP[$key])`) — a constant cannot call `__()`, so
     * the regex scan below cannot see these.
     */
    private const LABEL_CONSTANTS = [
        [IncidentDisplay::class, 'KIND_LABELS'],
        [IncidentDisplay::class, 'STRENGTH_LABELS'],
        [ModelView::class, 'EXCLUSION_LABELS'],
        [ModelView::class, 'FAILURE_LABELS'],
        [IncidentsTable::class, 'STATUSES'],
        [IncidentsTable::class, 'CATEGORIES'],
        [IncidentsTable::class, 'SEVERITIES'],
        [OpenIncidentAction::class, 'CATEGORIES'],
        [OpenIncidentAction::class, 'SEVERITIES'],
        [LiveAttentionQueue::class, 'DISMISS_CONFIRMATION'],
    ];

    /**
     * Stored codes the panel prints through `__($code)`: English still shows the code itself,
     * Arabic shows a word.
     */
    private const DISPLAYED_CODES = [
        // the classification taxonomy (D-TG-08; `app/domain/moderation/classification.py`)
        'QUESTION_COURSE', 'QUESTION_ACCESS', 'COMPLAINT', 'CHITCHAT', 'SPAM_OR_AD', 'ABUSE', 'OTHER',
        // the classification severities
        'none', 'low', 'medium', 'high',
        // attention_items.status
        'open', 'answered', 'dismissed', 'expired',
        // moderation_incident_state.status
        'acknowledged', 'resolved', 'closed_false_positive',
        // telegram_chats.chat_type and ck_telegram_chats_bot_status
        'group', 'supergroup', 'channel', 'private',
        'member', 'administrator', 'left', 'kicked', 'restricted', 'unknown',
        // ck_assignment_role
        'primary', 'backup',
    ];

    /** @return array<string, string> */
    private function arabic(): array
    {
        $path = lang_path('ar.json');
        $this->assertFileExists($path);

        return json_decode((string) file_get_contents($path), true, flags: JSON_THROW_ON_ERROR);
    }

    /** @return array<int, string> every PHP and Blade file the panel renders from */
    private function sourceFiles(): array
    {
        $files = [];

        foreach ([app_path(), resource_path('views')] as $root) {
            $iterator = new RecursiveIteratorIterator(new RecursiveDirectoryIterator($root));
            foreach ($iterator as $file) {
                if ($file->isFile() && str_ends_with($file->getFilename(), '.php')) {
                    $files[] = $file->getPathname();
                }
            }
        }

        sort($files);

        return $files;
    }

    private function source(): string
    {
        return implode("\n", array_map(fn (string $f): string => (string) file_get_contents($f), $this->sourceFiles()));
    }

    /** @return array<int, string> the literal keys of every `__('…')` / `__("…")` call */
    private function literalKeys(): array
    {
        $source = $this->source();
        $keys = [];

        preg_match_all("/__\(\s*'((?:[^'\\\\]|\\\\.)*)'/s", $source, $single);
        foreach ($single[1] as $raw) {
            $keys[] = str_replace(["\\'", '\\\\'], ["'", '\\'], $raw);
        }

        preg_match_all('/__\(\s*"((?:[^"\\\\]|\\\\.)*)"/s', $source, $double);
        foreach ($double[1] as $raw) {
            $keys[] = str_replace(['\\"', '\\\\'], ['"', '\\'], $raw);
        }

        // A package's own namespaced keys (`filament-panels::…`) are translated by the package.
        return array_values(array_unique(array_filter($keys, fn (string $k): bool => ! str_contains($k, '::'))));
    }

    /** @return array<int, string> */
    private function labelConstantValues(): array
    {
        $values = [];

        foreach (self::LABEL_CONSTANTS as [$class, $constant]) {
            $value = (new ReflectionClass($class))->getConstant($constant);
            $this->assertNotFalse($value, "{$class}::{$constant} no longer exists");
            array_push($values, ...(is_array($value) ? array_values($value) : [$value]));
        }

        return $values;
    }

    /** @return array<int, string> */
    private function placeholders(string $line): array
    {
        preg_match_all('/:([A-Za-z_]+)/', $line, $matches);
        $names = array_unique($matches[1]);
        sort($names);

        return $names;
    }

    public function test_english_has_no_translation_file(): void
    {
        $this->assertFileDoesNotExist(lang_path('en.json'));
    }

    public function test_the_panel_translates_its_strings(): void
    {
        $this->assertGreaterThan(150, count($this->literalKeys()));
    }

    public function test_no_translated_literal_is_concatenated(): void
    {
        // `__('a '.'b')` would look up the fragment, not the sentence.
        $this->assertSame(0, preg_match_all("/__\\(\\s*'(?:[^'\\\\]|\\\\.)*'\\s*\\./s", $this->source()));
    }

    public function test_every_translated_literal_has_an_arabic_entry(): void
    {
        $missing = array_diff($this->literalKeys(), array_keys($this->arabic()));

        $this->assertSame([], array_values($missing), 'Missing from lang/ar.json');
    }

    public function test_every_label_map_value_and_displayed_code_has_an_arabic_entry(): void
    {
        $expected = [...$this->labelConstantValues(), ...self::DISPLAYED_CODES];
        $missing = array_diff($expected, array_keys($this->arabic()));

        $this->assertSame([], array_values($missing), 'Missing from lang/ar.json');
    }

    public function test_every_arabic_entry_is_written_and_keeps_its_placeholders(): void
    {
        foreach ($this->arabic() as $english => $arabic) {
            $this->assertIsString($arabic, $english);
            $this->assertNotSame('', trim($arabic), "Blank Arabic for: {$english}");
            $this->assertSame($this->placeholders($english), $this->placeholders($arabic), "Placeholders differ for: {$english}");
        }
    }

    public function test_no_arabic_entry_outlives_its_english(): void
    {
        $source = $this->source();
        $held = [...$this->labelConstantValues(), ...self::DISPLAYED_CODES];
        $stale = [];

        foreach (array_keys($this->arabic()) as $english) {
            if (in_array($english, $held, true)) {
                continue;
            }

            $single = "'".str_replace(['\\', "'"], ['\\\\', "\\'"], $english)."'";
            $double = '"'.str_replace(['\\', '"'], ['\\\\', '\\"'], $english).'"';

            if (! str_contains($source, $single) && ! str_contains($source, $double)) {
                $stale[] = $english;
            }
        }

        $this->assertSame([], $stale, 'In lang/ar.json but no longer in the panel source');
    }
}
