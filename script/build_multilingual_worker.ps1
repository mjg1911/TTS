param([string]$Python = $env:PIPER_MULTILINGUAL_WORKER_PYTHON, [switch]$SkipInstall)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (-not $Python) {
    $Python = Join-Path $Root 'build/multilingual-venv/Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $Python)) {
        & python -m venv (Join-Path $Root 'build/multilingual-venv')
        if ($LASTEXITCODE -ne 0) { throw 'Multilingual environment creation failed' }
    }
}
if (-not (Test-Path -LiteralPath $Python)) { throw "Python environment not found: $Python" }
if (-not $SkipInstall) {
    & $Python -m pip install torch==2.6.0+cu124 torchaudio==2.6.0+cu124 --index-url https://download.pytorch.org/whl/cu124
    if ($LASTEXITCODE -ne 0) { throw 'Multilingual CUDA Torch installation failed' }
    & $Python -m pip install -r requirements/multilingual-worker.in
    if ($LASTEXITCODE -ne 0) { throw 'Multilingual worker dependency installation failed' }
}
$env:PYTHONPATH = Join-Path $Root 'src'
$Check = @'
import inspect
import json
import torch
from importlib.metadata import distribution
from piper.multilingual_assets import SOURCE_REVISION
from piper.multilingual_worker.main import main
from chatterbox.mtl_tts import ChatterboxMultilingualTTS, _resolve_multilingual_t3_model

installed = json.loads(distribution('chatterbox-tts').read_text('direct_url.json'))
assert installed['vcs_info']['commit_id'] == SOURCE_REVISION
assert 't3_model' in inspect.signature(ChatterboxMultilingualTTS.from_local).parameters
assert _resolve_multilingual_t3_model('v3') == 't3_mtl23ls_v3.safetensors'
assert torch.__version__ == '2.6.0+cu124'
assert torch.version.cuda == '12.4'
assert callable(main)
'@
& $Python -c $Check
if ($LASTEXITCODE -ne 0) { throw 'Pinned Multilingual V3 CUDA worker API check failed' }
& $Python -m PyInstaller --noconfirm --clean script/multilingual_worker.spec
if ($LASTEXITCODE -ne 0) { throw 'Multilingual worker build failed' }
if (-not (Test-Path -LiteralPath 'dist/MultilingualWorker/MultilingualWorker.exe')) { throw 'MultilingualWorker.exe was not produced' }
