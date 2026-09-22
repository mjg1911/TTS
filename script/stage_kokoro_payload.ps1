$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$required = @{
    "config.json" = "PIPER_KOKORO_CONFIG"
    "kokoro-v1_0.pth" = "PIPER_KOKORO_MODEL"
    "voices/af_heart.pt" = "PIPER_KOKORO_AF_HEART"
}
$lock = Get-Content "script/kokoro_assets.lock.json" -Raw | ConvertFrom-Json
if ($lock.repository -ne "hexgrad/Kokoro-82M") { throw "Unexpected Kokoro asset repository" }
if ($lock.revision -ne "c3327e9bac3dbe55779397bfa82de0f8806fb3bc") {
    throw "Unexpected Kokoro asset revision"
}
foreach ($relative in $required.Keys) {
    $name = $required[$relative]
    $value = [Environment]::GetEnvironmentVariable($name)
    if ([string]::IsNullOrWhiteSpace($value) -or -not (Test-Path $value)) {
        throw "Required Kokoro build input $name is missing"
    }
    $actual = (Get-FileHash $value -Algorithm SHA256).Hash.ToLowerInvariant()
    $expected = [string]$lock.files.PSObject.Properties[$relative].Value
    if ($actual -ne $expected) {
        throw "Kokoro source hash mismatch for $relative"
    }
}
if (-not (Test-Path "dist/KokoroWorker/KokoroWorker.exe")) {
    throw "Build KokoroWorker before staging the payload"
}

$payloadRoot = Join-Path $Root "build\kokoro-payload"
if (Test-Path $payloadRoot) {
    Remove-Item $payloadRoot -Recurse -Force
}
New-Item -ItemType Directory -Force `
    (Join-Path $payloadRoot "worker"), `
    (Join-Path $payloadRoot "model"), `
    (Join-Path $payloadRoot "voices") | Out-Null
Copy-Item "dist/KokoroWorker/*" (Join-Path $payloadRoot "worker") -Recurse -Force
Copy-Item $env:PIPER_KOKORO_CONFIG (Join-Path $payloadRoot "model\config.json") -Force
Copy-Item $env:PIPER_KOKORO_MODEL (Join-Path $payloadRoot "model\kokoro-v1_0.pth") -Force
Copy-Item $env:PIPER_KOKORO_AF_HEART (Join-Path $payloadRoot "voices\af_heart.pt") -Force

$requiredWorkerPaths = @(
    (Join-Path $payloadRoot "worker\_internal\en_core_web_sm"),
    (Join-Path $payloadRoot "worker\_internal\language_tags\data\json\index.json"),
    (Join-Path $payloadRoot "worker\_internal\curated_transformers\models\output.py"),
    (Join-Path $payloadRoot "worker\_internal\misaki\data"),
    (Join-Path $payloadRoot "worker\_internal\espeakng_loader")
)
foreach ($path in $requiredWorkerPaths) {
    if (-not (Test-Path $path)) {
        throw "Required frozen Kokoro resource is missing: $path"
    }
}
python script/write_kokoro_manifest.py $payloadRoot
if ($LASTEXITCODE -ne 0) { throw "Kokoro manifest generation failed" }
