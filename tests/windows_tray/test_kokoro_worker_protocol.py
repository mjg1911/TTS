import io
from pathlib import Path
from types import SimpleNamespace

import pytest

from piper.kokoro_worker import main as worker_main
from piper.windows_tray.kokoro_protocol import ProtocolError, read_frame, write_frame


SENTINEL = "SENTINEL_PRIVATE_TEXT_91f0"


def framed_input(*messages):
    stream = io.BytesIO()
    for message in messages:
        write_frame(stream, message)
    stream.seek(0)
    return stream


def read_all(stream):
    stream.seek(0)
    messages = []
    while stream.tell() < len(stream.getvalue()):
        messages.append(read_frame(stream))
    return messages


class FakeRuntime:
    instances = []

    def __init__(self, config_path, model_path, voices):
        self.config_path = config_path
        self.model_path = model_path
        self.voices = voices
        self.loaded = False
        type(self).instances.append(self)

    def load(self):
        self.loaded = True

    def synthesize_segments(self, text, voice_id):
        if text == "explode":
            raise RuntimeError("SENTINEL_MUST_NOT_REACH_STDERR")
        yield b"\x01\x00"
        yield b"\x02\x00"


def fake_installation(root: Path, manifest_sha256: str = "a" * 64):
    return SimpleNamespace(
        root=root,
        manifest_sha256=manifest_sha256,
        config_path=root / "model" / "config.json",
        model_path=root / "model" / "kokoro-v1_0.pth",
        voices={"af_heart": object()},
    )


def initialize_message():
    return {"type": "initialize", "manifest_sha256": "a" * 64}


def test_worker_hello_ready_audio_end_and_shutdown(monkeypatch, tmp_path):
    FakeRuntime.instances.clear()
    monkeypatch.setattr(worker_main, "KokoroRuntime", FakeRuntime)
    monkeypatch.setattr(worker_main, "inspect_kokoro_installation", lambda root: fake_installation(root))
    stdin = framed_input(
        initialize_message(),
        {"type": "synthesize", "request_id": 1, "text": "hello", "voice_id": "af_heart"},
        {"type": "shutdown"},
    )
    stdout = io.BytesIO()
    stderr = io.StringIO()
    assert worker_main.main(stdin, stdout, stderr, install_root=tmp_path) == 0
    messages = read_all(stdout)
    assert messages[0]["type"] == "hello"
    assert messages[1] == {"type": "ready"}
    assert [message["type"] for message in messages[2:]] == ["audio", "audio", "response_end"]
    runtime = FakeRuntime.instances[0]
    assert runtime.config_path == tmp_path / "model" / "config.json"
    assert runtime.model_path == tmp_path / "model" / "kokoro-v1_0.pth"
    assert stderr.getvalue() == ""


def test_worker_initialize_does_not_call_full_verifier(monkeypatch, tmp_path):
    FakeRuntime.instances.clear()
    monkeypatch.setattr(worker_main, "KokoroRuntime", FakeRuntime)
    monkeypatch.setattr(
        worker_main,
        "inspect_kokoro_installation",
        lambda root: fake_installation(root),
    )
    monkeypatch.setattr(
        worker_main,
        "verify_kokoro_installation",
        lambda _root: (_ for _ in ()).throw(
            AssertionError("worker initialization must not run full verification")
        ),
        raising=False,
    )

    stdin = framed_input(initialize_message(), {"type": "shutdown"})
    assert worker_main.main(
        stdin, io.BytesIO(), io.StringIO(), install_root=tmp_path
    ) == 0


def test_worker_rejects_manifest_fingerprint_mismatch(monkeypatch, tmp_path):
    monkeypatch.setattr(worker_main, "inspect_kokoro_installation", lambda root: fake_installation(root, "b" * 64))
    with pytest.raises(ProtocolError, match="manifest fingerprint mismatch"):
        worker_main.main(framed_input(initialize_message()), io.BytesIO(), io.StringIO(), install_root=tmp_path)


def test_worker_rejects_protocol_supplied_asset_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(worker_main, "inspect_kokoro_installation", lambda root: fake_installation(root))
    malicious = {"type": "initialize", "manifest_sha256": "a" * 64, "model_path": r"C:\other\model.pth"}
    with pytest.raises(ProtocolError, match="unsupported fields"):
        worker_main.main(framed_input(malicious), io.BytesIO(), io.StringIO(), install_root=tmp_path)


def test_worker_runtime_error_returns_category_without_text(monkeypatch, tmp_path):
    monkeypatch.setattr(worker_main, "KokoroRuntime", FakeRuntime)
    monkeypatch.setattr(worker_main, "inspect_kokoro_installation", lambda root: fake_installation(root))
    stdin = framed_input(
        initialize_message(),
        {"type": "synthesize", "request_id": 2, "text": "explode", "voice_id": "af_heart"},
        {"type": "shutdown"},
    )
    stdout = io.BytesIO()
    stderr = io.StringIO()
    assert worker_main.main(stdin, stdout, stderr, install_root=tmp_path) == 0
    error = read_all(stdout)[-1]
    assert error["type"] == "response_error"
    assert error["request_id"] == 2
    assert error["category"] == "inference"
    assert "explode" not in stderr.getvalue()
    assert "SENTINEL_MUST_NOT_REACH_STDERR" not in stderr.getvalue()


def test_worker_runtime_failure_stderr_omits_source_text(monkeypatch, tmp_path):
    class FailingRuntime(FakeRuntime):
        def synthesize_segments(self, text, voice_id):
            assert text == SENTINEL
            raise RuntimeError("inference exploded")
            yield b""

    monkeypatch.setattr(worker_main, "KokoroRuntime", FailingRuntime)
    monkeypatch.setattr(
        worker_main,
        "inspect_kokoro_installation",
        lambda root: fake_installation(root),
    )
    stdin = framed_input(
        initialize_message(),
        {"type": "synthesize", "request_id": 9, "text": SENTINEL, "voice_id": "af_heart"},
        {"type": "shutdown"},
    )
    stdout = io.BytesIO()
    stderr = io.StringIO()
    assert worker_main.main(stdin, stdout, stderr, install_root=tmp_path) == 0
    assert SENTINEL not in stderr.getvalue()
    assert "request_id=9" in stderr.getvalue()


def test_worker_cancel_discards_segment_completed_after_cancel(monkeypatch, tmp_path):
    monkeypatch.setattr(worker_main, "KokoroRuntime", FakeRuntime)
    monkeypatch.setattr(worker_main, "inspect_kokoro_installation", lambda root: fake_installation(root))
    stdin = framed_input(
        initialize_message(),
        {"type": "synthesize", "request_id": 3, "text": "hello", "voice_id": "af_heart"},
        {"type": "cancel", "request_id": 3},
        {"type": "shutdown"},
    )
    stdout = io.BytesIO()
    assert worker_main.main(stdin, stdout, io.StringIO(), install_root=tmp_path) == 0
    messages = read_all(stdout)
    assert {"type": "response_cancelled", "request_id": 3} in messages
    assert not any(message["type"] == "audio" and message.get("request_id") == 3 for message in messages)
