$ErrorActionPreference = "Stop"

if ($env:OS -ne "Windows_NT") {
    throw "PiperTray.exe must be built on Windows."
}

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$IconDir = Join-Path $Root "build\piper-tray"
$DistDir = Join-Path $Root "dist\PiperTray"
$Exe = Join-Path $DistDir "PiperTray.exe"

if (Test-Path $IconDir) { Remove-Item -Recurse -Force -LiteralPath $IconDir }
if (Test-Path $DistDir) { Remove-Item -Recurse -Force -LiteralPath $DistDir }

python -m pip install -e ".[windows-tray,windows-tray-build]"
python setup.py build_ext --inplace

$Bridge = Get-ChildItem (Join-Path $Root "src\piper") -Filter "espeakbridge*.pyd" -File
if ($null -eq $Bridge) {
    throw "espeakbridge.pyd was not built; the packaged executable would not be able to synthesize speech."
}

python script/make_piper_tray_icon.py

$requireNano = $env:PIPER_REQUIRE_NANO_PAYLOAD -eq "1"
$hasNanoModel = -not [string]::IsNullOrWhiteSpace($env:PIPER_NANO_MODEL_DIR)
if ($requireNano -and -not $hasNanoModel -and
    [string]::IsNullOrWhiteSpace($env:PIPER_NANO_PAYLOAD_DIR)) {
    throw "release build requires a local Nano model directory or staged payload"
}
if ($hasNanoModel) {
    & "$Root/script/build_nano_worker.ps1"
    & "$Root/script/stage_nano_payload.ps1"
    $env:PIPER_NANO_PAYLOAD_DIR = (Resolve-Path "build/nano-payload").Path
}
$requireTurbo = $env:PIPER_REQUIRE_TURBO_PAYLOAD -eq "1"
$hasTurboModel = -not [string]::IsNullOrWhiteSpace($env:PIPER_TURBO_MODEL_DIR)
if ($requireTurbo -and -not $hasTurboModel -and
    [string]::IsNullOrWhiteSpace($env:PIPER_TURBO_PAYLOAD_DIR)) {
    throw "release build requires a local Turbo model directory or staged payload"
}
if ($hasTurboModel) {
    & "$Root/script/build_turbo_worker.ps1"
    & "$Root/script/stage_turbo_payload.ps1"
    $env:PIPER_TURBO_PAYLOAD_DIR = (Resolve-Path "build/turbo-payload").Path
}
python -m PyInstaller --clean --noconfirm script/piper_tray.spec
if ($LASTEXITCODE -ne 0) { throw "Piper Tray packaging failed" }

# Some frozen payload trees can retain a protected DACL that excludes the
# account running Piper. Keep the offline Turbo assets readable by standard
# Windows users after packaging.
$TurboPayloadDir = Join-Path $DistDir "_internal\turbo_payload"
if (Test-Path -LiteralPath $TurboPayloadDir -PathType Container) {
    & icacls.exe $TurboPayloadDir /grant '*S-1-5-32-545:(OI)(CI)(RX)' /T /C | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Could not grant standard Windows users read access to the Turbo payload"
    }
}

if (-not (Test-Path $Exe -PathType Leaf)) { throw "Expected executable was not created: $Exe" }
if (-not (Test-Path (Join-Path $DistDir "_internal") -PathType Container)) { throw "PyInstaller support directory missing" }
$File = Get-Item $Exe
if ($requireNano -and -not (Test-Path (Join-Path $DistDir "_internal\nano_payload\manifest.json") -PathType Leaf)) {
    throw "Required Chatterbox Nano payload was not collected"
}
if ($File.Length -le 0) { throw "Built executable is empty: $Exe" }
if ($requireTurbo -and -not (Test-Path (Join-Path $DistDir "_internal\turbo_payload\manifest.json") -PathType Leaf)) {
    throw "Required Chatterbox Turbo payload was not collected"
}
$Hash = Get-FileHash -Algorithm SHA256 $Exe
Write-Host "Built $DistDir"
Write-Host "Launcher size: $($File.Length) bytes"
Write-Host "Launcher SHA256: $($Hash.Hash)"
