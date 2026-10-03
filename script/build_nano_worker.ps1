param([string]$Python = $env:PIPER_NANO_WORKER_PYTHON, [switch]$SkipInstall)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (-not $Python) {
    $Python = Join-Path $Root 'build/nano-venv/Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $Python)) {
        & python -m venv (Join-Path $Root 'build/nano-venv')
        if ($LASTEXITCODE -ne 0) { throw 'Nano environment creation failed' }
    }
}
if (-not $SkipInstall) {
    & $Python -m pip install torch==2.6.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cpu
    if ($LASTEXITCODE -ne 0) { throw 'Nano CPU Torch installation failed' }
    & $Python -m pip install -r requirements/nano-worker.in
    if ($LASTEXITCODE -ne 0) { throw 'Nano dependency installation failed' }
}
$env:PYTHONPATH = Join-Path $Root 'src'
& $Python -c "from chatterbox.tts_turbo import ChatterboxTurboTTS; import inspect; assert 'nano' in inspect.signature(ChatterboxTurboTTS.from_local).parameters"
if ($LASTEXITCODE -ne 0) { throw 'Pinned Nano API import check failed' }
& $Python -m PyInstaller --noconfirm --clean script/nano_worker.spec
if ($LASTEXITCODE -ne 0) { throw 'Nano worker build failed' }
if (-not (Test-Path -LiteralPath 'dist/NanoWorker/NanoWorker.exe')) { throw 'NanoWorker.exe was not produced' }
