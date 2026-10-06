$ErrorActionPreference = "Stop"

if ($env:OS -ne "Windows_NT") {
    throw "PiperTray.exe must be built on Windows."
}

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$legacyPayloadVariables = @(
    "PIPER_NANO_PAYLOAD_DIR",
    "PIPER_TURBO_PAYLOAD_DIR"
)
foreach ($name in $legacyPayloadVariables) {
    if (-not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name))) {
        throw "$name is no longer supported. Stage one shared payload and set PIPER_CHATTERBOX_PAYLOAD_DIR."
    }
}

$legacyWorkerPythons = @(
    $env:PIPER_NANO_WORKER_PYTHON,
    $env:PIPER_TURBO_WORKER_PYTHON
) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique
if ($legacyWorkerPythons.Count -gt 1) {
    throw "Nano and Turbo worker Python settings disagree. Set one PIPER_CHATTERBOX_WORKER_PYTHON."
}
if ($legacyWorkerPythons.Count -eq 1) {
    if ($env:PIPER_CHATTERBOX_WORKER_PYTHON -and
        $env:PIPER_CHATTERBOX_WORKER_PYTHON -ne $legacyWorkerPythons[0]) {
        throw "Legacy worker Python setting conflicts with PIPER_CHATTERBOX_WORKER_PYTHON."
    }
    if (-not $env:PIPER_CHATTERBOX_WORKER_PYTHON) {
        $env:PIPER_CHATTERBOX_WORKER_PYTHON = $legacyWorkerPythons[0]
    }
}

$requireNano = $env:PIPER_REQUIRE_NANO_PAYLOAD -eq "1"
$requireTurbo = $env:PIPER_REQUIRE_TURBO_PAYLOAD -eq "1"
$hasNanoModel = -not [string]::IsNullOrWhiteSpace($env:PIPER_NANO_MODEL_DIR)
$hasTurboModel = -not [string]::IsNullOrWhiteSpace($env:PIPER_TURBO_MODEL_DIR)
$hasSharedPayload = -not [string]::IsNullOrWhiteSpace($env:PIPER_CHATTERBOX_PAYLOAD_DIR)
if ($hasSharedPayload -and ($hasNanoModel -or $hasTurboModel)) {
    throw "Choose an existing PIPER_CHATTERBOX_PAYLOAD_DIR or model directories to stage."
}
if (($requireNano -or $requireTurbo) -and -not ($hasSharedPayload -or $hasNanoModel -or $hasTurboModel)) {
    throw "Release build requires PIPER_CHATTERBOX_PAYLOAD_DIR or a local Nano/Turbo model directory."
}
if ($hasSharedPayload -and -not (Test-Path -LiteralPath $env:PIPER_CHATTERBOX_PAYLOAD_DIR -PathType Container)) {
    throw "Shared Chatterbox payload directory does not exist: $env:PIPER_CHATTERBOX_PAYLOAD_DIR"
}

$IconDir = Join-Path $Root "build\piper-tray"
$DistDir = Join-Path $Root "dist\PiperTray"
$Exe = Join-Path $DistDir "PiperTray.exe"
if (Test-Path -LiteralPath $IconDir) { Remove-Item -Recurse -Force -LiteralPath $IconDir }
if (Test-Path -LiteralPath $DistDir) { Remove-Item -Recurse -Force -LiteralPath $DistDir }

python -m pip install -e ".[windows-tray,windows-tray-build]"
python setup.py build_ext --inplace

$Bridge = Get-ChildItem (Join-Path $Root "src\piper") -Filter "espeakbridge*.pyd" -File
if ($null -eq $Bridge) {
    throw "espeakbridge.pyd was not built; the packaged executable would not be able to synthesize speech."
}

python script/make_piper_tray_icon.py

if ($hasNanoModel -or $hasTurboModel) {
    $PayloadDir = Join-Path $Root "build\chatterbox-payload"
    if (Test-Path -LiteralPath $PayloadDir) { Remove-Item -Recurse -Force -LiteralPath $PayloadDir }
    & "$Root/script/build_chatterbox_worker.ps1"
    $stageParameters = @{
        WorkerDir = "dist/ChatterboxWorker"
        OutputDir = $PayloadDir
    }
    if ($hasNanoModel) { $stageParameters.NanoModelDir = $env:PIPER_NANO_MODEL_DIR }
    if ($hasTurboModel) { $stageParameters.TurboModelDir = $env:PIPER_TURBO_MODEL_DIR }
    & "$Root/script/stage_chatterbox_payload.ps1" @stageParameters
    $env:PIPER_CHATTERBOX_PAYLOAD_DIR = (Resolve-Path -LiteralPath $PayloadDir).Path
    $hasSharedPayload = $true
}

$VerifySharedPayload = @'
import json
import os
from pathlib import Path
from piper.chatterbox_assets import inspect_chatterbox_installation

root = Path(os.environ['PIPER_CHATTERBOX_PAYLOAD_DIR'])
manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
declared = manifest.get('models')
if not isinstance(declared, dict) or not declared:
    raise ValueError('shared Chatterbox payload must declare at least one model')
required = {
    engine for engine in ('nano', 'turbo')
    if os.environ.get('PIPER_REQUIRE_' + engine.upper() + '_PAYLOAD') == '1'
}
inspect_chatterbox_installation(root, next(iter(declared)))
for engine in sorted(required - set(declared)):
    inspect_chatterbox_installation(root, engine)
'@
if ($hasSharedPayload) {
    $env:PYTHONPATH = Join-Path $Root "src"
    python -c $VerifySharedPayload
    if ($LASTEXITCODE -ne 0) { throw "Shared Chatterbox payload failed integrity or required-engine checks" }
}

python -m PyInstaller --clean --noconfirm script/piper_tray.spec
if ($LASTEXITCODE -ne 0) { throw "Piper Tray packaging failed" }

# Keep offline weights readable by standard Windows users after packaging.
$ChatterboxPayloadDir = Join-Path $DistDir "_internal\chatterbox_payload"
if (Test-Path -LiteralPath $ChatterboxPayloadDir -PathType Container) {
    & icacls.exe $ChatterboxPayloadDir /grant '*S-1-5-32-545:(OI)(CI)(RX)' /T /C | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Could not grant standard Windows users read access to the Chatterbox payload"
    }
}

if (-not (Test-Path -LiteralPath $Exe -PathType Leaf)) { throw "Expected executable was not created: $Exe" }
if (-not (Test-Path -LiteralPath (Join-Path $DistDir "_internal") -PathType Container)) { throw "PyInstaller support directory missing" }
$File = Get-Item $Exe
if ($requireNano -or $requireTurbo) {
    $env:PIPER_CHATTERBOX_PAYLOAD_DIR = $ChatterboxPayloadDir
    $env:PYTHONPATH = Join-Path $Root "src"
    python -c $VerifySharedPayload
    if ($LASTEXITCODE -ne 0) { throw "Built app does not contain every required Chatterbox engine" }
}
if ($File.Length -le 0) { throw "Built executable is empty: $Exe" }
$Hash = Get-FileHash -Algorithm SHA256 $Exe
Write-Host "Built $DistDir"
Write-Host "Launcher size: $($File.Length) bytes"
Write-Host "Launcher SHA256: $($Hash.Hash)"
