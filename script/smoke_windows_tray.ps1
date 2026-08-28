param(
    [string]$VoiceDirectory = $env:PIPER_SMOKE_VOICE_DIR
)

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
$SmokeRoot = Join-Path $BaseTemp "piper-tray-frozen-smoke-$([System.Guid]::NewGuid().ToString('N'))"
$SmokeAppData = Join-Path $SmokeRoot "AppData"
$SmokeLocalAppData = Join-Path $SmokeRoot "LocalAppData"
$SmokeWorking = Join-Path $SmokeRoot "Working"
$SmokeVoice = Join-Path $SmokeLocalAppData "Piper"

if (-not $VoiceDirectory) {
    $VoiceDirectory = $Root
}

$VoiceModel = Join-Path $VoiceDirectory "en_GB-alba-medium.onnx"
$VoiceConfig = Join-Path $VoiceDirectory "en_GB-alba-medium.onnx.json"
if (-not (Test-Path $VoiceModel) -or -not (Test-Path $VoiceConfig)) {
    throw "Frozen smoke requires en_GB-alba-medium.onnx and its matching JSON in $VoiceDirectory"
}

New-Item -ItemType Directory -Force $SmokeRoot | Out-Null
New-Item -ItemType Directory -Force $SmokeAppData | Out-Null
New-Item -ItemType Directory -Force $SmokeLocalAppData | Out-Null
New-Item -ItemType Directory -Force $SmokeWorking | Out-Null
New-Item -ItemType Directory -Force $SmokeVoice | Out-Null
New-Item -ItemType Directory -Force (Join-Path $SmokeAppData "Piper") | Out-Null
Copy-Item $VoiceModel $SmokeVoice
Copy-Item $VoiceConfig $SmokeVoice
@{
    schema_version = 1
    voice = "en_GB-alba-medium"
    hotkey = "alt+backtick"
    log_level = "INFO"
} | ConvertTo-Json | Set-Content (Join-Path (Join-Path $SmokeAppData "Piper") "settings.json")

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

    $Log = Join-Path $SmokeLocalAppData "Piper\piper-tray.log"
    $Ready = $false
    $Deadline = [DateTime]::UtcNow.AddSeconds(60)
    while ([DateTime]::UtcNow -lt $Deadline) {
        $Process.Refresh()
        if ($Process.HasExited) {
            throw "PiperTray.exe exited during frozen-runtime startup with code $($Process.ExitCode)"
        }

        if (Test-Path $Log) {
            $LogText = Get-Content -Raw $Log
            if ($LogText -match "Piper tray runtime ready") {
                $Ready = $true
                break
            }
        }

        Start-Sleep -Seconds 1
    }

    if (-not (Test-Path $Log)) {
        throw "Frozen runtime did not create its expected log: $Log"
    }
    if (-not $Ready) {
        throw "Frozen runtime did not report tray readiness within 60 seconds"
    }

    Write-Host "Frozen-runtime smoke passed: tray runtime reached its event loop from an isolated environment."
}
finally {
    try {
        if ($null -ne $Process) {
            $Process.Refresh()
            if (-not $Process.HasExited) {
                Stop-Process -Id $Process.Id -Force
            }
            $Process.WaitForExit(10000) | Out-Null
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
            $CleanupError = $null
            for ($Attempt = 1; $Attempt -le 10; $Attempt++) {
                try {
                    Remove-Item -Recurse -Force $SmokeRoot -ErrorAction Stop
                    $CleanupError = $null
                    break
                } catch {
                    $CleanupError = $_
                    if ($Attempt -lt 10) {
                        Start-Sleep -Seconds 1
                    }
                }
            }
            if ($null -ne $CleanupError) {
                throw $CleanupError
            }
        }
    }
}
