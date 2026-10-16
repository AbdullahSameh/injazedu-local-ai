<?php

/*
| Production serves the panel behind the host's nginx, which terminates TLS
| (docs/runbooks/production-deployment.md). Laravel's TrustProxies middleware reads this value:
| the address(es) whose X-Forwarded-* headers it believes — one IP, a comma-separated list, or
| "*". Unset — development and tests — trusts no proxy, exactly as before.
*/

return [

    'proxies' => env('TRUSTED_PROXIES'),

];
