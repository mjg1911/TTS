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
hiddenimports = collect_submodules("pystray") + ["piper.espeakbridge"]

a = Analysis(
    [str(SPEC_DIR / "piper_tray_entry.py")],
    pathex=[str(ROOT / "src")],
    binaries=piper_binaries,
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
