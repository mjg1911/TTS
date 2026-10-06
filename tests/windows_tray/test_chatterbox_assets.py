"""Integrity checks for the shared Nano and Turbo Chatterbox payload."""
import hashlib
import importlib
import json

import pytest


def _file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_shared_payload(tmp_path, monkeypatch, engines=("nano", "turbo")):
    nano = importlib.import_module("piper.nano_assets")
    turbo = importlib.import_module("piper.turbo_assets")
    model_contents = b"pinned model"
    model_hash = hashlib.sha256(model_contents).hexdigest()
    monkeypatch.setattr(
        nano, "MODEL_FILE_SHA256",
        {name: model_hash for name in nano.REQUIRED_MODEL_FILES},
    )
    monkeypatch.setattr(
        turbo, "MODEL_FILE_SHA256",
        {name: model_hash for name in turbo.REQUIRED_MODEL_FILES},
    )

    model_pins = {
        "nano": {
            "model_revision": nano.MODEL_REVISION,
            "model_repo": "ResembleAI/chatterbox-nano",
            "required_files": nano.REQUIRED_MODEL_FILES,
        },
        "turbo": {
            "model_revision": turbo.MODEL_REVISION,
            "model_repo": turbo.MODEL_REPO,
            "required_files": turbo.REQUIRED_MODEL_FILES,
        },
    }
    root = tmp_path / "chatterbox_payload"
    files = {}
    worker = root / "worker" / "ChatterboxWorker.exe"
    worker.parent.mkdir(parents=True)
    worker.write_bytes(b"shared worker")
    files["worker/ChatterboxWorker.exe"] = _file_hash(worker)
    models = {}
    for engine in engines:
        pin = model_pins[engine]
        models[engine] = {
            "model_revision": pin["model_revision"],
            "model_repo": pin["model_repo"],
        }
        for name in pin["required_files"]:
            relative = f"models/{engine}/{name}"
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(model_contents)
            files[relative] = _file_hash(target)
    manifest = {
        "manifest_version": 2,
        "runtime": "Chatterbox",
        "source_revision": nano.SOURCE_REVISION,
        "models": models,
        "files": files,
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return root, manifest, manifest_path


def test_shared_inspector_returns_one_worker_and_selected_model_directory(
    tmp_path, monkeypatch
):
    assets = importlib.import_module("piper.chatterbox_assets")
    root, _manifest, manifest_path = _write_shared_payload(tmp_path, monkeypatch)

    nano = assets.inspect_chatterbox_installation(root, "nano")
    turbo = assets.inspect_chatterbox_installation(root, "turbo")

    assert nano.root == root.resolve()
    assert nano.worker_executable == root / "worker" / "ChatterboxWorker.exe"
    assert nano.model_dir == root / "models" / "nano"
    assert nano.engine == "nano"
    assert turbo.worker_executable == nano.worker_executable
    assert turbo.model_dir == root / "models" / "turbo"
    assert turbo.engine == "turbo"
    assert nano.manifest_sha256 == _file_hash(manifest_path)


@pytest.mark.parametrize("engine", ["nano", "turbo"])
def test_engine_inspectors_accept_shared_manifest(tmp_path, monkeypatch, engine):
    root, _manifest, _manifest_path = _write_shared_payload(tmp_path, monkeypatch)
    module_name = "piper.nano_assets" if engine == "nano" else "piper.turbo_assets"
    inspector_name = f"inspect_{engine}_installation"
    installation = getattr(importlib.import_module(module_name), inspector_name)(root)

    assert installation.worker_executable == root / "worker" / "ChatterboxWorker.exe"
    assert installation.model_dir == root / "models" / engine
    assert installation.engine == engine


def test_shared_inspector_requires_the_selected_engine(tmp_path, monkeypatch):
    assets = importlib.import_module("piper.chatterbox_assets")
    root, _manifest, _manifest_path = _write_shared_payload(
        tmp_path, monkeypatch, engines=("nano",)
    )

    with pytest.raises(ValueError, match="selected engine"):
        assets.inspect_chatterbox_installation(root, "turbo")


def test_shared_inspector_accepts_a_payload_with_only_one_engine(tmp_path, monkeypatch):
    assets = importlib.import_module("piper.chatterbox_assets")
    root, _manifest, _manifest_path = _write_shared_payload(
        tmp_path, monkeypatch, engines=("nano",)
    )

    installation = assets.inspect_chatterbox_installation(root, "nano")

    assert installation.model_dir == root / "models" / "nano"


def test_shared_inspector_accepts_only_nano_or_turbo_engine(tmp_path, monkeypatch):
    assets = importlib.import_module("piper.chatterbox_assets")
    root, _manifest, _manifest_path = _write_shared_payload(tmp_path, monkeypatch)

    with pytest.raises(ValueError, match="engine"):
        assets.inspect_chatterbox_installation(root, "whisper")


def test_shared_inspector_pins_every_declared_model(tmp_path, monkeypatch):
    assets = importlib.import_module("piper.chatterbox_assets")
    root, manifest, manifest_path = _write_shared_payload(tmp_path, monkeypatch)
    turbo_file = root / "models" / "turbo" / "t3_turbo_v1.safetensors"
    turbo_file.write_bytes(b"different but manifest-hashed model")
    manifest["files"]["models/turbo/t3_turbo_v1.safetensors"] = _file_hash(turbo_file)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="pinned model hash"):
        assets.inspect_chatterbox_installation(root, "nano")


