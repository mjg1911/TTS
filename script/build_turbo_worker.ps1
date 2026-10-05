param([string]$Python = $env:PIPER_TURBO_WORKER_PYTHON, [switch]$SkipInstall)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (-not $Python) {
    $Python = Join-Path $Root 'build/turbo-venv/Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $Python)) {
        & python -m venv (Join-Path $Root 'build/turbo-venv')
        if ($LASTEXITCODE -ne 0) { throw 'Turbo environment creation failed' }
    }
}
if (-not (Test-Path -LiteralPath $Python)) { throw "Python environment not found: $Python" }
if (-not $SkipInstall) {
    & $Python -m pip install torch==2.6.0+cu124 torchaudio==2.6.0+cu124 --index-url https://download.pytorch.org/whl/cu124
    if ($LASTEXITCODE -ne 0) { throw 'Turbo CUDA Torch installation failed' }
    & $Python -m pip install -r requirements/turbo-worker.in
    if ($LASTEXITCODE -ne 0) { throw 'Turbo worker dependency installation failed' }
}
$env:PYTHONPATH = Join-Path $Root 'src'
$Check = @'
import inspect
import json
import torch
from importlib.metadata import distribution
from pathlib import Path
from piper.turbo_assets import SOURCE_REVISION
from piper.turbo_worker.main import main
from chatterbox.tts_turbo import ChatterboxTurboTTS

installed = json.loads(distribution('chatterbox-tts').read_text('direct_url.json'))
assert installed['vcs_info']['commit_id'] == SOURCE_REVISION
signature = inspect.signature(ChatterboxTurboTTS.from_local)
assert 'nano' in signature.parameters
signature.bind(Path('model'), device='cuda', nano=False)
assert torch.__version__ == '2.6.0+cu124'
assert torch.version.cuda == '12.4'
assert callable(main)
'@
& $Python -c $Check
if ($LASTEXITCODE -ne 0) { throw 'Pinned Turbo CUDA worker API check failed' }
& $Python -m PyInstaller --noconfirm --clean script/turbo_worker.spec
if ($LASTEXITCODE -ne 0) { throw 'Turbo worker build failed' }
if (-not (Test-Path -LiteralPath 'dist/TurboWorker/TurboWorker.exe')) { throw 'TurboWorker.exe was not produced' }
