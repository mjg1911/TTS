$ErrorActionPreference = "Stop"

if ($env:OS -ne "Windows_NT") {
    throw "PiperTray.exe must be built on Windows."
}

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$IconDir = Join-Path $Root "build\piper-tray"
$Exe = Join-Path $Root "dist\PiperTray.exe"

if (Test-Path $IconDir) {
    Remove-Item -Recurse -Force $IconDir
}
if (Test-Path $Exe) {
    Remove-Item -Force $Exe
}

python -m pip install -e ".[windows-tray,windows-tray-build]"
python script/make_piper_tray_icon.py
python -m PyInstaller --clean --noconfirm script/piper_tray.spec

if (-not (Test-Path $Exe)) {
    throw "Expected executable was not created: $Exe"
}

$File = Get-Item $Exe
if ($File.Length -le 0) {
    throw "Built executable is empty: $Exe"
}

$Hash = Get-FileHash -Algorithm SHA256 $Exe
Write-Host "Built $Exe"
Write-Host "Size: $($File.Length) bytes"
Write-Host "SHA256: $($Hash.Hash)"