@pytest.mark.parametrize(
    "models",
    [{}, {"nano": {}, "turbo": {}, "other": {}}, {"other": {}}],
)
def test_shared_inspector_requires_one_or_two_known_model_declarations(
    tmp_path, monkeypatch, models
):
    assets = importlib.import_module("piper.chatterbox_assets")
    root, manifest, manifest_path = _write_shared_payload(tmp_path, monkeypatch)
    manifest["models"] = models
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="model"):
        assets.inspect_chatterbox_installation(root, "nano")


@pytest.mark.parametrize(
    "bad_path", ["../outside", "models/nano/../nano/t3_nano_v1.safetensors", "/outside"]
)
def test_shared_inspector_rejects_traversal_and_absolute_asset_paths(
    tmp_path, monkeypatch, bad_path
):
    assets = importlib.import_module("piper.chatterbox_assets")
    root, manifest, manifest_path = _write_shared_payload(tmp_path, monkeypatch)
    manifest["files"][bad_path] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="path"):
        assets.inspect_chatterbox_installation(root, "nano")


def test_shared_inspector_rejects_duplicate_manifest_keys(tmp_path, monkeypatch):
    assets = importlib.import_module("piper.chatterbox_assets")
    root, manifest, manifest_path = _write_shared_payload(tmp_path, monkeypatch)
    duplicate_files = json.dumps(manifest["files"])
    duplicate_files = duplicate_files[:-1] + ', "worker/ChatterboxWorker.exe": "' + manifest["files"]["worker/ChatterboxWorker.exe"] + '"}'
    raw = manifest_path.read_text(encoding="utf-8").replace(
        json.dumps(manifest["files"]), duplicate_files
    )
    manifest_path.write_text(raw, encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate"):
        assets.inspect_chatterbox_installation(root, "nano")


def test_shared_inspector_rejects_unhashed_extra_files(tmp_path, monkeypatch):
    assets = importlib.import_module("piper.chatterbox_assets")
    root, _manifest, _manifest_path = _write_shared_payload(tmp_path, monkeypatch)
    (root / "worker" / "unhashed.dll").write_bytes(b"extra")

    with pytest.raises(ValueError, match="inventory"):
        assets.inspect_chatterbox_installation(root, "nano")


def test_shared_inspector_rejects_a_tampered_worker(tmp_path, monkeypatch):
    assets = importlib.import_module("piper.chatterbox_assets")
    root, _manifest, _manifest_path = _write_shared_payload(tmp_path, monkeypatch)
    (root / "worker" / "ChatterboxWorker.exe").write_bytes(b"tampered worker")

    with pytest.raises(ValueError, match="asset hash mismatch"):
        assets.inspect_chatterbox_installation(root, "nano")


def test_shared_inspector_rejects_model_files_without_a_model_declaration(
    tmp_path, monkeypatch
):
    assets = importlib.import_module("piper.chatterbox_assets")
    root, manifest, manifest_path = _write_shared_payload(
        tmp_path, monkeypatch, engines=("nano",)
    )
    turbo_model = root / "models" / "turbo" / "extra.bin"
    turbo_model.parent.mkdir(parents=True)
    turbo_model.write_bytes(b"extra model")
    manifest["files"]["models/turbo/extra.bin"] = _file_hash(turbo_model)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="model"):
        assets.inspect_chatterbox_installation(root, "nano")
