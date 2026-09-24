"""Deploy the bundled Kokoro payload using lightweight structural checks."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import tempfile

from piper.kokoro_assets import KokoroInstallation, inspect_kokoro_installation


def _install_bundled_payload(
    bundle_root: Path,
    install_root: Path,
    replace_existing: bool,
) -> KokoroInstallation:
    install_root.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix="Kokoro.install-", dir=str(install_root.parent))
    )
    backup = install_root.with_name(install_root.name + ".previous")
    moved_old = False
    try:
        shutil.rmtree(temporary)
        shutil.copytree(bundle_root, temporary)
        inspect_kokoro_installation(temporary)
        if backup.exists():
            shutil.rmtree(backup)
        if replace_existing:
            os.replace(install_root, backup)
            moved_old = True
        os.replace(temporary, install_root)
        installed = inspect_kokoro_installation(install_root)
        if moved_old and backup.exists():
            shutil.rmtree(backup)
        return installed
    except (OSError, ValueError, KeyError):
        if moved_old:
            if install_root.exists():
                shutil.rmtree(install_root, ignore_errors=True)
            if backup.exists():
                os.replace(backup, install_root)
        raise
    finally:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)


def ensure_bundled_kokoro_payload(
    bundle_root: Path, install_root: Path
) -> KokoroInstallation:
    bundle_root = bundle_root.resolve()
    install_root = install_root.resolve()

    inspect_kokoro_installation(bundle_root)
    bundle_manifest = (bundle_root / "manifest.json").read_bytes()

    if not install_root.exists():
        return _install_bundled_payload(
            bundle_root,
            install_root,
            replace_existing=False,
        )

    installed = inspect_kokoro_installation(install_root)
    installed_manifest = (install_root / "manifest.json").read_bytes()
    if installed_manifest == bundle_manifest:
        return installed

    return _install_bundled_payload(
        bundle_root,
        install_root,
        replace_existing=True,
    )
