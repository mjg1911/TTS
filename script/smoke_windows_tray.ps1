$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Exe = Join-Path $Root "dist\PiperTray.exe"
if (-not (Test-Path $Exe)) {
    throw "Missing packaged executable: $Exe"
}

$BaseTemp = if ($env:RUNNER_TEMP) {
    $env:RUNNER_TEMP
} else {
    [System.IO.Path]::GetTempPath()
}
$SmokeRoot = Join-Path $BaseTemp "piper-tray-frozen-smoke"
$SmokeAppData = Join-Path $SmokeRoot "AppData"
$SmokeLocalAppData = Join-Path $SmokeRoot "LocalAppData"
$SmokeWorking = Join-Path $SmokeRoot "Working"

if (Test-Path $SmokeRoot) {
    Remove-Item -Recurse -Force $SmokeRoot
}
New-Item -ItemType Directory -Force $SmokeAppData | Out-Null
New-Item -ItemType Directory -Force $SmokeLocalAppData | Out-Null
New-Item -ItemType Directory -Force $SmokeWorking | Out-Null

$OldAppData = $env:APPDATA
$OldLocalAppData = $env:LOCALAPPDATA
$OldPythonPath = $env:PYTHONPATH
$Process = $null

try {
    $env:APPDATA = $SmokeAppData
    $env:LOCALAPPDATA = $SmokeLocalAppData
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue

    $Process = Start-Process `
        -FilePath $Exe `
        -WorkingDirectory $SmokeWorking `
        -PassThru

    Start-Sleep -Seconds 5
    $Process.Refresh()

    if ($Process.HasExited) {
        throw "PiperTray.exe exited during frozen-runtime bootstrap with code $($Process.ExitCode)"
    }

    $Log = Join-Path $SmokeLocalAppData "Piper\piper-tray.log"
    if (-not (Test-Path $Log)) {
        throw "Frozen runtime did not create its expected log: $Log"
    }

    Write-Host "Frozen-runtime smoke passed: process remained alive from a clean environment."
}
finally {
    try {
        if ($null -ne $Process) {
            $Process.Refresh()
            if (-not $Process.HasExited) {
                Stop-Process -Id $Process.Id -Force
            }
        }
    } finally {
        $env:APPDATA = $OldAppData
        $env:LOCALAPPDATA = $OldLocalAppData
        if ($null -eq $OldPythonPath) {
            Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
        } else {
            $env:PYTHONPATH = $OldPythonPath
        }

        if (Test-Path $SmokeRoot) {
            Remove-Item -Recurse -Force $SmokeRoot
        }
    }
}
