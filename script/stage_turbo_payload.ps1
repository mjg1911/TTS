param(
    [string]$Python = $env:PIPER_TURBO_WORKER_PYTHON,
    [string]$ModelDir = $env:PIPER_TURBO_MODEL_DIR,
    [string]$WorkerDir = 'dist/ChatterboxWorker',
    [string]$OutputDir = 'build/chatterbox-payload'
)
$ErrorActionPreference = 'Stop'
$arguments = @{
    WorkerDir = $WorkerDir
    OutputDir = $OutputDir
    DownloadTurbo = -not [bool]$ModelDir
}
if ($Python) { $arguments.Python = $Python }
if ($ModelDir) { $arguments.TurboModelDir = $ModelDir }
& (Join-Path $PSScriptRoot 'stage_chatterbox_payload.ps1') @arguments
