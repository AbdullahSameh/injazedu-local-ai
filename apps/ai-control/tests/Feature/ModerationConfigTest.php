<?php

namespace Tests\Feature;

use Illuminate\Foundation\Testing\DatabaseTransactions;
use Tests\TestCase;

/**
 * T005: `config/moderation.php` reads both `MODERATION_PERCENTILE_MIN_SAMPLES` and
 * `MODERATION_INCIDENT_MAX_AGE_S` blank-safe (research Finding 2, D-TG-122). ⚠ The running panel
 * reads `0` today because `.env` lacks the key, Compose passes `''`, and a bare
 * `(int) env(..., 10)` coerces the empty string instead of falling back — a test that only sets
 * real values passes against that broken code. Each variable is put into the process environment
 * and the config file is `require`d directly — the same evaluation `config()` performs at boot —
 * so this test reflects exactly what Compose's `${KEY:-default}` produces: an empty string, not an
 * absent key, without depending on application boot order.
 */
class ModerationConfigTest extends TestCase
{
    use DatabaseTransactions;

    private const VARS = ['MODERATION_PERCENTILE_MIN_SAMPLES', 'MODERATION_INCIDENT_MAX_AGE_S'];

    private function setEnv(string $key, ?string $value): void
    {
        if ($value === null) {
            putenv($key);
            unset($_ENV[$key], $_SERVER[$key]);

            return;
        }

        putenv("{$key}={$value}");
        $_ENV[$key] = $value;
        $_SERVER[$key] = $value;
    }

    private function loadConfig(): array
    {
        return require config_path('moderation.php');
    }

    public function test_percentile_min_samples_reads_default_when_env_is_empty_string(): void
    {
        $this->setEnv('MODERATION_PERCENTILE_MIN_SAMPLES', '');

        $this->assertSame(10, $this->loadConfig()['percentile_min_samples']);
    }

    public function test_incident_max_age_reads_default_when_env_is_empty_string(): void
    {
        $this->setEnv('MODERATION_INCIDENT_MAX_AGE_S', '');

        $this->assertSame(86400, $this->loadConfig()['incident_max_age_s']);
    }

    public function test_percentile_min_samples_reads_real_value(): void
    {
        $this->setEnv('MODERATION_PERCENTILE_MIN_SAMPLES', '25');

        $this->assertSame(25, $this->loadConfig()['percentile_min_samples']);
    }

    public function test_incident_max_age_reads_real_value(): void
    {
        $this->setEnv('MODERATION_INCIDENT_MAX_AGE_S', '3600');

        $this->assertSame(3600, $this->loadConfig()['incident_max_age_s']);
    }

    protected function tearDown(): void
    {
        foreach (self::VARS as $var) {
            $this->setEnv($var, null);
        }

        parent::tearDown();
    }
}
