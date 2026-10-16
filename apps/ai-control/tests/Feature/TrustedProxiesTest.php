<?php

namespace Tests\Feature;

use Illuminate\Http\Request;
use Illuminate\Support\Facades\Route;
use Tests\TestCase;

/**
 * Production serves the panel behind the host's nginx, which terminates TLS
 * (docs/runbooks/production-deployment.md). Only the proxy named by TRUSTED_PROXIES may tell
 * Laravel the client's address and scheme; unset — development and tests — trusts no one.
 */
class TrustedProxiesTest extends TestCase
{
    private const PROXY = '172.31.240.1';

    private const CLIENT = '203.0.113.9';

    protected function setUp(): void
    {
        parent::setUp();

        Route::get('/__proxy-probe', fn (Request $request) => [
            'ip' => $request->ip(),
            'secure' => $request->isSecure(),
        ]);
    }

    public function test_trusted_proxies_come_from_the_environment(): void
    {
        $this->assertNull(config('trustedproxy.proxies'));

        $_SERVER['TRUSTED_PROXIES'] = $_ENV['TRUSTED_PROXIES'] = self::PROXY;

        try {
            $this->refreshApplication();

            $this->assertSame(self::PROXY, config('trustedproxy.proxies'));
        } finally {
            unset($_SERVER['TRUSTED_PROXIES'], $_ENV['TRUSTED_PROXIES']);
        }
    }

    public function test_no_proxy_is_trusted_by_default(): void
    {
        $this->fromPeer(self::PROXY)
            ->assertExactJson(['ip' => self::PROXY, 'secure' => false]);
    }

    public function test_the_configured_proxy_forwards_the_client_address_and_scheme(): void
    {
        config(['trustedproxy.proxies' => self::PROXY]);

        $this->fromPeer(self::PROXY)
            ->assertExactJson(['ip' => self::CLIENT, 'secure' => true]);
    }

    public function test_any_other_peer_cannot_forge_forwarded_headers(): void
    {
        config(['trustedproxy.proxies' => self::PROXY]);

        $this->fromPeer('198.51.100.7')
            ->assertExactJson(['ip' => '198.51.100.7', 'secure' => false]);
    }

    private function fromPeer(string $peer): \Illuminate\Testing\TestResponse
    {
        return $this->withServerVariables(['REMOTE_ADDR' => $peer])
            ->withHeaders([
                'X-Forwarded-For' => self::CLIENT,
                'X-Forwarded-Proto' => 'https',
                'X-Forwarded-Port' => '443',
            ])
            ->getJson('/__proxy-probe')
            ->assertOk();
    }
}
