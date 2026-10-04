param(
    [string]$Python = $env:PIPER_MULTILINGUAL_WORKER_PYTHON,
    [string]$ModelDir = $env:PIPER_MULTILINGUAL_MODEL_DIR,
    [string]$PKUsegArchive = $env:PIPER_MULTILINGUAL_PKUSEG_ARCHIVE,
    [string]$WorkerDir = 'dist/MultilingualWorker',
    [string]$OutputDir = 'build/multilingual-payload'
)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (-not $Python) { $Python = Join-Path $Root 'build/multilingual-venv/Scripts/python.exe' }
$env:PYTHONPATH = Join-Path $Root 'src'
$arguments = @('script/stage_multilingual_payload.py', '--worker-dir', $WorkerDir, '--output', $OutputDir)
if ($ModelDir) { $arguments += @('--model-dir', $ModelDir) }
if ($PKUsegArchive) { $arguments += @('--pkuseg-archive', $PKUsegArchive) }
& $Python @arguments
if ($LASTEXITCODE -ne 0) { throw 'Multilingual payload staging failed' }
