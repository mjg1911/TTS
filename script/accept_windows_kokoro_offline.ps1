#requires -RunAsAdministrator

param(
    [string]$TrayExe = "dist/PiperTray/PiperTray.exe"
)

$ErrorActionPreference = "Stop"
$tray = (Resolve-Path $TrayExe).Path
if (-not (Test-Path $tray)) { throw "PiperTray.exe missing" }

$stateRoot = Join-Path $env:TEMP ("PiperKokoroAcceptance-" + $PID)
$originalLocalAppData = $env:LOCALAPPDATA
$originalAppData = $env:APPDATA
$env:LOCALAPPDATA = Join-Path $stateRoot "LocalAppData"
$env:APPDATA = Join-Path $stateRoot "RoamingAppData"
New-Item -ItemType Directory -Force -Path $env:LOCALAPPDATA, $env:APPDATA | Out-Null
$installRoot = Join-Path $env:LOCALAPPDATA "Piper/Kokoro"
$worker = Join-Path $installRoot "worker/KokoroWorker.exe"
Get-Process -Name "KokoroWorker" -ErrorAction SilentlyContinue | Stop-Process -Force
Remove-Item $installRoot -Recurse -Force -ErrorAction SilentlyContinue

$rulePrefix = "PiperKokoroAcceptance-$PID"
$trayRule = "$rulePrefix-Tray"
$workerRule = "$rulePrefix-Worker"
try {
    New-NetFirewallRule -DisplayName $trayRule -Direction Outbound -Program $tray -Action Block | Out-Null
    New-NetFirewallRule -DisplayName $workerRule -Direction Outbound -Program $worker -Action Block | Out-Null

    $trayProcess = Start-Process -FilePath $tray -PassThru
    Start-Sleep -Seconds 5
    if ($trayProcess.HasExited) { throw "PiperTray exited during offline first launch" }
    if (-not (Test-Path (Join-Path $installRoot "manifest.json"))) {
        throw "Kokoro payload was not deployed"
    }
    if (-not (Test-Path $worker)) { throw "installed KokoroWorker.exe missing" }
    Stop-Process -Id $trayProcess.Id -Force
    & pwsh -File script/smoke_windows_kokoro.ps1 -PayloadRoot $installRoot
    if ($LASTEXITCODE -ne 0) { throw "installed Kokoro worker offline smoke failed" }

    $voice = Join-Path $installRoot "voices/af_heart.pt"
    $backup = "$voice.clean"
    Get-Process -Name "KokoroWorker" -ErrorAction SilentlyContinue | Stop-Process -Force
    Copy-Item $voice $backup -Force
    try {
        [byte[]]$bytes = [IO.File]::ReadAllBytes($voice)
        $bytes[0] = $bytes[0] -bxor 1
        [IO.File]::WriteAllBytes($voice, $bytes)
        $corruptHash = (Get-FileHash $voice -Algorithm SHA256).Hash
        $trayProcess = Start-Process -FilePath $tray -PassThru
        Start-Sleep -Seconds 5
        if ($trayProcess.HasExited) { throw "tray exited on corrupt Kokoro asset" }
        $workers = Get-Process -Name "KokoroWorker" -ErrorAction SilentlyContinue
        if ($workers) { throw "KokoroWorker started despite manifest hash failure" }
        if ((Get-FileHash $voice -Algorithm SHA256).Hash -ne $corruptHash) {
            throw "corrupt Kokoro asset was automatically repaired"
        }
        Stop-Process -Id $trayProcess.Id -Force
    } finally {
        if ($trayProcess -and -not $trayProcess.HasExited) { Stop-Process -Id $trayProcess.Id -Force }
        Move-Item $backup $voice -Force
        Get-Process -Name "KokoroWorker" -ErrorAction SilentlyContinue | Stop-Process -Force
    }
} finally {
    Remove-NetFirewallRule -DisplayName $trayRule -ErrorAction SilentlyContinue
    Remove-NetFirewallRule -DisplayName $workerRule -ErrorAction SilentlyContinue
    $env:LOCALAPPDATA = $originalLocalAppData
    $env:APPDATA = $originalAppData
    Remove-Item $stateRoot -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "OFFLINE KOKORO ACCEPTANCE PASSED"
