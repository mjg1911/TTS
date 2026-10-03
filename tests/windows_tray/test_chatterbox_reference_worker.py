"""Reference clip storage and optional Nano custom voice initialization."""
import hashlib
import importlib
import io
import json
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest


def _write_clip(path, *, seconds=6, sample_rate=16000, samples=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = seconds * sample_rate
    if samples is None:
        samples = b"\x01\x00" * frames
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(samples)
    return path


@pytest.fixture
def reference_module():
    return importlib.import_module("piper.windows_tray.chatterbox_voice")


def test_import_reference_clip_copies_to_unique_managed_wav_and_validates_without_copy(
    tmp_path, reference_module
):
    source = _write_clip(tmp_path / "source" / "guide.wav")
    managed = tmp_path / "Piper" / "Chatterbox" / "References"

    first = reference_module.import_reference_clip(source, managed)
    second = reference_module.import_reference_clip(source, managed)

    assert first.is_absolute()
    assert first.parent == managed.resolve()
    assert first != second
    assert first.read_bytes() == source.read_bytes()
    assert second.read_bytes() == source.read_bytes()
    assert reference_module.validate_reference_clip(first) == first.resolve()
    assert sorted(path.name for path in managed.iterdir()) == sorted(
        (first.name, second.name)
    )


def test_import_reference_clip_uses_local_piper_data_directory_by_default(
    tmp_path, monkeypatch, reference_module
):
    source = _write_clip(tmp_path / "guide.wav")
    local_appdata = tmp_path / "local-app-data"
    monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))

    imported = reference_module.import_reference_clip(source)

    assert imported.parent == (
        local_appdata / "Piper" / "Chatterbox" / "References"
    ).resolve()


def test_reference_clip_must_be_longer_than_five_seconds(tmp_path, reference_module):
    source = _write_clip(tmp_path / "exactly-five.wav", seconds=5)

    with pytest.raises(ValueError, match="longer than 5 seconds"):
        reference_module.validate_reference_clip(source)


@pytest.mark.parametrize("kind", ["corrupt", "truncated", "silent"])
def test_reference_clip_rejects_unusable_wave_data(tmp_path, reference_module, kind):
    source = tmp_path / f"{kind}.wav"
    if kind == "corrupt":
        source.write_bytes(b"not a wave file")
    elif kind == "truncated":
        _write_clip(source)
        source.write_bytes(source.read_bytes()[:64])
    else:
        _write_clip(source, samples=b"\x00\x00" * 6 * 16000)

    with pytest.raises(ValueError):
        reference_module.validate_reference_clip(source)


def test_reference_clip_rejects_files_above_the_size_limit(
    tmp_path, monkeypatch, reference_module
):
    source = _write_clip(tmp_path / "large.wav")
    monkeypatch.setattr(reference_module, "MAX_REFERENCE_CLIP_BYTES", 128)

    with pytest.raises(ValueError, match="too large"):
        reference_module.validate_reference_clip(source)


class _Process:
    def __init__(self, frames):
        from piper.windows_tray.kokoro_protocol import write_frame

        self.stdout = io.BytesIO()
        for frame in frames:
            write_frame(self.stdout, frame)
        self.stdout.seek(0)
        self.stdin = io.BytesIO()
        self.killed = False

    def poll(self):
        return 0 if self.killed else None

    def terminate(self):
        self.killed = True

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        return 0


def test_nano_client_sends_absolute_reference_only_when_custom_voice_is_enabled(
    tmp_path, monkeypatch
):
    assets = importlib.import_module("piper.nano_assets")
    client_module = importlib.import_module("piper.windows_tray.nano_client")
    asset_hash = hashlib.sha256(b"asset").hexdigest()
    monkeypatch.setattr(
        assets,
        "MODEL_FILE_SHA256",
        {name: asset_hash for name in assets.REQUIRED_MODEL_FILES},
    )
    paths = ["worker/NanoWorker.exe"] + [
        "model/" + name for name in assets.REQUIRED_MODEL_FILES
    ]
    files = {}
    for name in paths:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"asset")
        files[name] = asset_hash
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "engine": "Chatterbox Nano",
                "source_revision": assets.SOURCE_REVISION,
                "model_revision": assets.MODEL_REVISION,
                "files": files,
            }
        )
    )
    installation = assets.inspect_nano_installation(tmp_path)
    reference = _write_clip(tmp_path / "managed" / "guide.wav")
    process = _Process(
        [
            {"type": "hello", "engine": "Chatterbox Nano", "protocol_version": 1},
            {"type": "ready", "sample_rate": 22050},
        ]
    )
    worker = client_module.NanoWorkerClient(
        installation,
        process_factory=lambda _: process,
        reference_clip=reference,
    )

    try:
        worker.ensure_ready()
        from piper.windows_tray.kokoro_protocol import read_frame

        process.stdin.seek(0)
        assert read_frame(process.stdin) == {
            "type": "initialize",
            "manifest_sha256": installation.manifest_sha256,
            "reference_clip": str(reference.resolve()),
        }
    finally:
        worker.shutdown()


def test_runtime_prepares_custom_conditionals_once_before_returning_model(tmp_path):
    runtime = importlib.import_module("piper.nano_worker.runtime")
    reference = _write_clip(tmp_path / "guide.wav")
    calls = []

    class Model:
        @classmethod
        def from_local(cls, directory, **kwargs):
            return SimpleNamespace(
                sr=22050,
                conds=object(),
                prepare_conditionals=lambda path, exaggeration: calls.append(
                    (path, exaggeration)
                ),
            )

    model = runtime.load_model(tmp_path, model_class=Model, reference_clip=reference)

    assert model.sr == 22050
    assert calls == [(reference, 0.0)]


