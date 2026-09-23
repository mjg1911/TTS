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

$requireKokoro = $env:PIPER_REQUIRE_KOKORO_PAYLOAD -eq "1"
$kokoroInputs = @(
    $env:PIPER_KOKORO_CONFIG,
    $env:PIPER_KOKORO_MODEL,
    $env:PIPER_KOKORO_AF_HEART
)
$hasKokoroInputs = @($kokoroInputs | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }).Count -eq $kokoroInputs.Count
if ($requireKokoro -and -not $hasKokoroInputs) {
    throw "release build requires local Kokoro asset paths"
}
if ($hasKokoroInputs) {
    & "$Root/script/build_kokoro_worker.ps1"
    & "$Root/script/stage_kokoro_payload.ps1"
    $env:PIPER_KOKORO_PAYLOAD_DIR = (Resolve-Path "build/kokoro-payload").Path
}
python -m PyInstaller --clean --noconfirm script/piper_tray.spec

if (-not (Test-Path $Exe -PathType Leaf)) { throw "Expected executable was not created: $Exe" }
if (-not (Test-Path (Join-Path $DistDir "_internal") -PathType Container)) { throw "PyInstaller support directory missing" }
if ($requireKokoro -and -not (Test-Path (Join-Path $DistDir "_internal\kokoro_payload\manifest.json") -PathType Leaf)) {
    throw "Required Kokoro payload was not collected"
}
$File = Get-Item $Exe
if ($File.Length -le 0) { throw "Built executable is empty: $Exe" }
$Hash = Get-FileHash -Algorithm SHA256 $Exe
Write-Host "Built $DistDir"
Write-Host "Launcher size: $($File.Length) bytes"
Write-Host "Launcher SHA256: $($Hash.Hash)"
