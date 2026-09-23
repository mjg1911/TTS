import hashlib
import json
from pathlib import Path

import pytest

from piper.kokoro_assets import (
    DEFAULT_KOKORO_VOICE,
    inspect_kokoro_installation,
    verify_kokoro_installation,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_installation(root: Path):
    contents = {
        "worker/KokoroWorker.exe": b"worker",
        "worker/_internal/en_core_web_sm/meta.json": b"spacy",
        "worker/_internal/misaki/data/us_gold.json": b"misaki",
        "worker/_internal/espeakng_loader/espeak-ng.exe": b"espeak",
        "model/config.json": b"{}",
        "model/kokoro-v1_0.pth": b"model",
        "voices/af_heart.pt": b"voice",
    }
    for relative, data in contents.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    manifest = {
        "manifest_version": 1,
        "worker_version": "1",
        "kokoro_version": "0.9.4",
        "model_revision": "c3327e9bac3dbe55779397bfa82de0f8806fb3bc",
        "worker": {"executable": "worker/KokoroWorker.exe"},
        "model": {"config": "model/config.json", "weights": "model/kokoro-v1_0.pth"},
        "voices": {"af_heart": {"path": "voices/af_heart.pt", "language": "a"}},
        "required_groups": {
            "spacy": "worker/_internal/en_core_web_sm",
            "misaki_data": "worker/_internal/misaki/data",
            "espeak_ng": "worker/_internal/espeakng_loader",
        },
        "files": {relative: _sha256(root / relative) for relative in contents},
    }
    rewrite_manifest(root, manifest)
    return manifest


def rewrite_manifest(root: Path, manifest) -> None:
    (root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def test_valid_installation_returns_absolute_verified_paths(tmp_path):
    make_installation(tmp_path)
    installation = verify_kokoro_installation(tmp_path)
    assert installation.root == tmp_path.resolve()
    assert installation.worker_executable.is_absolute()
    assert DEFAULT_KOKORO_VOICE in installation.voices
    assert len(installation.manifest_sha256) == 64


def test_inspection_returns_required_paths_without_hashing_payload_bytes(
    monkeypatch, tmp_path
):
    make_installation(tmp_path)
    (tmp_path / "voices/af_heart.pt").write_bytes(b"corrupt-but-present")
    monkeypatch.setattr(
        "piper.kokoro_assets._sha256",
        lambda _path: (_ for _ in ()).throw(AssertionError("hashing is not inspection")),
    )

    installation = inspect_kokoro_installation(tmp_path)

    assert installation.root == tmp_path.resolve()
    assert installation.worker_executable == (
        tmp_path / "worker/KokoroWorker.exe"
    ).resolve()
    assert installation.model_path == (
        tmp_path / "model/kokoro-v1_0.pth"
    ).resolve()
    assert installation.voices["af_heart"].path == (
        tmp_path / "voices/af_heart.pt"
    ).resolve()
    assert len(installation.manifest_sha256) == 64


def test_inspection_rejects_missing_required_file(tmp_path):
    make_installation(tmp_path)
    (tmp_path / "model/kokoro-v1_0.pth").unlink()

    with pytest.raises(FileNotFoundError):
        inspect_kokoro_installation(tmp_path)


def test_inspection_rejects_missing_required_resource_directory(tmp_path):
    make_installation(tmp_path)
    resource = tmp_path / "worker/_internal/espeakng_loader"
    for path in sorted(resource.rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            path.rmdir()
    resource.rmdir()

    with pytest.raises(ValueError, match="resource group is not a directory"):
        inspect_kokoro_installation(tmp_path)


def test_missing_hashed_file_is_rejected(tmp_path):
    make_installation(tmp_path)
    (tmp_path / "model/kokoro-v1_0.pth").unlink()
    with pytest.raises(FileNotFoundError):
        verify_kokoro_installation(tmp_path)


def test_hash_mismatch_is_rejected(tmp_path):
    make_installation(tmp_path)
    (tmp_path / "voices/af_heart.pt").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_kokoro_installation(tmp_path)


def test_critical_file_missing_from_hash_map_is_rejected(tmp_path):
    manifest = make_installation(tmp_path)
    del manifest["files"]["model/kokoro-v1_0.pth"]
    rewrite_manifest(tmp_path, manifest)
    with pytest.raises(ValueError, match="critical file is not hashed"):
        verify_kokoro_installation(tmp_path)


def test_required_resource_group_without_hashed_member_is_rejected(tmp_path):
    manifest = make_installation(tmp_path)
    del manifest["files"]["worker/_internal/espeakng_loader/espeak-ng.exe"]
    rewrite_manifest(tmp_path, manifest)
    with pytest.raises(ValueError, match="required resource group"):
        verify_kokoro_installation(tmp_path)


def test_required_resource_group_must_resolve_to_a_directory(tmp_path):
    manifest = make_installation(tmp_path)
    manifest["required_groups"]["espeak_ng"] = "model/config.json"
    rewrite_manifest(tmp_path, manifest)
    with pytest.raises(ValueError, match="resource group is not a directory"):
        verify_kokoro_installation(tmp_path)


def test_unhashed_payload_file_is_rejected(tmp_path):
    make_installation(tmp_path)
    extra = tmp_path / "worker/_internal/en_core_web_sm/untracked.bin"
    extra.write_bytes(b"not declared")
    with pytest.raises(ValueError, match="does not hash every payload file"):
        verify_kokoro_installation(tmp_path)


def test_manifest_path_traversal_is_rejected(tmp_path):
    manifest = make_installation(tmp_path)
    manifest["model"]["weights"] = "../outside.pth"
    rewrite_manifest(tmp_path, manifest)
    with pytest.raises(ValueError, match="escapes install root"):
        verify_kokoro_installation(tmp_path)
