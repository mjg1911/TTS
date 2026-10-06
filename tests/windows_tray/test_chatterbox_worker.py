"""Tests for the shared Chatterbox runtime and its tray launch routing."""
import importlib
import io
import os
import sys
from types import SimpleNamespace

import pytest

from piper.windows_tray.worker_protocol import decode_audio, read_frame, write_frame


def _shared_installation(root, engine):
    worker = root / "worker" / "ChatterboxWorker.exe"
    worker.parent.mkdir(parents=True, exist_ok=True)
    worker.touch()
    model_dir = root / "models" / engine
    model_dir.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(
        root=root,
        worker_executable=worker,
        model_dir=model_dir,
        manifest_sha256="a" * 64,
    )


@pytest.mark.parametrize("engine", ["nano", "turbo"])
def test_shared_worker_launcher_uses_common_module_and_explicit_engine(
    tmp_path, monkeypatch, engine
):
    nano_client = importlib.import_module("piper.windows_tray.nano_client")
    turbo_client = importlib.import_module("piper.windows_tray.turbo_client")
    installation = _shared_installation(tmp_path, engine)
    calls = {}
    process = object()

    def fake_popen(argv, **kwargs):
        calls["argv"] = argv
        calls["kwargs"] = kwargs
        return process

    monkeypatch.setattr(
        nano_client, "os", SimpleNamespace(name="posix", environ=os.environ)
    )
    monkeypatch.setattr(nano_client.subprocess, "Popen", fake_popen)
    monkeypatch.setenv("PIPER_CHATTERBOX_WORKER_PYTHON", "shared-python.exe")
    monkeypatch.setenv("PIPER_NANO_WORKER_PYTHON", "legacy-nano-python.exe")
    monkeypatch.setenv("PIPER_TURBO_WORKER_PYTHON", "legacy-turbo-python.exe")

    launched = (
        nano_client.launch_nano_worker(installation)
        if engine == "nano"
        else turbo_client.launch_turbo_worker(installation)
    )

    assert launched is process
    assert calls["argv"] == [
        "shared-python.exe",
        "-m",
        "piper.chatterbox_worker.main",
        "--engine",
        engine,
        "--root",
        str(tmp_path),
        "--model-dir",
        str(installation.model_dir),
    ]
    assert calls["kwargs"]["env"]["HF_HUB_OFFLINE"] == "1"
    assert calls["kwargs"]["env"]["TRANSFORMERS_OFFLINE"] == "1"


def test_shared_worker_launcher_falls_back_to_engine_python_override(
    tmp_path, monkeypatch
):
    nano_client = importlib.import_module("piper.windows_tray.nano_client")
    installation = _shared_installation(tmp_path, "nano")
    calls = {}

    monkeypatch.setattr(
        nano_client, "os", SimpleNamespace(name="posix", environ=os.environ)
    )
    monkeypatch.setattr(
        nano_client.subprocess,
        "Popen",
        lambda argv, **kwargs: calls.update(argv=argv, kwargs=kwargs) or object(),
    )
    monkeypatch.delenv("PIPER_CHATTERBOX_WORKER_PYTHON", raising=False)
    monkeypatch.setenv("PIPER_NANO_WORKER_PYTHON", "legacy-python.exe")

    nano_client.launch_nano_worker(installation)

    assert calls["argv"][0] == "legacy-python.exe"
    assert calls["argv"][2] == "piper.chatterbox_worker.main"


def test_legacy_worker_launcher_keeps_engine_specific_arguments(tmp_path, monkeypatch):
    nano_client = importlib.import_module("piper.windows_tray.nano_client")
    installation = SimpleNamespace(
        root=tmp_path,
        worker_executable=tmp_path / "worker" / "NanoWorker.exe",
    )
    calls = {}

    monkeypatch.setattr(
        nano_client, "os", SimpleNamespace(name="posix", environ=os.environ)
    )
    monkeypatch.setattr(
        nano_client.subprocess,
        "Popen",
        lambda argv, **kwargs: calls.update(argv=argv, kwargs=kwargs) or object(),
    )
    monkeypatch.setenv("PIPER_NANO_WORKER_PYTHON", "legacy-python.exe")

    nano_client.launch_nano_worker(installation)

    assert calls["argv"] == [
        "legacy-python.exe",
        "-m",
        "piper.nano_worker.main",
        "--root",
        str(tmp_path),
    ]


