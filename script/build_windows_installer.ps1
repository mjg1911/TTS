param([string]$Python = 'python')

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$compiler = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $compiler)) {
    throw "Inno Setup 6 is required to build the installer"
}
if (-not (Test-Path "dist/PiperTray/PiperTray.exe" -PathType Leaf)) {
    throw "Build dist/PiperTray before the installer"
}
$setupText = Get-Content "setup.py" -Raw
$hasSharedManifest = Test-Path "dist/PiperTray/_internal/chatterbox_payload/manifest.json" -PathType Leaf
if (($env:PIPER_REQUIRE_TURBO_PAYLOAD -eq "1" -or $env:PIPER_REQUIRE_NANO_PAYLOAD -eq "1") -and
    -not $hasSharedManifest) {
    throw "Installer requires the shared offline Chatterbox payload"
}
if ($hasSharedManifest) {
    $env:PYTHONPATH = Join-Path $Root 'src'
    $checkPayload = @'
import json
import os
from pathlib import Path
from piper.chatterbox_assets import inspect_chatterbox_installation

root = Path('dist/PiperTray/_internal/chatterbox_payload')
models = json.loads((root / 'manifest.json').read_bytes()).get('models', {})
for engine in ('nano', 'turbo'):
    if os.environ.get(f'PIPER_REQUIRE_{engine.upper()}_PAYLOAD') == '1' and engine not in models:
        raise ValueError(f'Installer requires the Chatterbox {engine} model')
# One inspection verifies the runtime and every declared model's pinned hashes.
inspect_chatterbox_installation(root, next(iter(models), 'nano'))
'@
    & $Python -c $checkPayload
    if ($LASTEXITCODE -ne 0) { throw "Installer shared Chatterbox payload verification failed" }
}
$versionMatch = [regex]::Match($setupText, 'version="([^"]+)"')
$version = $versionMatch.Groups[1].Value
if ([string]::IsNullOrWhiteSpace($version)) { throw "Could not read package version" }
& $compiler "/DMyAppVersion=$version" "script/piper_tray_installer.iss"
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup failed with exit code $LASTEXITCODE"
}
if (-not (Test-Path "dist/PiperTraySetup.exe")) {
    throw "dist/PiperTraySetup.exe was not produced"
}
