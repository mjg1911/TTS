import hashlib
import json
from pathlib import Path

import pytest

from piper.windows_tray.kokoro_payload import ensure_bundled_kokoro_payload


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_payload(root: Path, marker: bytes = b"v1") -> Path:
    files = {
        "worker/KokoroWorker.exe": b"worker" + marker,
        "worker/_internal/en_core_web_sm/meta.json": b"spacy" + marker,
        "worker/_internal/misaki/data/us_gold.json": b"misaki" + marker,
        "worker/_internal/espeakng_loader/espeak-ng.exe": b"espeak" + marker,
        "model/config.json": b"{}",
        "model/kokoro-v1_0.pth": b"model" + marker,
        "voices/af_heart.pt": b"voice" + marker,
    }
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
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
        "files": {relative: _sha256(root / relative) for relative in files},
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return root


def test_missing_target_is_bootstrapped_and_verified(tmp_path):
    bundle = make_payload(tmp_path / "bundle")
    install = tmp_path / "installed"
    result = ensure_bundled_kokoro_payload(bundle, install)
    assert result.root == install.resolve()
    assert (install / "voices/af_heart.pt").is_file()


def test_identical_valid_manifest_is_noop(monkeypatch, tmp_path):
    bundle = make_payload(tmp_path / "bundle")
    install = make_payload(tmp_path / "installed")
    monkeypatch.setattr(
        "piper.windows_tray.kokoro_payload.shutil.copytree",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("copy not expected")),
    )
    ensure_bundled_kokoro_payload(bundle, install)


def test_different_but_valid_existing_payload_is_upgraded(tmp_path):
    bundle = make_payload(tmp_path / "bundle", b"new")
    install = make_payload(tmp_path / "installed", b"old")
    ensure_bundled_kokoro_payload(bundle, install)
    assert (install / "model/kokoro-v1_0.pth").read_bytes() == b"modelnew"


def test_corrupt_existing_target_is_not_repaired(tmp_path):
    bundle = make_payload(tmp_path / "bundle", b"new")
    install = make_payload(tmp_path / "installed", b"old")
    (install / "model/kokoro-v1_0.pth").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="hash mismatch"):
        ensure_bundled_kokoro_payload(bundle, install)


def test_invalid_bundle_leaves_previous_verified_install_untouched(tmp_path):
    install = make_payload(tmp_path / "installed", b"old")
    before = (install / "manifest.json").read_bytes()
    bundle = make_payload(tmp_path / "bundle", b"new")
    (bundle / "voices/af_heart.pt").write_bytes(b"corrupt")
    with pytest.raises((FileNotFoundError, ValueError)):
        ensure_bundled_kokoro_payload(bundle, install)
    assert (install / "manifest.json").read_bytes() == before


def test_rollback_restores_previous_verified_install(monkeypatch, tmp_path):
    bundle = make_payload(tmp_path / "bundle", b"new")
    install = make_payload(tmp_path / "installed", b"old")
    original_replace = __import__("piper.windows_tray.kokoro_payload", fromlist=["os"]).os.replace
    calls = []

    def replace(source, destination):
        calls.append((Path(source), Path(destination)))
        if len(calls) == 2:
            raise OSError("simulated install failure")
        return original_replace(source, destination)

    monkeypatch.setattr("piper.windows_tray.kokoro_payload.os.replace", replace)
    with pytest.raises(OSError, match="simulated install failure"):
        ensure_bundled_kokoro_payload(bundle, install)
    assert (install / "model/kokoro-v1_0.pth").read_bytes() == b"modelold"
