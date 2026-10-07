"""Release asset generation and offline diagnostics for Piper 1.10.0."""

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "script" / "prepare_model_release.py"
SPEC = ROOT / "script" / "piper_tray.spec"


def _release_module():
    spec = importlib.util.spec_from_file_location("prepare_model_release", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def tiny_payload(monkeypatch, tmp_path):
    from piper import nano_assets, turbo_assets

    for engine, assets in (("nano", nano_assets), ("turbo", turbo_assets)):
        monkeypatch.setattr(assets, "SOURCE_REVISION", "test-source-revision")
        monkeypatch.setattr(assets, "MODEL_REVISION", f"test-{engine}-revision")
        monkeypatch.setattr(assets, "MODEL_REPO", f"ResembleAI/test-{engine}")
        monkeypatch.setattr(assets, "REQUIRED_MODEL_FILES", ("model.bin", "tokenizer.json"))
        monkeypatch.setattr(assets, "MODEL_FILE_SHA256", {
            "model.bin": hashlib.sha256(f"{engine}-weights".encode()).hexdigest(),
            "tokenizer.json": hashlib.sha256(f"{engine}-tokenizer".encode()).hexdigest(),
        })
    payload = tmp_path / "payload"
    file_hashes = {}

    def add_file(relative, content):
        path = payload / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        file_hashes[relative] = hashlib.sha256(content).hexdigest()

    add_file("worker/ChatterboxWorker.exe", b"worker executable")
    models = {}
    for engine, assets in (("nano", nano_assets), ("turbo", turbo_assets)):
        models[engine] = {
            "model_revision": assets.MODEL_REVISION,
            "model_repo": assets.MODEL_REPO,
        }
        add_file(f"models/{engine}/model.bin", f"{engine}-weights".encode())
        add_file(f"models/{engine}/tokenizer.json", f"{engine}-tokenizer".encode())

    manifest = {
        "manifest_version": 2,
        "runtime": "Chatterbox",
        "source_revision": nano_assets.SOURCE_REVISION,
        "models": models,
        "files": file_hashes,
    }
    (payload / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return payload


def test_generator_builds_independent_deterministic_verified_archives(
    tiny_payload, tmp_path
):
    release = _release_module()
    output = tmp_path / "assets"
    catalog_path = tmp_path / "model_catalog.json"

    catalog = release.prepare_model_release(
        tiny_payload, output, catalog_path, "v1.10.0", max_part_bytes=100_000
    )
    first_archives = {
        name: [Path(part["url"].rsplit("/", 1)[1]) for part in value["parts"]]
        for name, value in catalog["components"].items()
    }
    inventories = {}
    for component, filenames in first_archives.items():
        with zipfile.ZipFile(output / filenames[0]) as archive:
            inventories[component] = set(archive.namelist())

    assert inventories == {
        "worker": {"worker/ChatterboxWorker.exe"},
        "nano": {"models/nano/model.bin", "models/nano/tokenizer.json"},
        "turbo": {"models/turbo/model.bin", "models/turbo/tokenizer.json"},
    }
    assert catalog["release"] == "v1.10.0"
    for component, value in catalog["components"].items():
        part = value["parts"][0]
        asset = output / first_archives[component][0]
        assert part["url"] == (
            "https://github.com/mjg1911/TTS/releases/download/v1.10.0/"
            + asset.name
        )
        assert part["size"] == asset.stat().st_size
        assert part["sha256"] == hashlib.sha256(asset.read_bytes()).hexdigest()

    before = {path.name: path.read_bytes() for path in output.iterdir()}
    repeat = release.prepare_model_release(
        tiny_payload, output, catalog_path, "v1.10.0", max_part_bytes=100_000
    )
    assert catalog == repeat
    assert before == {path.name: path.read_bytes() for path in output.iterdir()}
    assert json.loads(catalog_path.read_text(encoding="utf-8")) == catalog


def test_generator_splits_and_reassembles_large_archive_parts(
    tiny_payload, tmp_path
):
    release = _release_module()
    output = tmp_path / "assets"
    catalog = release.prepare_model_release(
        tiny_payload, output, tmp_path / "catalog.json", "v1.10.0",
        max_part_bytes=128,
    )

    for component in ("worker", "nano", "turbo"):
        parts = catalog["components"][component]["parts"]
        assert len(parts) > 1
        assert all(part["size"] <= 128 for part in parts)
        archive_bytes = b"".join(
            (output / part["url"].rsplit("/", 1)[1]).read_bytes()
            for part in parts
        )
        import io

        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            assert archive.testzip() is None
            assert archive.namelist()


def test_generator_rejects_payload_missing_one_pinned_model(tiny_payload, tmp_path):
    manifest_path = tiny_payload / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["models"].pop("turbo")
    manifest["files"].pop("models/turbo/model.bin")
    manifest["files"].pop("models/turbo/tokenizer.json")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    release = _release_module()
    with pytest.raises((ValueError, RuntimeError)):
        release.prepare_model_release(
            tiny_payload, tmp_path / "assets", tmp_path / "catalog.json", "v1.10.0"
        )


def test_regenerating_removes_only_obsolete_generated_parts(tiny_payload, tmp_path):
    release = _release_module()
    output = tmp_path / "assets"
    catalog_path = tmp_path / "catalog.json"
    release.prepare_model_release(tiny_payload, output, catalog_path, max_part_bytes=128)
    unrelated = output / "keep.txt"
    unrelated.write_text("user file")
    catalog = release.prepare_model_release(tiny_payload, output, catalog_path, max_part_bytes=100_000)
    expected = {part["url"].rsplit("/", 1)[1]
                for component in catalog["components"].values() for part in component["parts"]}
    assert {path.name for path in output.iterdir()} == expected | {"keep.txt"}


def test_frozen_voice_directory_is_searched_for_bundled_default(monkeypatch, tmp_path):
    from piper.windows_tray import app

    frozen_root = tmp_path / "_internal"
    monkeypatch.setattr(sys, "_MEIPASS", str(frozen_root), raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.chdir(tmp_path)

    assert frozen_root / "voices" in tuple(app._voice_data_dirs())


def test_offline_smoke_test_synthesizes_checks_catalog_and_closes_panel(
    monkeypatch, tmp_path
):
    import numpy as np
    from piper.windows_tray import app
    from piper.windows_tray import model_download_ui

    voice_path = tmp_path / "en_GB-alba-medium.onnx"

    class Chunk:
        audio_float_array = np.array([0.1, -0.1, 0.2])

    class Voice:
        def synthesize(self, text):
            assert text
            yield Chunk()

    monkeypatch.setattr(
        app, "load_voice_candidate", lambda reference, dirs: (voice_path, Voice())
    )
    monkeypatch.setattr(
        app,
        "load_catalog",
        lambda: {
            "version": 1,
            "release": "v1.10.0",
            "components": {
                name: {"parts": [{
                    "url": f"https://github.com/mjg1911/TTS/releases/download/v1.10.0/{name}.zip",
                    "size": 123,
                    "sha256": "0" * 64,
                }]}
                for name in ("worker", "nano", "turbo")
            },
        }, raising=False,
    )
    lifecycle = []

    class Root:
        def withdraw(self):
            lifecycle.append("withdraw")

        def destroy(self):
            lifecycle.append("root-destroy")

    class Panel:
        def __init__(self, _root):
            lifecycle.append("panel-create")

        def close(self):
            lifecycle.append("panel-close")

    import tkinter

    monkeypatch.setattr(tkinter, "Tk", Root)
    monkeypatch.setattr(model_download_ui, "ModelDownloadPanel", Panel)
    monkeypatch.setattr(app, "save_settings", lambda *_args: pytest.fail("settings saved"))
    monkeypatch.setattr(app, "run_app", lambda **_kwargs: pytest.fail("tray launched"))
    result_path = tmp_path / "smoke.json"

    exit_code = app.run_offline_smoke_test(result_path)

    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert result["status"] == "passed"
    assert result["voice_model"] == "en_GB-alba-medium"
    assert result["audio_samples"] == 3
    assert result["catalog_asset_parts"] == {"worker": 1, "nano": 1, "turbo": 1}
    assert lifecycle == ["withdraw", "panel-create", "panel-close", "root-destroy"]


def test_offline_smoke_test_writes_failure_json_and_returns_nonzero(
    monkeypatch, tmp_path
):
    from piper.windows_tray import app

    monkeypatch.setattr(
        app, "load_voice_candidate", lambda *_args: (_ for _ in ()).throw(
            FileNotFoundError("bundled default voice is missing")
        )
    )
    result_path = tmp_path / "failure" / "smoke.json"

    exit_code = app.run_offline_smoke_test(result_path)

    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert exit_code != 0
    assert result["status"] == "failed"
    assert result["exception_type"] == "FileNotFoundError"
    assert "default voice" in result["error"]


def test_hidden_cli_diagnostic_dispatches_without_starting_app(monkeypatch, tmp_path, capsys):
    from piper.windows_tray import __main__ as entry
    from piper.windows_tray import app

    destination = tmp_path / "result.json"
    calls = []
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(app, "run_offline_smoke_test", lambda path: calls.append(path) or 0,
                        raising=False)
    monkeypatch.setattr(app, "run_app", lambda **_kwargs: pytest.fail("tray launched"),
                        raising=False)

    assert entry.main(["--offline-smoke-test", str(destination)]) == 0
    assert calls == [destination]
    with pytest.raises(SystemExit) as help_exit:
        entry._parse_args(["--help"])
    assert help_exit.value.code == 0
    assert "offline-smoke-test" not in capsys.readouterr().out


def test_release_spec_bundles_voice_and_catalog_ignoring_stale_payload(monkeypatch, tmp_path):
    from types import ModuleType, SimpleNamespace
    import os

    hooks = ModuleType("PyInstaller.utils.hooks")
    hooks.collect_data_files = lambda _: []
    hooks.collect_dynamic_libs = lambda _: []
    hooks.collect_submodules = lambda _: []
    monkeypatch.setitem(sys.modules, "PyInstaller.utils.hooks", hooks)
    monkeypatch.setenv("PIPER_RELEASE_MODE", "1")
    monkeypatch.setenv("PIPER_CHATTERBOX_PAYLOAD_DIR", str(tmp_path / "missing-payload"))
    monkeypatch.setenv("PIPER_REQUIRE_NANO_PAYLOAD", "1")
    voice_dir = tmp_path / "voices"
    voice_dir.mkdir()
    for suffix in (".onnx", ".onnx.json"):
        (voice_dir / ("en_GB-alba-medium" + suffix)).write_bytes(b"voice")
    monkeypatch.setenv("PIPER_DEFAULT_VOICE_DIR", str(voice_dir))
    captured = {}
    def analysis(*args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(pure=[], scripts=[], binaries=[], datas=[])
    scope = {"SPECPATH": str(ROOT / "script"), "Analysis": analysis,
             "PYZ": lambda *_: None, "EXE": lambda *_, **__: None,
             "COLLECT": lambda *_, **__: None}
    exec(compile(SPEC.read_text(encoding="utf-8"), str(SPEC), "exec"), scope)
    datas = captured["datas"]
    assert all("chatterbox_payload" not in target for _, target in datas)
    assert all(any(Path(source).name == "en_GB-alba-medium" + suffix and target == "voices"
                   for source, target in datas) for suffix in (".onnx", ".onnx.json"))
    assert any(Path(source).name == "model_catalog.json" and target == "piper"
               for source, target in datas)
    assert "torch" in captured["excludes"]
