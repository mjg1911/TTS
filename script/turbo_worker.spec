from pathlib import Path
from PyInstaller.utils.hooks import collect_all, copy_metadata

root = Path(SPECPATH).parent
hiddenimports, datas, binaries = [], [], []
for package in (
    'chatterbox',
    'perth',
    's3tokenizer',
    'transformers',
    'diffusers',
    'librosa',
    'torchaudio',
    'requests',
):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden
for package in (
    'chatterbox-tts',
    'resemble-perth',
    'transformers',
    'safetensors',
    'huggingface-hub',
    'requests',
):
    datas += copy_metadata(package)

a = Analysis(
    [str(root / 'script/turbo_worker_entry.py')],
    pathex=[str(root / 'src')],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    module_collection_mode={'librosa': 'py'},
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='TurboWorker', console=True)
coll = COLLECT(exe, a.binaries, a.datas, name='TurboWorker')
