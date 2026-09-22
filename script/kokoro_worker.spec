from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules


SPEC_DIR = Path(SPECPATH)
ROOT = SPEC_DIR.parent
packages = (
    "kokoro",
    "misaki",
    "spacy",
    "spacy_curated_transformers",
    "phonemizer",
    "espeakng_loader",
    "transformers",
    "torch",
    "en_core_web_sm",
)

datas = []
binaries = []
hiddenimports = []
for package in packages:
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas.extend(package_datas)
    binaries.extend(package_binaries)
    hiddenimports.extend(package_hidden)
    hiddenimports.extend(collect_submodules(package))

a = Analysis(
    [str(SPEC_DIR / "kokoro_worker_entry.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="KokoroWorker",
    console=True,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name="KokoroWorker",
)
