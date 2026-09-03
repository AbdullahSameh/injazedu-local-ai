<?php

namespace App\Console\Commands;

use App\Models\User;
use Illuminate\Console\Command;
use Illuminate\Support\Facades\Hash;
use Illuminate\Support\Facades\Validator;

class SeedAdmin extends Command
{
    /**
     * The name and signature of the console command.
     *
     * @var string
     */
    protected $signature = 'app:seed-admin';

    /**
     * The console command description.
     *
     * @var string
     */
    protected $description = 'Create or update the panel operator account from ADMIN_EMAIL/ADMIN_PASSWORD (FR-022)';

    public function handle(): int
    {
        $email = env('ADMIN_EMAIL');
        $password = env('ADMIN_PASSWORD');

        if (! $email || ! $password) {
            $this->error('ADMIN_EMAIL and ADMIN_PASSWORD must both be set in the environment. No default account ships.');

            return self::FAILURE;
        }

        $validator = Validator::make(
            ['email' => $email],
            ['email' => ['required', 'email']],
        );

        if ($validator->fails()) {
            $this->error("ADMIN_EMAIL \"{$email}\" is not a valid email address.");

            return self::FAILURE;
        }

        $existed = User::where('email', $email)->exists();

        User::updateOrCreate(
            ['email' => $email],
            [
                'name' => 'Admin',
                'password' => Hash::make($password),
                'is_panel_operator' => true,
            ],
        );

        $this->info($existed
            ? "Updated the password for existing operator account \"{$email}\"."
            : "Created operator account \"{$email}\".");

        return self::SUCCESS;
    }
}
