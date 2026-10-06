param([string]$Python = $env:PIPER_NANO_WORKER_PYTHON, [switch]$SkipInstall)
$ErrorActionPreference = 'Stop'
$parameters = @{}
if ($Python) { $parameters.Python = $Python }
if ($SkipInstall) { $parameters.SkipInstall = $true }
& (Join-Path $PSScriptRoot 'build_chatterbox_worker.ps1') @parameters
