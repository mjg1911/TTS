from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)


SPEC_DIR = Path(SPECPATH)
ROOT = SPEC_DIR.parent
piper_datas = collect_data_files("piper")
piper_binaries = collect_dynamic_libs("piper")
piper_extensions = [
    (str(path), "piper")
    for path in (ROOT / "src" / "piper").glob("*.pyd")
]
if not piper_extensions:
    raise RuntimeError(
        "The compiled piper.espeakbridge extension was not built. "
        "Run the Windows build bootstrap again."
    )
hiddenimports = collect_submodules("pystray") + ["piper.espeakbridge"]

a = Analysis(
    [str(SPEC_DIR / "piper_tray_entry.py")],
    pathex=[str(ROOT / "src")],
    binaries=piper_binaries + piper_extensions,
    datas=piper_datas,
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
