from pathlib import Path
import os
import sys

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)


SPEC_DIR = Path(SPECPATH)
ROOT = SPEC_DIR.parent
PYTHON_ROOT = Path(sys.base_prefix)
piper_datas = collect_data_files("piper")
piper_binaries = collect_dynamic_libs("piper")
piper_extensions = [
    (str(path), "piper")
    for path in (ROOT / "src" / "piper").glob("*.pyd")
]
tkinter_binaries = [
    (str(PYTHON_ROOT / "DLLs" / "_tkinter.pyd"), "."),
    (str(PYTHON_ROOT / "DLLs" / "tcl86t.dll"), "."),
    (str(PYTHON_ROOT / "DLLs" / "tk86t.dll"), "."),
]


def _runtime_tree(root: Path, destination: str):
    return [
        (str(path), str(Path(destination) / path.relative_to(root).parent))
        for path in root.rglob("*")
        if path.is_file()
    ]


tkinter_datas = [
    *_runtime_tree(PYTHON_ROOT / "tcl" / "tcl8.6", "_tcl_data"),
    *_runtime_tree(PYTHON_ROOT / "tcl" / "tk8.6", "_tk_data"),
]

payload_text = os.environ.get("PIPER_KOKORO_PAYLOAD_DIR")
kokoro_payload_datas = []
if payload_text:
    payload_root = Path(payload_text).resolve()
    if not (payload_root / "manifest.json").is_file():
        raise RuntimeError("PIPER_KOKORO_PAYLOAD_DIR has no manifest.json")
    kokoro_payload_datas = _runtime_tree(payload_root, "kokoro_payload")
elif os.environ.get("PIPER_REQUIRE_KOKORO_PAYLOAD") == "1":
    raise RuntimeError("release build requires PIPER_KOKORO_PAYLOAD_DIR")
if not piper_extensions:
    raise RuntimeError(
        "The compiled piper.espeakbridge extension was not built. "
        "Run the Windows build bootstrap again."
    )
# TkUi is imported from inside run_app(), so keep the desktop modules in the
# frozen bundle even though PyInstaller cannot reliably discover that import
# through the lazy boundary.
hiddenimports = collect_submodules("pystray") + [
    "piper.espeakbridge",
    "tkinter",
    "tkinter.filedialog",
    "tkinter.messagebox",
    "tkinter.simpledialog",
]

a = Analysis(
    [str(SPEC_DIR / "piper_tray_entry.py")],
    pathex=[str(ROOT / "src")],
    binaries=piper_binaries + piper_extensions + tkinter_binaries,
    datas=piper_datas + tkinter_datas + kokoro_payload_datas,
    hookspath=[str(SPEC_DIR / "pyinstaller_hooks")],
    hiddenimports=hiddenimports,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PiperTray",
    icon=str(ROOT / "build" / "piper-tray" / "piper-tray.ico"),
    console=False,
)
