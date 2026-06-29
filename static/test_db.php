<?php
require __DIR__.'/../vendor/autoload.php';
$app = require_once __DIR__.'/../bootstrap/app.php';
$kernel = $app->make(Illuminate\Contracts\Http\Kernel::class);
$response = $kernel->handle($request = Illuminate\Http\Request::capture());

try {
    $count = \App\Models\SecurityThreatLog::count();
    echo "Database check SUCCESS! Found " . $count . " threat logs.";
} catch (\Exception $e) {
    echo "Database check FAILED: " . $e->getMessage();
}
