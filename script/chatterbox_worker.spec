from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata


ROOT = Path(SPECPATH).parent
hiddenimports, datas, binaries = [], [], []
for package in (
    "chatterbox",
    "perth",
    "s3tokenizer",
    "transformers",
    "diffusers",
    "librosa",
    "torchaudio",
    "requests",
):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden
for package in (
    "chatterbox-tts",
    "resemble-perth",
    "transformers",
    "safetensors",
    "huggingface-hub",
    "requests",
):
    datas += copy_metadata(package)

# The shared dispatcher selects these modules at runtime, so PyInstaller cannot
# reliably discover both serving paths by following imports from the entrypoint.
hiddenimports += collect_submodules("piper.chatterbox_worker")
hiddenimports += collect_submodules("piper.nano_worker")
hiddenimports += collect_submodules("piper.turbo_worker")
a = Analysis(
    [str(ROOT / "script" / "chatterbox_worker_entry.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    module_collection_mode={"librosa": "py"},
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="ChatterboxWorker", console=True)
coll = COLLECT(exe, a.binaries, a.datas, name="ChatterboxWorker")
