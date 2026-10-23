from pathlib import Path
from sysconfig import get_paths

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
    copy_metadata,
)


ROOT = Path(SPECPATH).parent
hiddenimports, datas, binaries = [], [], []

# Include just the SDK's inference path. Its optional API server is not part
# of this small worker and has separate FastAPI dependencies.
hiddenimports += [
    "supertonic",
    "supertonic.config",
    "supertonic.core",
    "supertonic.loader",
    "supertonic.pipeline",
    "supertonic.utils",
    "onnxruntime",
    "onnxruntime.capi",
    "onnxruntime.capi.onnxruntime_pybind11_state",
]
datas += collect_data_files("supertonic")
datas += collect_data_files("onnxruntime")
binaries += collect_dynamic_libs("onnxruntime")

# NVIDIA's runtime wheels use namespace directories without __init__.py, so
# enumerate their DLLs directly and preserve their relative directory layout.
nvidia_root = Path(get_paths()["purelib"]) / "nvidia"
if nvidia_root.is_dir():
    for library in nvidia_root.rglob("*.dll"):
        destination = Path("nvidia") / library.relative_to(nvidia_root).parent
        binaries.append((str(library), str(destination)))

hiddenimports += collect_submodules("piper.supertonic_worker")
hiddenimports += ["piper.windows_tray.worker_protocol"]
for package in ("supertonic", "onnxruntime-gpu", "numpy", "soundfile", "huggingface-hub"):
    try:
        datas += copy_metadata(package)
    except Exception:
        pass

a = Analysis(
    [str(ROOT / "script" / "supertonic_worker_entry.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="SupertonicWorker", console=True)
coll = COLLECT(exe, a.binaries, a.datas, name="SupertonicWorker")
