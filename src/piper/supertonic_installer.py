"""Download and validate the pinned Supertonic 3 model for the tray app."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import uuid
from typing import Callable, Optional
from urllib.request import Request, urlopen


ENGINE = "Supertonic 3"
MODEL_REPO = "Supertone/supertonic-3"
MODEL_REVISION = "3cadd1ee6394adea1bd021217a0e650ede09a323"
SOURCE_REPO = "supertone-oss-archive/supertonic-py"
SOURCE_REVISION = "df0f9686dac7fbbde391b759e2ee5286a3737622"
MANIFEST_NAME = "model_assets.json"
WORKER_EXE = "worker/SupertonicWorker.exe"
DOWNLOAD_TIMEOUT_SECONDS = 30
READ_BLOCK_BYTES = 1024 * 1024
_MANIFEST_VERSION = 1
_INSTALL_LOCK = threading.Lock()

_MODEL_ASSETS = (
    "config.json",
    "onnx/duration_predictor.onnx",
    "onnx/text_encoder.onnx",
    "onnx/vector_estimator.onnx",
    "onnx/vocoder.onnx",
    "onnx/tts.json",
    "onnx/unicode_indexer.json",
    "voice_styles/F1.json",
    "voice_styles/F2.json",
    "voice_styles/F3.json",
    "voice_styles/F4.json",
    "voice_styles/F5.json",
    "voice_styles/M1.json",
    "voice_styles/M2.json",
    "voice_styles/M3.json",
    "voice_styles/M4.json",
    "voice_styles/M5.json",
    "LICENSE",
    "SOURCE-LICENSE",
)
ASSET_PATHS = _MODEL_ASSETS
_WORKER_DIRECTORY_ENV = "PIPER_SUPERTONIC_WORKER_DIR"
_WORKER_PYTHON_ENV = "PIPER_SUPERTONIC_WORKER_PYTHON"


class SupertonicInstallError(RuntimeError):
    """A Supertonic model or worker runtime could not be installed."""


class DownloadCancelled(SupertonicInstallError):
    """The user cancelled a Supertonic installation."""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(READ_BLOCK_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()


def installation_root() -> Path:
    """Return the per-user model and worker installation directory."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "Piper" / "Supertonic3"
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        return Path(local_appdata) / "Piper" / "Supertonic3"
    return Path.home() / ".piper" / "Supertonic3"


def asset_url_for_path(relative: str) -> str:
    """Return the immutable upstream URL for one required asset."""
    if relative == "SOURCE-LICENSE":
        return (
            "https://raw.githubusercontent.com/" + SOURCE_REPO + "/"
            + SOURCE_REVISION + "/LICENSE"
        )
    if relative not in _MODEL_ASSETS:
        raise ValueError("unknown Supertonic asset: " + str(relative))
    return (
        "https://huggingface.co/" + MODEL_REPO + "/resolve/" + MODEL_REVISION
        + "/" + relative
    )


def asset_path_for_url(url: str) -> str:
    """Map one configured immutable asset URL back to its install-relative path."""
    for relative in _MODEL_ASSETS:
        if url == asset_url_for_path(relative):
            return relative
    raise ValueError("unknown Supertonic asset URL")


def _worker_python() -> Optional[Path]:
    configured = os.environ.get(_WORKER_PYTHON_ENV)
    if not configured:
        return None
    candidate = Path(configured).expanduser()
    return candidate.resolve() if candidate.is_file() else None


def _worker_source() -> Optional[Path]:
    candidates = []
    configured = os.environ.get(_WORKER_DIRECTORY_ENV)
    if configured:
        candidates.append(Path(configured).expanduser())
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        candidates.append(Path(frozen_root) / "supertonic_worker")
    for candidate in candidates:
        if candidate.is_dir():
            resolved = candidate.resolve()
            if (resolved / "SupertonicWorker.exe").is_file():
                return resolved
    return None


def inspect_supertonic3_installation(root: Optional[Path] = None):
    """Verify the model and runtime using the shared worker asset inspector."""
    from piper.supertonic_assets import inspect_supertonic3_installation as inspect

    return inspect(Path(root) if root is not None else installation_root())


