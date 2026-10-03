param([string]$Python = $env:PIPER_NANO_WORKER_PYTHON, [string]$ModelDir = $env:PIPER_NANO_MODEL_DIR, [string]$WorkerDir = 'dist/NanoWorker', [string]$OutputDir = 'build/nano-payload')
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (-not $Python) { $Python = Join-Path $Root 'build/nano-venv/Scripts/python.exe' }
$env:PYTHONPATH = Join-Path $Root 'src'
$arguments = @('script/stage_nano_payload.py', '--worker-dir', $WorkerDir, '--output', $OutputDir)
if ($ModelDir) { $arguments += @('--model-dir', $ModelDir) }
& $Python @arguments
if ($LASTEXITCODE -ne 0) { throw 'Nano payload staging failed' }
