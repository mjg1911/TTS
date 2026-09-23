$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

python -m pip install --disable-pip-version-check --require-hashes -r requirements/kokoro-worker-win-py311.lock
python -m pip install --disable-pip-version-check "pyinstaller>=6,<7"
python -m PyInstaller --noconfirm --clean script/kokoro_worker.spec

$workerExe = "dist/KokoroWorker/KokoroWorker.exe"
if (-not (Test-Path $workerExe)) { throw "$workerExe was not produced" }
if ((Get-Item $workerExe).Length -le 0) { throw "$workerExe is empty" }
& "$Root/script/smoke_kokoro_worker_stdio.ps1" -WorkerExe $workerExe
