param(
    [string]$Python = $env:PIPER_SUPERTONIC_BUILD_PYTHON,
    [switch]$SkipInstall
)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$BuildTemp = Join-Path $Root 'build/supertonic-tmp'
New-Item -ItemType Directory -Force -Path $BuildTemp | Out-Null
$env:TEMP = $BuildTemp
$env:TMP = $BuildTemp

$Venv = Join-Path $Root 'build/supertonic-venv'
$VenvPython = Join-Path $Venv 'Scripts/python.exe'
if (-not $Python) {
    if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
        $BasePython = Join-Path $Root '.venv/Scripts/python.exe'
        if (Test-Path -LiteralPath $BasePython -PathType Leaf) {
            & $BasePython -m venv $Venv
        } else {
            & py -3.11 -m venv $Venv
        }
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the isolated build/supertonic-venv environment.' }
    }
    & $VenvPython -m ensurepip --upgrade
    if ($LASTEXITCODE -ne 0) { throw 'Could not bootstrap pip in the isolated Supertonic environment.' }
    $Python = $VenvPython
}
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Supertonic build Python does not exist: $Python"
}

if (-not $SkipInstall) {
    # Install pinned top-level requirements without the SDK's generic CPU
    # onnxruntime dependency; then explicitly install the GPU wheel and its
    # CUDA/cuDNN dependencies below.
    & $Python -m pip install --no-deps -r (Join-Path $Root 'requirements/supertonic-worker.in')
    if ($LASTEXITCODE -ne 0) { throw 'Could not install pinned Supertonic worker packages.' }
    & $Python -m pip install 'onnxruntime-gpu[cuda,cudnn]==1.30.0' 'numpy==1.26.4' 'soundfile==0.13.1' 'huggingface-hub==1.33.0' 'pyinstaller==6.19.0'
    if ($LASTEXITCODE -ne 0) { throw 'Could not install the Supertonic CUDA runtime dependencies.' }
}

$env:PYTHONPATH = Join-Path $Root 'src'
& $Python -c "import onnxruntime as ort, supertonic; assert 'CUDAExecutionProvider' in ort.get_available_providers(), 'CUDAExecutionProvider is unavailable'; assert supertonic.__version__ == '1.3.1'"
if ($LASTEXITCODE -ne 0) {
    throw 'Supertonic GPU preflight failed. Install the NVIDIA CUDA 13 driver/runtime required by ONNX Runtime 1.30.'
}
& $Python -m PyInstaller --noconfirm --clean (Join-Path $Root 'script/supertonic_worker.spec')
if ($LASTEXITCODE -ne 0) { throw 'Supertonic worker packaging failed.' }
$Worker = Join-Path $Root 'dist/SupertonicWorker/SupertonicWorker.exe'
if (-not (Test-Path -LiteralPath $Worker -PathType Leaf)) {
    throw "Supertonic worker executable was not produced: $Worker"
}
Write-Host "Built isolated Supertonic GPU worker: $Worker"
