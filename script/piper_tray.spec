from pathlib import Path
import json
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
release_mode = os.environ.get("PIPER_RELEASE_MODE") == "1"
catalog_path = ROOT / "src" / "piper" / "model_catalog.json"
piper_datas.append((str(catalog_path), "piper"))
voice_datas = []
if release_mode:
    voice_root = Path(os.environ.get("PIPER_DEFAULT_VOICE_DIR", str(ROOT / "Voices")))
    for name in ("en_GB-alba-medium.onnx", "en_GB-alba-medium.onnx.json"):
        path = voice_root / name
        if not path.is_file() or not path.stat().st_size:
            raise RuntimeError("Release requires the default Piper voice: " + str(path))
        voice_datas.append((str(path), "voices"))
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

for legacy_name in ("PIPER_NANO_PAYLOAD_DIR", "PIPER_TURBO_PAYLOAD_DIR"):
    if not release_mode and os.environ.get(legacy_name):
        raise RuntimeError(
            f"{legacy_name} is no longer supported; use PIPER_CHATTERBOX_PAYLOAD_DIR"
        )

chatterbox_payload_datas = []
chatterbox_payload_text = None if release_mode else os.environ.get("PIPER_CHATTERBOX_PAYLOAD_DIR")
required_engines = {
    engine
    for engine in ("nano", "turbo")
    if not release_mode and os.environ.get(f"PIPER_REQUIRE_{engine.upper()}_PAYLOAD") == "1"
}
if chatterbox_payload_text:
    from piper.chatterbox_assets import inspect_chatterbox_installation

    chatterbox_payload_root = Path(chatterbox_payload_text).resolve()
    manifest_path = chatterbox_payload_root / "manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError("PIPER_CHATTERBOX_PAYLOAD_DIR has no manifest.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        declared_engines = set(manifest.get("models", {}))
    except (AttributeError, json.JSONDecodeError) as error:
        raise RuntimeError("shared Chatterbox manifest is invalid") from error
    inspection_engine = sorted(declared_engines or required_engines or {"nano"})[0]
    inspect_chatterbox_installation(chatterbox_payload_root, inspection_engine)
    for engine in sorted(required_engines - declared_engines):
        inspect_chatterbox_installation(chatterbox_payload_root, engine)
    chatterbox_payload_datas = _runtime_tree(
        chatterbox_payload_root, "chatterbox_payload"
    )
elif required_engines:
    names = ", ".join(sorted(required_engines))
    raise RuntimeError(
        "release build requires PIPER_CHATTERBOX_PAYLOAD_DIR with " + names
    )
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
    datas=piper_datas + tkinter_datas + chatterbox_payload_datas + voice_datas,
    hookspath=[str(SPEC_DIR / "pyinstaller_hooks")],
    hiddenimports=hiddenimports,
    excludes=["torch", "torchaudio", "chatterbox", "transformers", "diffusers",
              "accelerate", "piper.train", "piper.train.vits"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PiperTray",
    icon=str(ROOT / "build" / "piper-tray" / "piper-tray.ico"),
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name="PiperTray",
)
