"""Integrity checks for the shared Nano and Turbo Chatterbox payload."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

from piper import nano_assets, turbo_assets


_ENGINE_NAMES = ("nano", "turbo")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ChatterboxEngineUnavailable(ValueError):
    """The shared payload does not contain the requested engine's model."""


@dataclass(frozen=True)
class ChatterboxInstallation:
    root: Path
    worker_executable: Path
    model_dir: Path
    manifest_sha256: str
    engine: str


class _DuplicateKeyError(ValueError):
    """Raised when a JSON object repeats a key."""


def _object_without_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError(key)
        result[key] = value
    return result


def _read_manifest(raw):
    try:
        return json.loads(raw, object_pairs_hook=_object_without_duplicate_keys)
    except _DuplicateKeyError as error:
        raise ValueError("duplicate Chatterbox manifest key: " + str(error)) from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("invalid Chatterbox manifest") from error


def _model_pin(engine):
    if engine == "nano":
        return {
            "model_revision": nano_assets.MODEL_REVISION,
            "model_repo": nano_assets.MODEL_REPO,
            "required_files": nano_assets.REQUIRED_MODEL_FILES,
            "file_sha256": nano_assets.MODEL_FILE_SHA256,
        }
    return {
        "model_revision": turbo_assets.MODEL_REVISION,
        "model_repo": turbo_assets.MODEL_REPO,
        "required_files": turbo_assets.REQUIRED_MODEL_FILES,
        "file_sha256": turbo_assets.MODEL_FILE_SHA256,
    }


def _normalize_asset_path(root, relative):
    if (not isinstance(relative, str) or not relative or "\\" in relative
            or "\x00" in relative or relative.startswith("/")
            or re.match(r"^[A-Za-z]:", relative)):
        raise ValueError("invalid Chatterbox asset path")
    parts = relative.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError("invalid Chatterbox asset path")
    if relative == "manifest.json":
        raise ValueError("manifest cannot list itself as a Chatterbox asset")
    path = root.joinpath(*parts)
    try:
        path.resolve().relative_to(root)
    except ValueError as error:
        raise ValueError("Chatterbox asset path escapes root") from error
    return path, relative


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inspect_chatterbox_installation(root, engine):
    """Validate a shared Chatterbox payload and select its Nano or Turbo model."""
    if engine not in _ENGINE_NAMES:
        raise ValueError("unsupported Chatterbox engine")

    root = Path(root).resolve()
    raw_manifest = (root / "manifest.json").read_bytes()
    manifest = _read_manifest(raw_manifest)
    if not isinstance(manifest, dict):
        raise ValueError("invalid Chatterbox manifest")
    if manifest.get("manifest_version") != 2 or manifest.get("runtime") != "Chatterbox":
        raise ValueError("unsupported shared Chatterbox manifest")
    if (nano_assets.SOURCE_REVISION != turbo_assets.SOURCE_REVISION
            or manifest.get("source_revision") != nano_assets.SOURCE_REVISION):
        raise ValueError("incompatible Chatterbox source revision")

    models = manifest.get("models")
    if (not isinstance(models, dict) or not 1 <= len(models) <= 2
            or not set(models) <= set(_ENGINE_NAMES)):
        raise ValueError("invalid Chatterbox model declarations")
    if engine not in models:
        raise ChatterboxEngineUnavailable("selected engine is absent from Chatterbox payload")

    required = {"worker/ChatterboxWorker.exe"}
    for declared_engine, metadata in models.items():
        pin = _model_pin(declared_engine)
        if (not isinstance(metadata, dict)
                or set(metadata) != {"model_revision", "model_repo"}
                or metadata.get("model_revision") != pin["model_revision"]
                or metadata.get("model_repo") != pin["model_repo"]):
            raise ValueError("incompatible Chatterbox model pin: " + declared_engine)
        if (set(pin["file_sha256"]) != set(pin["required_files"])
                or not pin["required_files"]):
            raise ValueError("incomplete pinned model inventory: " + declared_engine)
        required.update(
            f"models/{declared_engine}/{name}" for name in pin["required_files"]
        )

    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("Chatterbox manifest has no files")
    normalized = set()
    folded = set()
    observed_hashes = {}
    for relative, expected in files.items():
        path, name = _normalize_asset_path(root, relative)
        key = name.casefold()
        if key in folded:
            raise ValueError("duplicate Chatterbox asset path: " + name)
        folded.add(key)
        normalized.add(name)
        if (not isinstance(expected, str) or not _SHA256_RE.fullmatch(expected)
                or not path.is_file()):
            raise ValueError("Chatterbox asset hash mismatch: " + name)
        actual_hash = file_sha256(path)
        if actual_hash != expected:
            raise ValueError("Chatterbox asset hash mismatch: " + name)
        observed_hashes[name] = actual_hash
        parts = name.split("/")
        if parts[0] == "models":
            if len(parts) < 3 or parts[1] not in models:
                raise ValueError("undeclared Chatterbox model asset: " + name)

    if not required <= normalized:
        raise ValueError("required Chatterbox assets missing from manifest")

    for declared_engine in models:
        pin = _model_pin(declared_engine)
        for name, expected in pin["file_sha256"].items():
            relative = f"models/{declared_engine}/{name}"
            if observed_hashes.get(relative) != expected:
                raise ValueError("pinned model hash mismatch: " + declared_engine + "/" + name)

    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path != root / "manifest.json"
    }
    if normalized != actual:
        raise ValueError("Chatterbox payload inventory differs from manifest")

    return ChatterboxInstallation(
        root=root,
        worker_executable=root / "worker" / "ChatterboxWorker.exe",
        model_dir=root / "models" / engine,
        manifest_sha256=hashlib.sha256(raw_manifest).hexdigest(),
        engine=engine,
    )
