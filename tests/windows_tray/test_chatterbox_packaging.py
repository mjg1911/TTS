"""The frozen distribution contains one shared Chatterbox worker and payload."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]


def _load_stager():
    path = ROOT / "script" / "stage_chatterbox_payload.py"
    spec = importlib.util.spec_from_file_location("stage_chatterbox_payload", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_model(engine, destination, monkeypatch):
    import importlib

    assets = importlib.import_module(
        "piper.nano_assets" if engine == "nano" else "piper.turbo_assets"
    )
    destination.mkdir(parents=True)
    model_hashes = {}
    for name in assets.REQUIRED_MODEL_FILES:
        path = destination / name
        path.write_bytes((engine + ":" + name).encode("utf-8"))
        model_hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(assets, "MODEL_FILE_SHA256", model_hashes)
    return assets


def _run_stager(monkeypatch, worker, output, *, nano_model=None, turbo_model=None):
    args = [
        "stage_chatterbox_payload.py",
        "--worker-dir",
        str(worker),
        "--output",
        str(output),
    ]
    if nano_model is not None:
        args += ["--nano-model-dir", str(nano_model)]
    if turbo_model is not None:
        args += ["--turbo-model-dir", str(turbo_model)]
    monkeypatch.setattr(sys, "argv", args)
    _load_stager().main()


def test_stager_builds_one_version_two_payload_for_both_engines(tmp_path, monkeypatch):
    import importlib

    nano_assets = _write_model("nano", tmp_path / "nano-source", monkeypatch)
    turbo_assets = _write_model("turbo", tmp_path / "turbo-source", monkeypatch)
    worker = tmp_path / "worker"
    worker.mkdir()
    (worker / "ChatterboxWorker.exe").write_bytes(b"one shared worker")
    output = tmp_path / "payload"

    _run_stager(
        monkeypatch,
        worker,
        output,
        nano_model=tmp_path / "nano-source",
        turbo_model=tmp_path / "turbo-source",
    )

    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_version"] == 2
    assert manifest["runtime"] == "Chatterbox"
    assert manifest["source_revision"] == nano_assets.SOURCE_REVISION
    assert manifest["models"] == {
        "nano": {
            "model_revision": nano_assets.MODEL_REVISION,
            "model_repo": nano_assets.MODEL_REPO,
        },
        "turbo": {
            "model_revision": turbo_assets.MODEL_REVISION,
            "model_repo": turbo_assets.MODEL_REPO,
        },
    }
    assert set(manifest["files"]) == {
        "worker/ChatterboxWorker.exe",
        *(
            f"models/{engine}/{name}"
            for engine, assets in (("nano", nano_assets), ("turbo", turbo_assets))
            for name in assets.REQUIRED_MODEL_FILES
        ),
    }
    inspector = importlib.import_module("piper.chatterbox_assets").inspect_chatterbox_installation
    nano = inspector(output, "nano")
    turbo = inspector(output, "turbo")
    assert nano.worker_executable == turbo.worker_executable
    assert nano.model_dir == output / "models" / "nano"
    assert turbo.model_dir == output / "models" / "turbo"


def test_stager_allows_one_engine_and_rejects_absent_engine(tmp_path, monkeypatch):
    import importlib

    nano_assets = _write_model("nano", tmp_path / "nano-source", monkeypatch)
    worker = tmp_path / "worker"
    worker.mkdir()
    (worker / "ChatterboxWorker.exe").write_bytes(b"worker")
    output = tmp_path / "nano-payload"

    _run_stager(monkeypatch, worker, output, nano_model=tmp_path / "nano-source")

    inspector = importlib.import_module("piper.chatterbox_assets").inspect_chatterbox_installation
    assert inspector(output, "nano").model_dir == output / "models" / "nano"
    with pytest.raises(ValueError, match="absent"):
        inspector(output, "turbo")
    assert set(json.loads((output / "manifest.json").read_text())["models"]) == {"nano"}

    assert nano_assets.MODEL_REVISION


def test_stager_requires_a_model_source_and_does_not_download_implicitly(tmp_path, monkeypatch):
    worker = tmp_path / "worker"
    worker.mkdir()
    (worker / "ChatterboxWorker.exe").write_bytes(b"worker")
    output = tmp_path / "payload"

    with pytest.raises(ValueError, match="at least one pinned Chatterbox model"):
        _run_stager(monkeypatch, worker, output)

    assert not output.exists()


def test_stager_download_switches_can_select_both_pinned_models(tmp_path, monkeypatch):
    import importlib

    nano_assets = _write_model("nano", tmp_path / "nano-source", monkeypatch)
    turbo_assets = _write_model("turbo", tmp_path / "turbo-source", monkeypatch)
    worker = tmp_path / "worker"
    worker.mkdir()
    (worker / "ChatterboxWorker.exe").write_bytes(b"worker")
    output = tmp_path / "payload"
    stager = _load_stager()

    def download_model(engine):
        return tmp_path / (engine + "-source")

    monkeypatch.setattr(stager, "_download_model", download_model)
    monkeypatch.setattr(sys, "argv", [
        "stage_chatterbox_payload.py", "--worker-dir", str(worker), "--output", str(output),
        "--download-nano", "--download-turbo",
    ])
    stager.main()

    models = json.loads((output / "manifest.json").read_text(encoding="utf-8"))["models"]
    assert set(models) == {"nano", "turbo"}
    inspector = importlib.import_module("piper.chatterbox_assets").inspect_chatterbox_installation
    assert inspector(output, "nano").model_dir == output / "models" / "nano"
    assert inspector(output, "turbo").model_dir == output / "models" / "turbo"
    assert nano_assets.SOURCE_REVISION == turbo_assets.SOURCE_REVISION


def test_tray_packages_and_verifies_the_shared_payload_once():
    spec = (ROOT / "script" / "piper_tray.spec").read_text(encoding="utf-8")
    build = (ROOT / "script" / "build_windows_tray.ps1").read_text(encoding="utf-8")
    installer = (ROOT / "script" / "build_windows_installer.ps1").read_text(encoding="utf-8")

    assert "PIPER_CHATTERBOX_PAYLOAD_DIR" in spec
    assert "chatterbox_payload_datas" in spec
    assert "inspect_chatterbox_installation" in spec
    assert '"nano"' in spec and '"turbo"' in spec
    assert "nano_payload_datas" not in spec and "turbo_payload_datas" not in spec
    assert "build_chatterbox_worker.ps1" in build
    assert "stage_chatterbox_payload.ps1" in build
    assert "inspect_chatterbox_installation" in build
    assert "PIPER_NANO_PAYLOAD_DIR" in build and "PIPER_TURBO_PAYLOAD_DIR" in build
    assert "legacy per-engine" in build.lower() or "shared payload" in build.lower()
    assert "inspect_chatterbox_installation" in installer
    assert "chatterbox_payload/manifest.json" in installer
    assert "nano_payload/manifest.json" not in installer
    assert "turbo_payload/manifest.json" not in installer


def test_worker_build_uses_one_requirements_file_venv_and_frozen_executable():
    build = (ROOT / "script" / "build_chatterbox_worker.ps1").read_text(encoding="utf-8")
    spec = (ROOT / "script" / "chatterbox_worker.spec").read_text(encoding="utf-8")
    setup = (ROOT / "setup.py").read_text(encoding="utf-8")
    requirements = (ROOT / "requirements" / "chatterbox-worker.in").read_text(encoding="utf-8")

    assert "build/chatterbox-venv/Scripts/python.exe" in build
    assert "requirements/chatterbox-worker.in" in build
    assert "cu124" in build
    assert "ChatterboxWorker.exe" in build
    assert "chatterbox_worker_entry.py" in spec
    assert "piper.nano_worker" in spec and "piper.turbo_worker" in spec
    assert "piper.chatterbox_worker" in setup
    assert "chatterbox-tts" in requirements
    assert not (ROOT / "requirements" / "nano-worker.in").exists()
    assert not (ROOT / "requirements" / "turbo-worker.in").exists()


@pytest.mark.parametrize(
    ("wrapper", "legacy_env"),
    [
        ("build_nano_worker.ps1", "PIPER_NANO_WORKER_PYTHON"),
        ("build_turbo_worker.ps1", "PIPER_TURBO_WORKER_PYTHON"),
    ],
)
def test_old_build_commands_forward_to_the_single_worker_builder(wrapper, legacy_env):
    text = (ROOT / "script" / wrapper).read_text(encoding="utf-8")
    assert "build_chatterbox_worker.ps1" in text
    assert legacy_env in text
    assert "PyInstaller" not in text
    assert "NanoWorker.exe" not in text
    assert "TurboWorker.exe" not in text


def test_old_stage_commands_forward_to_one_engine_in_the_shared_payload():
    nano = (ROOT / "script" / "stage_nano_payload.ps1").read_text(encoding="utf-8")
    turbo = (ROOT / "script" / "stage_turbo_payload.ps1").read_text(encoding="utf-8")
    assert "stage_chatterbox_payload.ps1" in nano and "NanoModelDir" in nano
    assert "stage_chatterbox_payload.ps1" in turbo and "TurboModelDir" in turbo
    assert "DownloadNano" in nano and "DownloadTurbo" in turbo
    assert "nano-payload" not in nano
    assert "turbo-payload" not in turbo


def test_readme_documents_the_common_staging_and_legacy_environment_migration():
    readme = (ROOT / "README.md").read_text(encoding="utf-8").lower()
    assert "build_chatterbox_worker.ps1" in readme
    assert "stage_chatterbox_payload.ps1" in readme
    assert "piper_chatterbox_payload_dir" in readme
    assert "piper_chatterbox_worker_python" in readme
    assert "piper_nano_payload_dir" not in readme
    assert "piper_turbo_payload_dir" not in readme
