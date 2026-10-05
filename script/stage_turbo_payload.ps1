param(
    [string]$Python = $env:PIPER_TURBO_WORKER_PYTHON,
    [string]$ModelDir = $env:PIPER_TURBO_MODEL_DIR,
    [string]$WorkerDir = $env:PIPER_TURBO_WORKER_DIR,
    [string]$OutputDir = $env:PIPER_TURBO_PAYLOAD_DIR
)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (-not $Python) { $Python = Join-Path $Root 'build/turbo-venv/Scripts/python.exe' }
if (-not $WorkerDir) { $WorkerDir = 'dist/TurboWorker' }
if (-not $OutputDir) { $OutputDir = 'build/turbo-payload' }
$env:PYTHONPATH = Join-Path $Root 'src'
$arguments = @('script/stage_turbo_payload.py', '--worker-dir', $WorkerDir, '--output', $OutputDir)
if ($ModelDir) { $arguments += @('--model-dir', $ModelDir) }
& $Python @arguments
if ($LASTEXITCODE -ne 0) { throw 'Turbo payload staging failed' }
