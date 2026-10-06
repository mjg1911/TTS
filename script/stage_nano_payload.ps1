param(
    [string]$Python = $env:PIPER_NANO_WORKER_PYTHON,
    [string]$ModelDir = $env:PIPER_NANO_MODEL_DIR,
    [string]$WorkerDir = 'dist/ChatterboxWorker',
    [string]$OutputDir = 'build/chatterbox-payload'
)
$ErrorActionPreference = 'Stop'
$arguments = @{
    WorkerDir = $WorkerDir
    OutputDir = $OutputDir
    DownloadNano = -not [bool]$ModelDir
}
if ($Python) { $arguments.Python = $Python }
if ($ModelDir) { $arguments.NanoModelDir = $ModelDir }
& (Join-Path $PSScriptRoot 'stage_chatterbox_payload.ps1') @arguments
