"""Verification and local path resolution for the bundled Kokoro payload."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Dict


DEFAULT_KOKORO_VOICE = "af_heart"


@dataclass(frozen=True)
class KokoroVoiceAsset:
    voice_id: str
    path: Path
    language: str


@dataclass(frozen=True)
class KokoroInstallation:
    root: Path
    worker_executable: Path
    config_path: Path
    model_path: Path
    voices: Dict[str, KokoroVoiceAsset]
    worker_version: str
    kokoro_version: str
    manifest_sha256: str


def _local_path(root: Path, relative: object) -> Path:
    if not isinstance(relative, str) or not relative:
        raise ValueError("manifest path must be a non-empty string")
    root = root.resolve()
    candidate = (root / relative).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("manifest path escapes install root")
    return candidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _normalized_relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _require_hashed_file(root: Path, files: Dict[str, object], relative: object) -> Path:
    path = _local_path(root, relative)
    normalized = _normalized_relative(root, path)
    if normalized not in files:
        raise ValueError("Kokoro critical file is not hashed: %s" % normalized)
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def verify_kokoro_installation(root: Path) -> KokoroInstallation:
    root = root.resolve()
    manifest_path = root / "manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    if manifest.get("manifest_version") != 1:
        raise ValueError("unsupported Kokoro manifest version")

    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("Kokoro manifest has no files")
    normalized_files = {}
    for relative, expected_hash in files.items():
        path = _local_path(root, relative)
        normalized = _normalized_relative(root, path)
        normalized_files[normalized] = expected_hash
        if not path.is_file():
            raise FileNotFoundError(path)
        if not isinstance(expected_hash, str) or _sha256(path) != expected_hash.lower():
            raise ValueError("Kokoro asset hash mismatch")

    worker_data = manifest.get("worker")
    model = manifest.get("model")
    voices_data = manifest.get("voices")
    groups = manifest.get("required_groups")
    if not isinstance(worker_data, dict):
        raise ValueError("Kokoro manifest worker entry is invalid")
    if not isinstance(model, dict) or not isinstance(voices_data, dict):
        raise ValueError("Kokoro manifest model/voices are invalid")
    if not isinstance(groups, dict):
        raise ValueError("Kokoro manifest required groups are invalid")

    worker = _require_hashed_file(root, normalized_files, worker_data.get("executable"))
    config_path = _require_hashed_file(root, normalized_files, model.get("config"))
    model_path = _require_hashed_file(root, normalized_files, model.get("weights"))

    voices = {}
    for voice_id, metadata in voices_data.items():
        if not isinstance(voice_id, str) or not isinstance(metadata, dict):
            raise ValueError("invalid Kokoro voice catalog entry")
        voice_path = _require_hashed_file(root, normalized_files, metadata.get("path"))
        language = metadata.get("language")
        if not isinstance(language, str) or not language:
            raise ValueError("invalid Kokoro voice catalog entry")
        voices[voice_id] = KokoroVoiceAsset(voice_id, voice_path, language)

    if DEFAULT_KOKORO_VOICE not in voices:
        raise ValueError("default Kokoro voice is missing")

    for key in ("spacy", "misaki_data", "espeak_ng"):
        prefix = groups.get(key)
        if not isinstance(prefix, str):
            raise ValueError("Kokoro required resource group is invalid")
        group_root = _local_path(root, prefix)
        if not group_root.is_dir():
            raise ValueError("Kokoro required resource group is not a directory")
        normalized_prefix = _normalized_relative(root, group_root)
        if not any(
            relative == normalized_prefix
            or relative.startswith(normalized_prefix.rstrip("/") + "/")
            for relative in normalized_files
        ):
            raise ValueError("Kokoro required resource group is missing")

    actual_files = {
        _normalized_relative(root, path)
        for path in root.rglob("*")
        if path.is_file() and path != manifest_path
    }
    if set(normalized_files) != actual_files:
        raise ValueError("Kokoro manifest does not hash every payload file")

    return KokoroInstallation(
        root=root,
        worker_executable=worker,
        config_path=config_path,
        model_path=model_path,
        voices=voices,
        worker_version=str(manifest.get("worker_version", "")),
        kokoro_version=str(manifest.get("kokoro_version", "")),
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
    )
