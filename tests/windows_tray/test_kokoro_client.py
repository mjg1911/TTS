import io
import subprocess
import time
from pathlib import Path
from threading import Condition, Event, Thread

import pytest

import piper.windows_tray.kokoro_client as kokoro_client_module
from piper.windows_tray.kokoro_client import (
    KokoroUnavailable,
    KokoroWorkerClient,
    KokoroWorkerConfig,
)
from piper.windows_tray.kokoro_protocol import encode_audio, read_frame, write_frame


SENTINEL = "SENTINEL_PRIVATE_TEXT_91f0"


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
        self.wait_calls = 0
        for message in messages:
            self.stdout.feed_message(message)

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        del timeout
        self.wait_calls += 1
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


def _wait_until(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_client_rejects_protocol_version_mismatch():
    process = FakeProcess([
        {"type": "hello", "protocol_version": 2, "worker_version": "1", "kokoro_version": "0.9.4"}
    ])
    with pytest.raises(KokoroUnavailable, match="protocol"):
        make_client(process).synthesize("hello", Event())


def test_client_rejects_oversized_text_before_writing_a_request():
    process = ready_process()
    client = make_client(process)

    with pytest.raises(KokoroUnavailable, match="request"):
        client.synthesize("x" * (1024 * 1024 + 1), Event())

    assert process.stdin.getvalue() == b""


def test_failed_live_handshake_cleans_up_job_before_raising():
    failed = FakeProcess([
        {"type": "hello", "protocol_version": 2, "worker_version": "1", "kokoro_version": "0.9.4"}
    ])
    closed = []
    failed._piper_kokoro_job = type(
        "TrackingJob", (), {"close": lambda self: closed.append(True)}
    )()
    client = KokoroWorkerClient(
        KokoroWorkerConfig(Path("KokoroWorker.exe"), Path("Kokoro"), "a" * 64, "1", "0.9.4"),
        "af_heart",
        lambda _config: failed,
        sleep=lambda _delay: None,
    )

    with pytest.raises(KokoroUnavailable, match="protocol"):
        client.synthesize("hello", Event())
    assert failed.terminated
    assert not failed.killed
    assert failed.wait_calls == 1
    assert closed == [True]
    assert client._process is None
    assert client._inbox is None


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


def test_client_allows_slow_worker_initialization(monkeypatch):
    monkeypatch.setattr(kokoro_client_module, "_HANDSHAKE_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(
        kokoro_client_module, "_INITIALIZATION_TIMEOUT_SECONDS", 0.1, raising=False
    )
    process = FakeProcess([
        {"type": "hello", "protocol_version": 1, "worker_version": "1", "kokoro_version": "0.9.4"},
    ])
    Thread(
        target=lambda: (
            time.sleep(0.03), process.stdout.feed_message({"type": "ready"})
        ),
        daemon=True,
    ).start()

    make_client(process).ensure_ready()


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


def test_client_protocol_failure_does_not_expose_source_text(caplog):
    process = ready_process(
        {"type": "response_error", "request_id": 1, "category": "inference"}
    )
    result = make_client(process).synthesize(SENTINEL, Event())
    with pytest.raises(RuntimeError):
        list(result.chunks)
    assert SENTINEL not in caplog.text
    assert SENTINEL not in process.stderr.getvalue().decode("utf-8", errors="replace")


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


def test_cancel_is_forwarded_while_worker_has_not_produced_another_frame():
    process = FakeProcess([
        {"type": "hello", "protocol_version": 1, "worker_version": "1", "kokoro_version": "0.9.4"},
        {"type": "ready"},
    ])
    cancelled = Event()
    result = make_client(process).synthesize("hello", cancelled)
    consumed = []
    thread = Thread(target=lambda: consumed.append(list(result.chunks)), daemon=True)
    thread.start()

    cancelled.set()
    assert _wait_until(
        lambda: {"type": "cancel", "request_id": 1} in written_messages(process)
    )
    process.stdout.feed_message({"type": "response_cancelled", "request_id": 1})
    thread.join(1.0)

    assert not thread.is_alive()
    assert consumed == [[]]


def test_cancel_event_sends_exactly_one_cancel_for_active_request():
    process = FakeProcess([
        {"type": "hello", "protocol_version": 1, "worker_version": "1", "kokoro_version": "0.9.4"},
        {"type": "ready"},
    ])
    cancelled = Event()
    result = make_client(process).synthesize("hello", cancelled)
    thread = Thread(target=lambda: list(result.chunks), daemon=True)
    thread.start()

    cancelled.set()
    assert _wait_until(
        lambda: len([m for m in written_messages(process) if m["type"] == "cancel"]) == 1
    )
    process.stdout.feed_message(
        {"type": "audio", "request_id": 1, "audio": encode_audio(b"\x05\x00")}
    )
    time.sleep(0.1)
    assert len([m for m in written_messages(process) if m["type"] == "cancel"]) == 1
    process.stdout.feed_message({"type": "response_end", "request_id": 1})
    thread.join(1.0)


def test_audio_after_cancel_is_not_yielded():
    process = FakeProcess([
        {"type": "hello", "protocol_version": 1, "worker_version": "1", "kokoro_version": "0.9.4"},
        {"type": "ready"},
    ])
    cancelled = Event()
    result = make_client(process).synthesize("hello", cancelled)
    consumed = []
    thread = Thread(target=lambda: consumed.extend(result.chunks), daemon=True)
    thread.start()
    cancelled.set()
    assert _wait_until(
        lambda: {"type": "cancel", "request_id": 1} in written_messages(process)
    )
    process.stdout.feed_message(
        {"type": "audio", "request_id": 1, "audio": encode_audio(b"\x05\x00")}
    )
    process.stdout.feed_message({"type": "response_cancelled", "request_id": 1})
    thread.join(1.0)
    assert consumed == []


def ready_process(*responses):
    return FakeProcess([
        {"type": "hello", "protocol_version": 1, "worker_version": "1", "kokoro_version": "0.9.4"},
        {"type": "ready"},
        *responses,
    ])


def test_worker_starts_lazily_on_first_synthesis():
    process = ready_process({"type": "response_end", "request_id": 1})
    starts = []
    client = KokoroWorkerClient(
        KokoroWorkerConfig(Path("KokoroWorker.exe"), Path("Kokoro"), "a" * 64, "1", "0.9.4"),
        "af_heart",
        lambda config: starts.append(config) or process,
    )
    assert starts == []
    assert list(client.synthesize("hello", Event()).chunks) == []
    assert len(starts) == 1


def test_worker_is_reused_between_successful_requests():
    process = ready_process(
        {"type": "response_end", "request_id": 1},
        {"type": "response_end", "request_id": 2},
    )
    starts = []
    client = KokoroWorkerClient(
        KokoroWorkerConfig(Path("KokoroWorker.exe"), Path("Kokoro"), "a" * 64, "1", "0.9.4"),
        "af_heart",
        lambda config: starts.append(config) or process,
    )
    assert list(client.synthesize("one", Event()).chunks) == []
    assert list(client.synthesize("two", Event()).chunks) == []
    assert len(starts) == 1


def test_crash_restarts_with_increasing_short_backoff():
    dead = ready_process()
    dead.returncode = 1
    live = ready_process({"type": "response_end", "request_id": 1})
    processes = iter([dead, live])
    sleeps = []
    client = KokoroWorkerClient(
        KokoroWorkerConfig(Path("KokoroWorker.exe"), Path("Kokoro"), "a" * 64, "1", "0.9.4"),
        "af_heart",
        lambda _config: next(processes),
        sleep=sleeps.append,
    )
    assert list(client.synthesize("hello", Event()).chunks) == []
    assert sleeps == [0.1]


def test_restart_budget_marks_kokoro_unavailable_for_session():
    starts = []

    def factory(_config):
        process = ready_process()
        process.returncode = 1
        starts.append(process)
        return process

    client = KokoroWorkerClient(
        KokoroWorkerConfig(Path("KokoroWorker.exe"), Path("Kokoro"), "a" * 64, "1", "0.9.4"),
        "af_heart",
        factory,
        sleep=lambda _delay: None,
    )
    with pytest.raises(KokoroUnavailable):
        client.synthesize("hello", Event())
    count = len(starts)
    with pytest.raises(KokoroUnavailable):
        client.synthesize("again", Event())
    assert len(starts) == count


def test_shutdown_sends_shutdown_and_waits_for_exit():
    process = ready_process({"type": "response_end", "request_id": 1})
    closed = []
    process._piper_kokoro_job = type(
        "TrackingJob", (), {"close": lambda self: closed.append(True)}
    )()
    client = make_client(process)
    assert list(client.synthesize("hello", Event()).chunks) == []
    client.shutdown()
    assert written_messages(process)[-1]["type"] == "shutdown"
    assert not process.killed
    assert process.poll() is not None
    assert process.wait_calls == 1
    assert closed == [True]


def test_shutdown_synchronizes_with_process_creation_before_returning():
    process_creation_started = Event()
    allow_process_creation_to_finish = Event()
    shutdown_started = Event()
    shutdown_finished = Event()
    cancel_event = Event()
    processes = []
    process = ready_process()

    def process_factory(_config):
        process_creation_started.set()
        assert allow_process_creation_to_finish.wait(1.0)
        processes.append(process)
        return process

    client = KokoroWorkerClient(
        KokoroWorkerConfig(Path("KokoroWorker.exe"), Path("Kokoro"), "a" * 64, "1", "0.9.4"),
        "af_heart",
        process_factory,
        sleep=lambda _delay: None,
    )

    readiness_errors = []

    def ensure_ready():
        try:
            client.ensure_ready(cancel_event)
        except KokoroUnavailable as error:
            readiness_errors.append(error)

    readiness = Thread(target=ensure_ready, daemon=True)
    readiness.start()
    assert process_creation_started.wait(1.0)

    def cancel_startup():
        cancel_event.set()
        shutdown_started.set()
        client.shutdown()
        shutdown_finished.set()

    shutdown = Thread(target=cancel_startup, daemon=True)
    shutdown.start()
    assert shutdown_started.wait(1.0)
    assert shutdown_finished.wait(0.05) is False

    allow_process_creation_to_finish.set()
    readiness.join(1.0)
    shutdown.join(1.0)

    assert not readiness.is_alive()
    assert not shutdown.is_alive()
    assert shutdown_finished.is_set()
    assert processes == [process]
    assert client._process is None
    assert process.terminated
    assert process.wait_calls == 1
    assert len(readiness_errors) == 1
    with pytest.raises(KokoroUnavailable):
        client.ensure_ready()
    assert processes == [process]


def test_shutdown_during_restart_backoff_prevents_another_process_launch():
    backoff_started = Event()
    release_backoff = Event()
    processes = []
    dead_process = ready_process()
    dead_process.returncode = 1
    replacement = ready_process()

    def process_factory(_config):
        process = dead_process if not processes else replacement
        processes.append(process)
        return process

    def sleep(_delay):
        backoff_started.set()
        assert release_backoff.wait(1.0)

    client = KokoroWorkerClient(
        KokoroWorkerConfig(Path("KokoroWorker.exe"), Path("Kokoro"), "a" * 64, "1", "0.9.4"),
        "af_heart",
        process_factory,
        sleep=sleep,
    )
    errors = []

    def ensure_ready():
        try:
            client.ensure_ready()
        except KokoroUnavailable as error:
            errors.append(error)

    readiness = Thread(target=ensure_ready, daemon=True)
    readiness.start()
    assert backoff_started.wait(1.0)

    client.shutdown()
    release_backoff.set()
    readiness.join(1.0)

    assert not readiness.is_alive()
    assert len(errors) == 1
    assert processes == [dead_process]
    assert client._process is None
    with pytest.raises(KokoroUnavailable):
        client.ensure_ready()
    assert processes == [dead_process]


def test_synthesize_cancellation_during_restart_backoff_prevents_replacement_launch():
    backoff_started = Event()
    release_backoff = Event()
    cancel_event = Event()
    dead_process = ready_process()
    dead_process.returncode = 1
    replacement = ready_process({"type": "response_end", "request_id": 1})
    processes = []

    def process_factory(_config):
        process = dead_process if not processes else replacement
        processes.append(process)
        return process

    def sleep(_delay):
        backoff_started.set()
        assert release_backoff.wait(1.0)

    client = KokoroWorkerClient(
        KokoroWorkerConfig(Path("KokoroWorker.exe"), Path("Kokoro"), "a" * 64, "1", "0.9.4"),
        "af_heart",
        process_factory,
        sleep=sleep,
    )
    errors = []

    def synthesize():
        try:
            client.synthesize("hello", cancel_event)
        except KokoroUnavailable as error:
            errors.append(error)

    request = Thread(target=synthesize, daemon=True)
    request.start()
    assert backoff_started.wait(1.0)

    cancel_event.set()
    release_backoff.set()
    request.join(1.0)

    assert not request.is_alive()
    assert len(errors) == 1
    assert "cancelled" in str(errors[0])
    assert processes == [dead_process]


def test_shutdown_kills_worker_after_timeout():
    class HangingProcess(FakeProcess):
        def wait(self, timeout=None):
            self.wait_calls += 1
            if not self.killed:
                raise subprocess.TimeoutExpired("KokoroWorker.exe", timeout)
            self.returncode = 1
            return self.returncode

    process = HangingProcess([
        {"type": "hello", "protocol_version": 1, "worker_version": "1", "kokoro_version": "0.9.4"},
        {"type": "ready"},
        {"type": "response_end", "request_id": 1},
    ])
    client = make_client(process)
    assert list(client.synthesize("hello", Event()).chunks) == []
    client.shutdown()
    assert process.killed
    assert process.poll() is not None
    assert process.wait_calls == 2


def test_shutdown_is_idempotent():
    process = ready_process({"type": "response_end", "request_id": 1})
    client = make_client(process)
    assert list(client.synthesize("hello", Event()).chunks) == []
    client.shutdown()
    client.shutdown()
    assert [m["type"] for m in written_messages(process)].count("shutdown") == 1


def test_pipe_eof_is_reported_as_recoverable_kokoro_failure():
    process = ready_process()
    result = make_client(process).synthesize("hello", Event())
    process.stdout.close_input()
    with pytest.raises(KokoroUnavailable, match="closed"):
        list(result.chunks)