def supertonic3_installed(*, install_root: Optional[Path] = None) -> bool:
    """Check for a complete local model and usable worker without network access."""
    try:
        inspect_supertonic3_installation(install_root)
    except (OSError, ValueError, KeyError, AttributeError, TypeError):
        return False
    return True


def _head_size(relative: str, cancel_event: threading.Event) -> Optional[int]:
    if cancel_event.is_set():
        raise DownloadCancelled("Download cancelled")
    request = Request(asset_url_for_path(relative), method="HEAD")
    try:
        with urlopen(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
            value = response.headers.get("Content-Length")
    except Exception as error:
        raise SupertonicInstallError(
            f"Could not check the size of Supertonic file {relative}: {error}"
        ) from error
    try:
        size = int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    return size if size is not None and size > 0 else None


def _copy_worker_tree(
    source: Path,
    target: Path,
    cancel_event: threading.Event,
    progress: Callable[[int, int, str], None],
    completed: int,
    total: int,
) -> int:
    resolved_source = source.resolve()
    for path in sorted(resolved_source.rglob("*")):
        if cancel_event.is_set():
            raise DownloadCancelled("Download cancelled")
        if path.is_symlink():
            raise SupertonicInstallError("Supertonic worker runtime contains a symbolic link")
        if not path.is_file():
            continue
        relative = path.relative_to(resolved_source).as_posix()
        destination = target / "worker" / Path(*relative.split("/"))
        destination.parent.mkdir(parents=True, exist_ok=True)
        with path.open("rb") as source_stream, destination.open("xb") as output:
            while True:
                if cancel_event.is_set():
                    raise DownloadCancelled("Download cancelled")
                block = source_stream.read(READ_BLOCK_BYTES)
                if not block:
                    break
                output.write(block)
                completed += len(block)
                progress(completed, total, "worker/" + relative)
    if not (target / WORKER_EXE).is_file():
        raise SupertonicInstallError(
            "Supertonic worker runtime is missing SupertonicWorker.exe"
        )
    return completed


def _download_asset(
    relative: str,
    destination: Path,
    cancel_event: threading.Event,
    progress: Callable[[int, int, str], None],
    completed: int,
    total: int,
    expected_size: Optional[int],
) -> int:
    if cancel_event.is_set():
        raise DownloadCancelled("Download cancelled")
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = Request(asset_url_for_path(relative))
    received = 0
    try:
        with urlopen(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
            response_size = response.headers.get("Content-Length")
            if response_size is not None:
                try:
                    response_size = int(response_size)
                except (TypeError, ValueError):
                    response_size = None
            with destination.open("xb") as output:
                while True:
                    if cancel_event.is_set():
                        raise DownloadCancelled("Download cancelled")
                    block = response.read(READ_BLOCK_BYTES)
                    if not block:
                        break
                    if not isinstance(block, bytes):
                        raise SupertonicInstallError(
                            f"Invalid response stream for Supertonic file {relative}"
                        )
                    received += len(block)
                    if expected_size is not None and received > expected_size:
                        raise SupertonicInstallError(
                            f"Supertonic file {relative} exceeds its advertised size"
                        )
                    output.write(block)
                    completed += len(block)
                    progress(completed, total, relative)
    except (DownloadCancelled, SupertonicInstallError):
        raise
    except Exception as error:
        raise SupertonicInstallError(
            f"Failed to download Supertonic file {relative}: {error}"
        ) from error
    final_size = expected_size if expected_size is not None else response_size
    if final_size is not None and received != final_size:
        raise SupertonicInstallError(
            f"Supertonic file {relative} size mismatch: expected {final_size} bytes, "
            f"received {received}"
        )
    return completed


def _write_manifest(root: Path, cancel_event: threading.Event) -> None:
    files = {}
    for path in sorted(root.rglob("*")):
        if cancel_event.is_set():
            raise DownloadCancelled("Download cancelled")
        if path.is_file() and path != root / MANIFEST_NAME:
            relative = path.relative_to(root).as_posix()
            if not relative.startswith("worker/") and relative not in _MODEL_ASSETS:
                raise SupertonicInstallError("Unexpected file in Supertonic staging area")
            files[relative] = file_sha256(path)
    if not set(_MODEL_ASSETS) <= set(files):
        raise SupertonicInstallError("Supertonic model files are incomplete")
    if _worker_source() is not None and WORKER_EXE not in files:
        raise SupertonicInstallError("Supertonic worker runtime was not staged")
    if WORKER_EXE not in files and _worker_python() is None:
        raise SupertonicInstallError(
            "Supertonic worker runtime is unavailable. Restart Piper after its worker "
            "runtime has been installed."
        )
    manifest = {
        "manifest_version": _MANIFEST_VERSION,
        "engine": ENGINE,
        "model_repo": MODEL_REPO,
        "model_revision": MODEL_REVISION,
        "source_repo": SOURCE_REPO,
        "source_revision": SOURCE_REVISION,
        "files": files,
    }
    (root / MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _activate(staging: Path, root: Path) -> Path:
    backup = root.with_name(root.name + ".backup-" + uuid.uuid4().hex)
    had_previous = root.exists()
    if had_previous:
        os.replace(root, backup)
    try:
        os.replace(staging, root)
    except Exception:
        if had_previous and backup.exists():
            os.replace(backup, root)
        raise
    if had_previous:
        shutil.rmtree(backup, ignore_errors=True)
    return root.resolve()


def install_supertonic3(
    progress: Callable[[int, int, str], None],
    cancel_event: threading.Event,
    *,
    install_root: Optional[Path] = None,
) -> Path:
    """Download, validate, and atomically install the pinned Supertonic 3 payload."""
    root = Path(install_root) if install_root is not None else installation_root()
    root = root.resolve()
    while not _INSTALL_LOCK.acquire(timeout=0.1):
        if cancel_event.is_set():
            raise DownloadCancelled("Download cancelled")
    if cancel_event.is_set():
        _INSTALL_LOCK.release()
        raise DownloadCancelled("Download cancelled")

    staging = None
    try:
        if supertonic3_installed(install_root=root):
            return root

        worker_source = _worker_source()
        if worker_source is None and _worker_python() is None:
            raise SupertonicInstallError(
                "Supertonic 3 worker runtime is unavailable. Rebuild or reinstall Piper "
                "with its Supertonic worker."
            )

        root.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=root.name + ".staging-", dir=root.parent))
        sizes = {
            relative: _head_size(relative, cancel_event) for relative in _MODEL_ASSETS
        }
        total = (
            sum(sizes.values())
            if all(size is not None for size in sizes.values())
            else 0
        )
        worker_bytes = 0
        if worker_source is not None:
            worker_bytes = sum(
                path.stat().st_size for path in worker_source.rglob("*")
                if path.is_file() and not path.is_symlink()
            )
        if total:
            total += worker_bytes
        completed = 0
        for relative in _MODEL_ASSETS:
            completed = _download_asset(
                relative,
                staging / Path(*relative.split("/")),
                cancel_event,
                progress,
                completed,
                total,
                sizes[relative],
            )
        if worker_source is not None:
            completed = _copy_worker_tree(
                worker_source, staging, cancel_event, progress, completed, total
            )
        if cancel_event.is_set():
            raise DownloadCancelled("Download cancelled")
        _write_manifest(staging, cancel_event)
        try:
            inspect_supertonic3_installation(staging)
        except (OSError, ValueError, KeyError, AttributeError, TypeError) as error:
            raise SupertonicInstallError(
                f"Downloaded Supertonic 3 files failed validation: {error}"
            ) from error
        if cancel_event.is_set():
            raise DownloadCancelled("Download cancelled")
        installed = _activate(staging, root)
        staging = None
        return installed
    except (DownloadCancelled, SupertonicInstallError):
        raise
    except Exception as error:
        raise SupertonicInstallError(f"Could not install Supertonic 3: {error}") from error
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
        _INSTALL_LOCK.release()