@pytest.mark.parametrize("engine", ["nano", "turbo"])
def test_shared_worker_main_routes_to_existing_engine_serve(
    tmp_path, monkeypatch, engine
):
    shared_main = importlib.import_module("piper.chatterbox_worker.main")
    incoming, outgoing = io.BytesIO(), io.BytesIO()
    installation = _shared_installation(tmp_path, engine)
    calls = []

    monkeypatch.setattr(
        shared_main,
        "serve_nano" if engine == "nano" else "serve_turbo",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    monkeypatch.setattr(shared_main.sys, "stdin", SimpleNamespace(buffer=incoming))
    monkeypatch.setattr(shared_main.sys, "stdout", SimpleNamespace(buffer=outgoing))

    assert shared_main.main(
        [
            "--engine",
            engine,
            "--root",
            str(installation.root),
            "--model-dir",
            str(installation.model_dir),
        ]
    ) == 0
    assert calls == [
        (
            (installation.root, incoming, outgoing),
            {"model_dir": installation.model_dir},
        )
    ]


def test_shared_worker_main_rejects_unknown_engine(monkeypatch):
    shared_main = importlib.import_module("piper.chatterbox_worker.main")
    with pytest.raises(SystemExit):
        shared_main.main(["--engine", "whisper", "--root", ".", "--model-dir", "."])


def _initialize_input():
    incoming = io.BytesIO()
    write_frame(
        incoming,
        {"type": "initialize", "manifest_sha256": "a" * 64},
    )
    incoming.seek(0)
    return incoming


def test_nano_serve_validates_shared_model_directory_before_load(
    tmp_path, monkeypatch
):
    nano_main = importlib.import_module("piper.nano_worker.main")
    installation = _shared_installation(tmp_path, "nano")
    inspected, loaded = [], []
    monkeypatch.setattr(
        nano_main,
        "inspect_nano_installation",
        lambda root: inspected.append(root) or installation,
    )
    monkeypatch.setattr(
        nano_main, "load_model", lambda *args, **kwargs: loaded.append(args)
    )
    monkeypatch.setattr(nano_main, "_configure_numba_cache", lambda _root: None)
    outgoing = io.BytesIO()

    with pytest.raises(ValueError, match="model directory"):
        nano_main.serve(
            installation.root,
            _initialize_input(),
            outgoing,
            model_dir=tmp_path / "wrong-model",
        )

    assert inspected == [installation.root]
    assert loaded == []


def test_turbo_serve_validates_shared_model_directory_before_load(
    tmp_path, monkeypatch
):
    turbo_main = importlib.import_module("piper.turbo_worker.main")
    installation = _shared_installation(tmp_path, "turbo")
    inspected, loaded = [], []
    monkeypatch.setattr(
        turbo_main,
        "inspect_turbo_installation",
        lambda root: inspected.append(root) or installation,
    )
    monkeypatch.setattr(
        turbo_main, "load_model", lambda *args, **kwargs: loaded.append(args)
    )
    monkeypatch.setattr(turbo_main, "_configure_numba_cache", lambda _root: None)
    incoming = io.BytesIO()
    write_frame(
        incoming,
        {"type": "initialize", "manifest_sha256": "a" * 64, "device": "cuda"},
    )
    incoming.seek(0)
    outgoing = io.BytesIO()

    turbo_main.serve(
        installation.root,
        incoming,
        outgoing,
        model_dir=tmp_path / "wrong-model",
    )

    outgoing.seek(0)
    assert read_frame(outgoing) == {
        "type": "hello",
        "engine": "Chatterbox Turbo (350M)",
        "protocol_version": 1,
    }
    startup_error = read_frame(outgoing)
    assert startup_error["type"] == "startup_error"
    assert "model directory" in startup_error["message"]
    assert inspected == [installation.root]
    assert loaded == []


@pytest.mark.parametrize(
    ("device", "with_reference"), [("cpu", False), ("cuda", True)]
)
def test_shared_worker_routes_nano_device_and_reference_to_engine_runtime(
    tmp_path, monkeypatch, device, with_reference
):
    shared_main = importlib.import_module("piper.chatterbox_worker.main")
    nano_main = importlib.import_module("piper.nano_worker.main")
    installation = _shared_installation(tmp_path, "nano")
    inspected, loaded = [], []
    monkeypatch.setattr(
        nano_main,
        "inspect_nano_installation",
        lambda root: inspected.append(root) or installation,
    )
    monkeypatch.setattr(nano_main, "_configure_numba_cache", lambda _root: None)
    model = SimpleNamespace(
        sr=24000,
        effective_device=device,
        device_message="shared Nano device",
    )
    monkeypatch.setattr(
        nano_main,
        "load_model",
        lambda model_dir, **options: loaded.append((model_dir, options)) or model,
    )
    request = {"type": "initialize", "manifest_sha256": "a" * 64, "device": device}
    reference = None
    if with_reference:
        reference = tmp_path / "reference.wav"
        reference.write_bytes(b"RIFF fake wave")
        request["reference_clip"] = str(reference.resolve())
    incoming, outgoing = io.BytesIO(), io.BytesIO()
    write_frame(incoming, request)
    write_frame(incoming, {"type": "shutdown"})
    incoming.seek(0)
    monkeypatch.setattr(shared_main.sys, "stdin", SimpleNamespace(buffer=incoming))
    monkeypatch.setattr(shared_main.sys, "stdout", SimpleNamespace(buffer=outgoing))

    assert shared_main.main(
        [
            "--engine",
            "nano",
            "--root",
            str(installation.root),
            "--model-dir",
            str(installation.model_dir),
        ]
    ) == 0

    outgoing.seek(0)
    assert read_frame(outgoing)["engine"] == "Chatterbox Nano"
    assert read_frame(outgoing) == {
        "type": "ready",
        "sample_rate": 24000,
        "device": device,
        "device_message": "shared Nano device",
    }
    expected_options = {"device": "cuda"} if device == "cuda" else {}
    if reference is not None:
        expected_options["reference_clip"] = str(reference.resolve())
    assert loaded == [(installation.model_dir, expected_options)]
    assert inspected == [installation.root]


def test_shared_worker_routes_turbo_cuda_and_delivery_mode_to_runtime(
    tmp_path, monkeypatch
):
    shared_main = importlib.import_module("piper.chatterbox_worker.main")
    turbo_main = importlib.import_module("piper.turbo_worker.main")
    installation = _shared_installation(tmp_path, "turbo")
    inspected, loaded, generated = [], [], []
    monkeypatch.setattr(
        turbo_main,
        "inspect_turbo_installation",
        lambda root: inspected.append(root) or installation,
    )
    monkeypatch.setattr(turbo_main, "_configure_numba_cache", lambda _root: None)
    model = SimpleNamespace(sr=24000)
    monkeypatch.setattr(
        turbo_main,
        "load_model",
        lambda model_dir, **options: loaded.append((model_dir, options)) or model,
    )

    def generate_chunks(model_arg, text, *, delivery_mode):
        generated.append((model_arg, text, delivery_mode))
        yield b"\x00\x00"

    monkeypatch.setattr(turbo_main, "generate_chunks", generate_chunks)
    incoming, outgoing = io.BytesIO(), io.BytesIO()
    write_frame(
        incoming,
        {"type": "initialize", "manifest_sha256": "a" * 64, "device": "cuda"},
    )
    write_frame(
        incoming,
        {
            "type": "synthesize",
            "request_id": 1,
            "text": "hello",
            "voice_id": "default",
            "delivery_mode": "[whispering]",
        },
    )
    write_frame(incoming, {"type": "shutdown"})
    incoming.seek(0)
    monkeypatch.setattr(shared_main.sys, "stdin", SimpleNamespace(buffer=incoming))
    monkeypatch.setattr(shared_main.sys, "stdout", SimpleNamespace(buffer=outgoing))

    assert shared_main.main(
        [
            "--engine",
            "turbo",
            "--root",
            str(installation.root),
            "--model-dir",
            str(installation.model_dir),
        ]
    ) == 0

    outgoing.seek(0)
    assert read_frame(outgoing)["engine"] == "Chatterbox Turbo (350M)"
    assert read_frame(outgoing) == {
        "type": "ready",
        "sample_rate": 24000,
        "device": "cuda",
        "device_message": "Chatterbox Turbo (350M) uses GPU (CUDA).",
    }
    audio_frame = read_frame(outgoing)
    assert audio_frame["type"] == "audio"
    assert audio_frame["request_id"] == 1
    assert decode_audio(audio_frame["audio"]) == b"\x00\x00"
    assert read_frame(outgoing) == {
        "type": "response_end", "request_id": 1
    }
    assert loaded == [(installation.model_dir, {"reference_clip": None})]
    assert generated == [(model, "hello", "[whispering]")]
    assert inspected == [installation.root]
