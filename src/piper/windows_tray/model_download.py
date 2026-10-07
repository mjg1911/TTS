"""On-demand, verified installation of optional Chatterbox model payloads."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import threading
import uuid
import zipfile
from typing import Callable, Iterable, Optional
from urllib.request import urlopen

from piper import nano_assets, turbo_assets


CATALOG_PATH = Path(__file__).resolve().parents[1] / "model_catalog.json"
MAX_PART_BYTES = 1_900_000_000
READ_BLOCK_BYTES = 1024 * 1024
DOWNLOAD_TIMEOUT_SECONDS = 30
_GENERATION_POINTER = "current.json"
_INSTALL_LOCK = threading.Lock()
_CACHE_LOCK = threading.Lock()
_RECORD_LOCK = threading.Lock()
_INSTALLATION_CACHE = {}
_INSTALL_RECORD_NAME = "installed-engines.json"
_ENGINE_DISPLAY_NAMES = {
    "nano": "Chatterbox Nano",
    "turbo": turbo_assets.ENGINE,
}


class ModelDownloadError(RuntimeError):
    """A catalog, download, or local installation could not be completed."""


class DownloadCancelled(ModelDownloadError):
    """The user cancelled an optional model download."""


def _normalize_engine(engine: str) -> str:
    if engine in ("nano", _ENGINE_DISPLAY_NAMES["nano"]):
        return "nano"
    if engine in ("turbo", _ENGINE_DISPLAY_NAMES["turbo"]):
        return "turbo"
    raise ValueError("engine must be Chatterbox Nano or Chatterbox Turbo (350M)")


def _default_install_root() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "Piper" / "Chatterbox"
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        return Path(local_appdata) / "Piper" / "Chatterbox"
    return Path.home() / ".piper" / "Chatterbox"


def installation_root() -> Path:
    """Return the shared persistent payload root used by the tray app."""
    return _default_install_root()


def _read_install_record(record_path: Path) -> set[str]:
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return set()
    if not isinstance(record, dict) or record.get("version") != 1:
        return set()
    values = record.get("engines")
    if not isinstance(values, list):
        return set()
    normalized = set()
    for value in values:
        if not isinstance(value, str):
            continue
        try:
            normalized.add(_normalize_engine(value))
        except ValueError:
            continue
    return normalized


def recorded_engines(*, install_root: Optional[Path] = None) -> frozenset[str]:
    """Return engine IDs saved after a successful check or installation.

    Reading this record is deliberately cheap and does not inspect model files.
    """
    root = Path(install_root) if install_root is not None else _default_install_root()
    with _RECORD_LOCK:
        return frozenset(_read_install_record(root / _INSTALL_RECORD_NAME))


def _record_installed_engine(engine: str, install_root: Optional[Path]) -> None:
    """Persist a verified engine so later launches do not probe it again."""
    normalized = _normalize_engine(engine)
    root = Path(install_root) if install_root is not None else _default_install_root()
    record_path = root / _INSTALL_RECORD_NAME
    try:
        with _RECORD_LOCK:
            engines = _read_install_record(record_path)
            if normalized in engines:
                return
            engines.add(normalized)
            root.mkdir(parents=True, exist_ok=True)
            temporary_path = root / f"{_INSTALL_RECORD_NAME}.{uuid.uuid4().hex}.tmp"
            try:
                temporary_path.write_text(
                    json.dumps({"version": 1, "engines": sorted(engines)}, indent=2)
                    + "\n",
                    encoding="utf-8",
                )
                os.replace(temporary_path, record_path)
            finally:
                temporary_path.unlink(missing_ok=True)
    except OSError:
        # Installation remains usable if the optional UI cache cannot be saved.
        return


def active_generation_root(install_root: Optional[Path] = None) -> Optional[Path]:
    """Return the locally selected immutable generation, if its pointer is valid."""
    root = Path(install_root) if install_root is not None else _default_install_root()
    pointer = root / _GENERATION_POINTER
    try:
        value = json.loads(pointer.read_text(encoding="utf-8"))
        relative = value.get("generation") if isinstance(value, dict) else None
        if value.get("version") != 1 or not isinstance(relative, str):
            return None
        if not re.fullmatch(r"generations/[0-9a-f]{32}", relative):
            return None
        generation = root / relative
        generation.resolve().relative_to((root / "generations").resolve())
        return generation.resolve() if generation.is_dir() else None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, AttributeError):
        return None


def _catalog_path(catalog_path: Optional[Path]) -> Path:
    return Path(catalog_path) if catalog_path is not None else CATALOG_PATH


def load_catalog(catalog_path: Optional[Path] = None) -> dict:
    """Load and validate the versioned catalog without opening a network connection."""
    path = _catalog_path(catalog_path)
    try:
        catalog = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ModelDownloadError(
            "Download assets are not configured: catalog is unavailable"
        ) from error
    if (not isinstance(catalog, dict) or catalog.get("version") != 1
            or catalog.get("release") != "v1.10.0"):
        raise ModelDownloadError("Download assets are not configured: unsupported catalog")
    components = catalog.get("components")
    if not isinstance(components, dict) or set(components) != {"worker", "nano", "turbo"}:
        raise ModelDownloadError(
            "Download assets are not configured: catalog components are incomplete"
        )
    for name, component in components.items():
        if not isinstance(component, dict) or not isinstance(component.get("parts"), list):
            raise ModelDownloadError(f"Download assets are not configured for {name}")
    return catalog


def _component_parts(catalog: dict, component: str) -> list[dict]:
    parts = catalog["components"][component]["parts"]
    if not parts:
        raise ModelDownloadError(f"Download assets are not configured for {component}")
    checked = []
    for index, part in enumerate(parts, start=1):
        if not isinstance(part, dict):
            raise ModelDownloadError(f"Invalid {component} asset part {index}")
        url, size, digest = part.get("url"), part.get("size"), part.get("sha256")
        if (not isinstance(url, str) or not url.startswith("https://")
                or not isinstance(size, int) or isinstance(size, bool)
                or size <= 0 or size > MAX_PART_BYTES
                or not isinstance(digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", digest)):
            raise ModelDownloadError(f"Invalid {component} asset metadata for part {index}")
        checked.append({"url": url, "size": size, "sha256": digest})
    return checked


def _cache_key(engine: str, install_root: Optional[Path]) -> tuple[str, str]:
    root = Path(install_root) if install_root is not None else _default_install_root()
    return engine, str(root.resolve())


def invalidate_installation_cache(
    engine: Optional[str] = None, install_root: Optional[Path] = None
) -> None:
    """Forget cached readiness after an installer changes the active pointer."""
    normalized = _normalize_engine(engine) if engine is not None else None
    root_key = str(Path(install_root).resolve()) if install_root is not None else None
    with _CACHE_LOCK:
        for key in list(_INSTALLATION_CACHE):
            if (normalized is None or key[0] == normalized) and (
                root_key is None or key[1] == root_key
            ):
                del _INSTALLATION_CACHE[key]


def _shared_roots(install_root: Optional[Path]) -> Iterable[Path]:
    if install_root is not None:
        root = Path(install_root)
        active = active_generation_root(root)
        if active is not None:
            yield active
        if (root / "manifest.json").is_file():
            yield root
        return

    root = _default_install_root()
    active = active_generation_root(root)
    if active is not None:
        yield active
    if (root / "manifest.json").is_file():
        yield root
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        bundled = Path(frozen_root) / "chatterbox_payload"
        if bundled.is_dir():
            yield bundled


def _legacy_engine_roots(engine: str, install_root: Optional[Path]) -> Iterable[Path]:
    if install_root is not None:
        return
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        bundled = Path(frozen_root) / f"{engine}_payload"
        if bundled.is_dir():
            yield bundled
    dirname = "ChatterboxNano" if engine == "nano" else "ChatterboxTurbo"
    legacy = _default_install_root().parent / dirname
    if legacy.is_dir():
        yield legacy


def _inspect_shared(root: Path, engine: str):
    from piper.chatterbox_assets import inspect_chatterbox_installation

    return inspect_chatterbox_installation(root, engine)


def _inspect_legacy(root: Path, engine: str):
    if engine == "nano":
        return nano_assets.inspect_nano_installation(root)
    return turbo_assets.inspect_turbo_installation(root)


def _find_installation(engine: str, install_root: Optional[Path]) -> Optional[Path]:
    seen = set()
    for root in _shared_roots(install_root):
        key = str(root.resolve())
        if key in seen:
            continue
        seen.add(key)
        try:
            _inspect_shared(root, engine)
            return root.resolve()
        except (OSError, ValueError, KeyError, AttributeError, TypeError):
            continue
    for root in _legacy_engine_roots(engine, install_root):
        key = str(root.resolve())
        if key in seen:
            continue
        seen.add(key)
        try:
            _inspect_legacy(root, engine)
            return root.resolve()
        except (OSError, ValueError, KeyError, AttributeError, TypeError):
            continue
    return None


def engine_installed(
    engine: str,
    *,
    catalog_path: Optional[Path] = None,
    install_root: Optional[Path] = None,
) -> bool:
    """Inspect local files once per engine/root and cache readiness for UI polling."""
    normalized = _normalize_engine(engine)
    key = _cache_key(normalized, install_root)
    with _CACHE_LOCK:
        if key not in _INSTALLATION_CACHE:
            _INSTALLATION_CACHE[key] = _find_installation(normalized, install_root)
        installed = _INSTALLATION_CACHE[key] is not None
    if installed:
        _record_installed_engine(normalized, install_root)
    return installed


def _cached_installation(engine: str, install_root: Optional[Path]) -> Optional[Path]:
    key = _cache_key(engine, install_root)
    with _CACHE_LOCK:
        if key in _INSTALLATION_CACHE:
            return _INSTALLATION_CACHE[key]
    found = _find_installation(engine, install_root)
    with _CACHE_LOCK:
        return _INSTALLATION_CACHE.setdefault(key, found)


def _valid_shared_source(install_root: Path) -> Optional[Path]:
    for root in _shared_roots(install_root):
        try:
            _inspect_shared(root, "nano")
            return root.resolve()
        except (OSError, ValueError, KeyError, AttributeError, TypeError):
            pass
        try:
            _inspect_shared(root, "turbo")
            return root.resolve()
        except (OSError, ValueError, KeyError, AttributeError, TypeError):
            pass
    if install_root == _default_install_root():
        frozen_root = getattr(sys, "_MEIPASS", None)
        if frozen_root:
            bundled = Path(frozen_root) / "chatterbox_payload"
            try:
                _inspect_shared(bundled, "nano")
                return bundled.resolve()
            except (OSError, ValueError, KeyError, AttributeError, TypeError):
                try:
                    _inspect_shared(bundled, "turbo")
                    return bundled.resolve()
                except (OSError, ValueError, KeyError, AttributeError, TypeError):
                    pass
    return None


def _copy_payload(source: Path, target: Path, cancel_event: threading.Event) -> None:
    """Copy an already validated payload, hard-linking immutable large files when possible."""
    for path in source.rglob("*"):
        if cancel_event.is_set():
            raise DownloadCancelled("Download cancelled")
        if not path.is_file() or path.name == "manifest.json" and path.parent == source:
            continue
        relative = path.relative_to(source)
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(path, destination)
        except OSError:
            with path.open("rb") as source_stream, destination.open("xb") as target_stream:
                while True:
                    if cancel_event.is_set():
                        raise DownloadCancelled("Download cancelled")
                    block = source_stream.read(READ_BLOCK_BYTES)
                    if not block:
                        break
                    target_stream.write(block)


def _download_parts(
    component: str,
    parts: list[dict],
    archive_path: Path,
    cancel_event: threading.Event,
    progress: Callable[[int, int, str], None],
    completed_before: int,
    total_bytes: int,
) -> int:
    completed = completed_before
    with archive_path.open("wb") as archive:
        for part_number, part in enumerate(parts, start=1):
            if cancel_event.is_set():
                raise DownloadCancelled("Download cancelled")
            digest = hashlib.sha256()
            received = 0
            try:
                response = urlopen(part["url"], timeout=DOWNLOAD_TIMEOUT_SECONDS)
                with response:
                    while True:
                        if cancel_event.is_set():
                            raise DownloadCancelled("Download cancelled")
                        block = response.read(READ_BLOCK_BYTES)
                        if not block:
                            break
                        if not isinstance(block, bytes):
                            raise ModelDownloadError(f"Invalid response stream for {component}")
                        received += len(block)
                        if received > part["size"]:
                            raise ModelDownloadError(
                                f"{component} part {part_number} exceeds its catalog size"
                            )
                        digest.update(block)
                        archive.write(block)
                        completed += len(block)
                        progress(completed, total_bytes, component)
            except (DownloadCancelled, ModelDownloadError):
                raise
            except Exception as error:
                raise ModelDownloadError(f"Failed to download {component}: {error}") from error
            if received != part["size"]:
                raise ModelDownloadError(
                    f"{component} part {part_number} size mismatch: expected "
                    f"{part['size']} bytes, received {received}"
                )
            if digest.hexdigest() != part["sha256"]:
                raise ModelDownloadError(f"{component} part {part_number} SHA-256 mismatch")
    return completed


def _safe_archive_name(name: str, component: str, engine: str) -> tuple[str, bool]:
    if (not isinstance(name, str) or not name or "\\" in name or "\x00" in name
            or name.startswith("/") or ":" in name):
        raise ModelDownloadError(f"Unsafe {component} archive path")
    is_directory = name.endswith("/")
    normalized = name[:-1] if is_directory else name
    parts = normalized.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ModelDownloadError(f"Unsafe {component} archive path: {name}")
    expected_prefix = "worker" if component == "worker" else f"models/{engine}"
    prefix_parts = expected_prefix.split("/")
    if (len(parts) < len(prefix_parts) + (0 if is_directory else 1)
            or "/".join(parts[: len(prefix_parts)]) != expected_prefix):
        raise ModelDownloadError(f"Unexpected {component} archive path: {name}")
    return normalized, is_directory


def _extract_component(
    archive_path: Path,
    target: Path,
    component: str,
    engine: str,
    cancel_event: threading.Event,
) -> None:
    names = set()
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            for info in archive.infolist():
                if cancel_event.is_set():
                    raise DownloadCancelled("Download cancelled")
                relative, is_directory = _safe_archive_name(info.filename, component, engine)
                folded = relative.casefold()
                if folded in names:
                    raise ModelDownloadError(f"Duplicate {component} archive path: {relative}")
                names.add(folded)
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise ModelDownloadError(f"Unsafe symbolic link in {component} archive")
                destination = target.joinpath(*relative.split("/"))
                destination.resolve().relative_to(target.resolve())
                if is_directory:
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info, "r") as source, destination.open("xb") as output:
                    while True:
                        if cancel_event.is_set():
                            raise DownloadCancelled("Download cancelled")
                        block = source.read(READ_BLOCK_BYTES)
                        if not block:
                            break
                        output.write(block)
    except DownloadCancelled:
        raise
    except ModelDownloadError:
        raise
    except (OSError, zipfile.BadZipFile, RuntimeError, ValueError) as error:
        raise ModelDownloadError(f"Invalid {component} ZIP archive: {error}") from error


def _model_declaration(engine: str) -> dict[str, str]:
    assets = nano_assets if engine == "nano" else turbo_assets
    return {"model_revision": assets.MODEL_REVISION, "model_repo": assets.MODEL_REPO}


def _write_manifest(
    generation: Path, engines: set[str], cancel_event: threading.Event
) -> None:
    files = {}
    for path in sorted(generation.rglob("*")):
        if cancel_event.is_set():
            raise DownloadCancelled("Download cancelled")
        if path.is_file() and path != generation / "manifest.json":
            relative = path.relative_to(generation).as_posix()
            digest = hashlib.sha256()
            with path.open("rb") as source:
                while True:
                    if cancel_event.is_set():
                        raise DownloadCancelled("Download cancelled")
                    block = source.read(READ_BLOCK_BYTES)
                    if not block:
                        break
                    digest.update(block)
            files[relative] = digest.hexdigest()
    manifest = {
        "manifest_version": 2,
        "runtime": "Chatterbox",
        "source_revision": nano_assets.SOURCE_REVISION,
        "models": {engine: _model_declaration(engine) for engine in sorted(engines)},
        "files": files,
    }
    (generation / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _activate_generation(staging: Path, install_root: Path) -> Path:
    generation_id = uuid.uuid4().hex
    generations = install_root / "generations"
    generations.mkdir(parents=True, exist_ok=True)
    destination = generations / generation_id
    os.replace(staging, destination)
    pointer_tmp = install_root / f"{_GENERATION_POINTER}.{uuid.uuid4().hex}.tmp"
    try:
        pointer_tmp.write_text(
            json.dumps({"version": 1, "generation": f"generations/{generation_id}"}) + "\n",
            encoding="utf-8",
        )
        os.replace(pointer_tmp, install_root / _GENERATION_POINTER)
    except Exception:
        pointer_tmp.unlink(missing_ok=True)
        shutil.rmtree(destination, ignore_errors=True)
        raise
    return destination.resolve()


def _acquire_install_lock(cancel_event: threading.Event) -> None:
    while not _INSTALL_LOCK.acquire(timeout=0.1):
        if cancel_event.is_set():
            raise DownloadCancelled("Download cancelled")
    if cancel_event.is_set():
        _INSTALL_LOCK.release()
        raise DownloadCancelled("Download cancelled")


def download_engine(
    engine: str,
    progress: Callable[[int, int, str], None],
    cancel_event: threading.Event,
    *,
    catalog_path: Optional[Path] = None,
    install_root: Optional[Path] = None,
) -> Path:
    """Download, verify, and atomically activate a Nano or Turbo payload generation."""
    normalized = _normalize_engine(engine)
    root = Path(install_root) if install_root is not None else _default_install_root()
    _acquire_install_lock(cancel_event)
    staging = None
    generation = None
    archive_paths = []
    try:
        existing = _cached_installation(normalized, install_root)
        if existing is not None:
            _record_installed_engine(normalized, root)
            return existing

        catalog = load_catalog(catalog_path)
        source = _valid_shared_source(root)
        model_parts = _component_parts(catalog, normalized)
        worker_parts = [] if source is not None else _component_parts(catalog, "worker")
        total_bytes = sum(part["size"] for part in worker_parts + model_parts)
        root.mkdir(parents=True, exist_ok=True)
        staging_root = root / ".staging"
        staging_root.mkdir(parents=True, exist_ok=True)
        staging = staging_root / uuid.uuid4().hex
        staging.mkdir()

        engines = set()
        if source is not None:
            _copy_payload(source, staging, cancel_event)
            source_manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
            engines.update(source_manifest["models"])

        completed = 0
        if worker_parts:
            archive_path = staging_root / f"{staging.name}-worker.zip"
            archive_paths.append(archive_path)
            completed = _download_parts(
                "worker", worker_parts, archive_path, cancel_event, progress, completed, total_bytes
            )
            _extract_component(archive_path, staging, "worker", normalized, cancel_event)

        model_archive = staging_root / f"{staging.name}-{normalized}.zip"
        archive_paths.append(model_archive)
        _download_parts(
            normalized,
            model_parts,
            model_archive,
            cancel_event,
            progress,
            completed,
            total_bytes,
        )
        _extract_component(model_archive, staging, normalized, normalized, cancel_event)
        engines.add(normalized)

        if cancel_event.is_set():
            raise DownloadCancelled("Download cancelled")
        _write_manifest(staging, engines, cancel_event)
        try:
            _inspect_shared(staging, normalized)
        except (OSError, ValueError, KeyError) as error:
            raise ModelDownloadError(
                f"Downloaded {normalized} payload failed validation: {error}"
            ) from error
        if cancel_event.is_set():
            raise DownloadCancelled("Download cancelled")
        generation = _activate_generation(staging, root)
        staging = None
        invalidate_installation_cache(install_root=root)
        with _CACHE_LOCK:
            _INSTALLATION_CACHE[_cache_key(normalized, root)] = generation
        _record_installed_engine(normalized, root)
        return generation
    except DownloadCancelled:
        raise
    except ModelDownloadError:
        raise
    except Exception as error:
        raise ModelDownloadError(f"Could not install {normalized}: {error}") from error
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
        for archive in archive_paths:
            archive.unlink(missing_ok=True)
        _INSTALL_LOCK.release()