@pytest.fixture
def fake_nano_installation(tmp_path, monkeypatch):
    assets = importlib.import_module("piper.nano_assets")
    install_root = tmp_path / "installation"
    asset_hash = hashlib.sha256(b"asset").hexdigest()
    monkeypatch.setattr(
        assets,
        "MODEL_FILE_SHA256",
        {name: asset_hash for name in assets.REQUIRED_MODEL_FILES},
    )
    paths = ["worker/NanoWorker.exe"] + [
        "model/" + name for name in assets.REQUIRED_MODEL_FILES
    ]
    files = {}
    for name in paths:
        target = install_root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"asset")
        files[name] = asset_hash
    (install_root / "manifest.json").write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "engine": "Chatterbox Nano",
                "source_revision": assets.SOURCE_REVISION,
                "model_revision": assets.MODEL_REVISION,
                "files": files,
            }
        )
    )
    return assets.inspect_nano_installation(install_root)


def test_worker_forwards_reference_clip_and_reports_ready_after_model_load(
    tmp_path, monkeypatch, fake_nano_installation
):
    main = importlib.import_module("piper.nano_worker.main")
    from piper.windows_tray.kokoro_protocol import read_frame, write_frame

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "profile"))
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.delenv("NUMBA_CACHE_DIR", raising=False)
    reference = _write_clip(tmp_path / "guide.wav")
    calls = []
    model = SimpleNamespace(sr=32000, effective_device="cpu", device_message="")

    def load_model(directory, reference_clip=None, **kwargs):
        calls.append((directory, reference_clip, kwargs))
        return model

    monkeypatch.setattr(main, "load_model", load_model)
    incoming, outgoing = io.BytesIO(), io.BytesIO()
    for frame in (
        {
            "type": "initialize",
            "manifest_sha256": fake_nano_installation.manifest_sha256,
            "device": "cuda",
            "reference_clip": str(reference.resolve()),
        },
        {"type": "shutdown"},
    ):
        write_frame(incoming, frame)
    incoming.seek(0)

    main.serve(fake_nano_installation.root, incoming, outgoing)

    outgoing.seek(0)
    assert read_frame(outgoing)["type"] == "hello"
    assert read_frame(outgoing)["type"] == "ready"
    assert calls == [
        (
            fake_nano_installation.model_dir,
            str(reference.resolve()),
            {"device": "cuda"},
        )
    ]


def test_worker_does_not_report_ready_when_custom_preparation_fails(
    tmp_path, monkeypatch, fake_nano_installation
):
    main = importlib.import_module("piper.nano_worker.main")
    from piper.windows_tray.kokoro_protocol import read_frame, write_frame

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "profile"))
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    reference = _write_clip(tmp_path / "guide.wav")
    calls = []

    def load_model(directory, reference_clip=None, **kwargs):
        calls.append(reference_clip)
        raise ValueError("reference preparation failed")

    monkeypatch.setattr(main, "load_model", load_model)
    incoming, outgoing = io.BytesIO(), io.BytesIO()
    for frame in (
        {
            "type": "initialize",
            "manifest_sha256": fake_nano_installation.manifest_sha256,
            "reference_clip": str(reference.resolve()),
        },
    ):
        write_frame(incoming, frame)
    incoming.seek(0)

    with pytest.raises(ValueError, match="reference preparation failed"):
        main.serve(fake_nano_installation.root, incoming, outgoing)

    outgoing.seek(0)
    assert read_frame(outgoing)["type"] == "hello"
    with pytest.raises(EOFError):
        read_frame(outgoing)
    assert calls == [str(reference.resolve())]


@pytest.mark.parametrize(
    "invalid_kind", ["wrong-type", "null", "relative", "missing"]
)
def test_worker_rejects_invalid_custom_reference_before_loading(
    tmp_path, monkeypatch, fake_nano_installation, invalid_kind
):
    main = importlib.import_module("piper.nano_worker.main")
    from piper.windows_tray.kokoro_protocol import read_frame, write_frame

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "profile"))
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    if invalid_kind == "wrong-type":
        reference = 7
    elif invalid_kind == "null":
        reference = None
    elif invalid_kind == "relative":
        reference = "guide.wav"
    else:
        reference = str((tmp_path / "missing.wav").resolve())
    load_called = []
    monkeypatch.setattr(
        main,
        "load_model",
        lambda *args, **kwargs: load_called.append((args, kwargs)),
    )
    incoming, outgoing = io.BytesIO(), io.BytesIO()
    write_frame(
        incoming,
        {
            "type": "initialize",
            "manifest_sha256": fake_nano_installation.manifest_sha256,
            "reference_clip": reference,
        },
    )
    incoming.seek(0)

    with pytest.raises(ValueError, match="reference clip"):
        main.serve(fake_nano_installation.root, incoming, outgoing)

    outgoing.seek(0)
    assert read_frame(outgoing)["type"] == "hello"
    with pytest.raises(EOFError):
        read_frame(outgoing)
    assert load_called == []


def test_nano_client_fails_readiness_when_worker_exits_before_ready(
    tmp_path, fake_nano_installation
):
    client_module = importlib.import_module("piper.windows_tray.nano_client")
    process = _Process(
        [{"type": "hello", "engine": "Chatterbox Nano", "protocol_version": 1}]
    )
    worker = client_module.NanoWorkerClient(
        fake_nano_installation, process_factory=lambda _: process
    )

    with pytest.raises(client_module.NanoUnavailable):
        worker.ensure_ready()

    assert process.killed
