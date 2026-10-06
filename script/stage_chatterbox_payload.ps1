param(
    [string]$Python = $env:PIPER_CHATTERBOX_WORKER_PYTHON,
    [string]$WorkerDir = 'dist/ChatterboxWorker',
    [string]$OutputDir = $env:PIPER_CHATTERBOX_PAYLOAD_DIR,
    [string]$NanoModelDir = $env:PIPER_NANO_MODEL_DIR,
    [string]$TurboModelDir = $env:PIPER_TURBO_MODEL_DIR,
    [switch]$DownloadNano,
    [switch]$DownloadTurbo
)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (-not $Python) { $Python = Join-Path $Root 'build/chatterbox-venv/Scripts/python.exe' }
if (-not $OutputDir) { $OutputDir = 'build/chatterbox-payload' }
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Shared Chatterbox Python environment not found: $Python. Run build_chatterbox_worker.ps1 first."
}
$env:PYTHONPATH = Join-Path $Root 'src'
$arguments = @('script/stage_chatterbox_payload.py', '--worker-dir', $WorkerDir, '--output', $OutputDir)
if ($NanoModelDir) { $arguments += @('--nano-model-dir', $NanoModelDir) }
if ($TurboModelDir) { $arguments += @('--turbo-model-dir', $TurboModelDir) }
if ($DownloadNano) { $arguments += '--download-nano' }
if ($DownloadTurbo) { $arguments += '--download-turbo' }
& $Python @arguments
if ($LASTEXITCODE -ne 0) { throw 'Shared Chatterbox payload staging failed' }
