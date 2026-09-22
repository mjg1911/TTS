import io
from pathlib import Path
from threading import Condition, Event

import pytest

from piper.windows_tray.kokoro_client import (
    KokoroUnavailable,
    KokoroWorkerClient,
    KokoroWorkerConfig,
)
from piper.windows_tray.kokoro_protocol import encode_audio, read_frame, write_frame


class BlockingStream:
    def __init__(self):
        self._buffer = bytearray()
        self._closed = False
        self._condition = Condition()

    def feed_message(self, message):
        encoded = io.BytesIO()
        write_frame(encoded, message)
        with self._condition:
            self._buffer.extend(encoded.getvalue())
            self._condition.notify_all()

    def read(self, size=-1):
        if size < 0:
            raise AssertionError("protocol reader must request a bounded byte count")
        with self._condition:
            while len(self._buffer) < size and not self._closed:
                self._condition.wait()
            if not self._buffer and self._closed:
                return b""
            count = min(size, len(self._buffer))
            result = bytes(self._buffer[:count])
            del self._buffer[:count]
            return result

    def close_input(self):
        with self._condition:
            self._closed = True
            self._condition.notify_all()


class FakeProcess:
    def __init__(self, messages=()):
        self.stdin = io.BytesIO()
        self.stdout = BlockingStream()
        self.stderr = io.BytesIO()
        self.returncode = None
        self.terminated = False
        self.killed = False
        for message in messages:
            self.stdout.feed_message(message)

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        del timeout
        if self.returncode is None:
            self.returncode = 0
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 1
        self.stdout.close_input()

    def kill(self):
        self.killed = True
        self.returncode = 1
        self.stdout.close_input()


def make_client(process, *, expected_protocol=1):
    config = KokoroWorkerConfig(
        executable=Path("KokoroWorker.exe"),
        install_root=Path("Kokoro"),
        manifest_sha256="a" * 64,
        worker_version="1",
        kokoro_version="0.9.4",
    )
    client = KokoroWorkerClient(
        config,
        "af_heart",
        process_factory=lambda _config: process,
        sleep=lambda _delay: None,
    )
    client._expected_protocol_version = expected_protocol
    return client


def written_messages(process):
    stream = io.BytesIO(process.stdin.getvalue())
    messages = []
    while stream.tell() < len(stream.getvalue()):
        messages.append(read_frame(stream))
    return messages


def test_client_rejects_protocol_version_mismatch():
    process = FakeProcess([
        {"type": "hello", "protocol_version": 2, "worker_version": "1", "kokoro_version": "0.9.4"}
    ])
    with pytest.raises(KokoroUnavailable, match="protocol"):
        make_client(process).synthesize("hello", Event())


def test_client_waits_for_ready_before_synthesis():
    process = FakeProcess([
        {"type": "hello", "protocol_version": 1, "worker_version": "1", "kokoro_version": "0.9.4"},
        {"type": "ready"},
        {"type": "response_end", "request_id": 1},
    ])
    result = make_client(process).synthesize("hello", Event())
    assert list(result.chunks) == []
    assert written_messages(process)[:2] == [
        {"type": "initialize", "manifest_sha256": "a" * 64},
        {"type": "synthesize", "request_id": 1, "text": "hello", "voice_id": "af_heart"},
    ]


def test_client_streams_audio_until_response_end():
    process = FakeProcess([
        {"type": "hello", "protocol_version": 1, "worker_version": "1", "kokoro_version": "0.9.4"},
        {"type": "ready"},
        {"type": "audio", "request_id": 1, "audio": encode_audio(b"\x01\x00")},
        {"type": "response_end", "request_id": 1},
    ])
    result = make_client(process).synthesize("hello", Event())
    assert result.sample_rate == 24000
    assert list(result.chunks) == [b"\x01\x00"]


def test_client_maps_response_error_to_synthesis_failure():
    process = FakeProcess([
        {"type": "hello", "protocol_version": 1, "worker_version": "1", "kokoro_version": "0.9.4"},
        {"type": "ready"},
        {"type": "response_error", "request_id": 1, "category": "inference"},
    ])
    result = make_client(process).synthesize("private text", Event())
    with pytest.raises(RuntimeError, match="inference"):
        list(result.chunks)


def test_client_ignores_stale_audio_for_previous_request():
    process = FakeProcess([
        {"type": "hello", "protocol_version": 1, "worker_version": "1", "kokoro_version": "0.9.4"},
        {"type": "ready"},
        {"type": "audio", "request_id": 99, "audio": encode_audio(b"\x09\x00")},
        {"type": "audio", "request_id": 1, "audio": encode_audio(b"\x01\x00")},
        {"type": "response_end", "request_id": 1},
    ])
    assert list(make_client(process).synthesize("hello", Event()).chunks) == [b"\x01\x00"]


def test_client_rejects_duplicate_terminal_frame_before_next_request():
    process = FakeProcess([
        {"type": "hello", "protocol_version": 1, "worker_version": "1", "kokoro_version": "0.9.4"},
        {"type": "ready"},
        {"type": "response_end", "request_id": 1},
        {"type": "response_end", "request_id": 1},
        {"type": "response_end", "request_id": 2},
    ])
    client = make_client(process)
    assert list(client.synthesize("first", Event()).chunks) == []
    with pytest.raises(RuntimeError, match="terminal"):
        list(client.synthesize("second", Event()).chunks)
