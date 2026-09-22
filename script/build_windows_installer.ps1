$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$compiler = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $compiler)) {
    throw "Inno Setup 6 is required to build the installer"
}
if (-not (Test-Path "dist/PiperTray.exe")) {
    throw "Build dist/PiperTray.exe before the installer"
}
$setupText = Get-Content "setup.py" -Raw
$versionMatch = [regex]::Match($setupText, 'version="([^"]+)"')
$version = $versionMatch.Groups[1].Value
if ([string]::IsNullOrWhiteSpace($version)) { throw "Could not read package version" }
& $compiler "/DMyAppVersion=$version" "script/piper_tray_installer.iss"
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup failed with exit code $LASTEXITCODE"
}
if (-not (Test-Path "dist/PiperTraySetup.exe")) {
    throw "dist/PiperTraySetup.exe was not produced"
}
