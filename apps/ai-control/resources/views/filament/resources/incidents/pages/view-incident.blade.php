<x-filament-panels::page>
    {{ $this->content }}

    @include('filament.resources.incidents.standing-notices', ['record' => $this->getRecord()])
</x-filament-panels::page>
