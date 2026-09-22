"""Tray-side client for the queue-backed Kokoro worker protocol."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Lock, Thread
import time
from typing import Callable, Iterable, Iterator, Optional

from .kokoro_protocol import (
    PROTOCOL_VERSION,
    ProtocolError,
    decode_audio,
    read_frame,
    validate_hello,
    validate_response_frame,
    write_frame,
)


class KokoroUnavailable(RuntimeError):
    """Raised when the Kokoro worker cannot be used for a request."""


@dataclass(frozen=True)
class BackendSynthesisResult:
    """Backend-neutral streamed PCM result.

    The planned speech-backend module is not present in this checkout yet, so
    the Task 3 contract is kept local until that shared module is introduced.
    """

    sample_rate: int
    chunks: Iterable[bytes]


_EOF = object()
_HANDSHAKE_TIMEOUT_SECONDS = 5.0
_RESPONSE_POLL_SECONDS = 0.05
_CANCEL_TIMEOUT_SECONDS = 2.0


@dataclass(frozen=True)
class KokoroWorkerConfig:
    executable: Path
    install_root: Path
    manifest_sha256: str
    worker_version: str
    kokoro_version: str


class _FrameInbox:
    """Decode blocking worker output on a daemon thread into a queue."""

    def __init__(self, stream) -> None:
        self._stream = stream
        self._queue = Queue()
        self._thread = Thread(
            target=self._read_forever,
            name="kokoro-response-reader",
            daemon=True,
        )
        self._thread.start()

    def _read_forever(self) -> None:
        try:
            while True:
                self._queue.put(read_frame(self._stream))
        except EOFError:
            self._queue.put(_EOF)
        except BaseException as error:
            self._queue.put(error)

    def get(self, timeout: float):
        return self._queue.get(timeout=timeout)


class KokoroWorkerClient:
    def __init__(
        self,
        config: KokoroWorkerConfig,
        voice_id: str,
        process_factory: Optional[Callable[[KokoroWorkerConfig], object]] = None,
        *,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config
        self._voice_id = voice_id
        self._process_factory = process_factory
        self._sleep = sleep
        self._monotonic = monotonic
        self._process: Optional[object] = None
        self._inbox: Optional[_FrameInbox] = None
        self._request_id = 0
        self._lock = Lock()
        self._terminal_request_ids = set()
        self._expected_protocol_version = PROTOCOL_VERSION

    def ensure_ready(self) -> None:
        self._ensure_ready()

    def synthesize(self, text: str, cancel_event: Event) -> BackendSynthesisResult:
        self.ensure_ready()
        request_id = self._next_request_id()
        self._send(
            {
                "type": "synthesize",
                "request_id": request_id,
                "text": text,
                "voice_id": self._voice_id,
            }
        )
        return BackendSynthesisResult(
            sample_rate=24000,
            chunks=self._response_chunks(request_id, cancel_event),
        )

    def _next_request_id(self) -> int:
        with self._lock:
            self._request_id += 1
            return self._request_id

    def _send(self, message) -> None:
        process = self._process
        if process is None or process.stdin is None:
            raise KokoroUnavailable("Kokoro worker is not running")
        try:
            write_frame(process.stdin, message)
        except (OSError, ProtocolError) as error:
            raise KokoroUnavailable("Kokoro worker request failed") from error

    def _next_frame(self, timeout: float, *, response: bool = False):
        inbox = self._inbox
        if inbox is None:
            raise KokoroUnavailable("Kokoro worker response pipe is not ready")
        try:
            item = inbox.get(timeout=timeout)
        except Empty:
            return None
        if item is _EOF:
            raise KokoroUnavailable("Kokoro worker response pipe closed")
        if isinstance(item, BaseException):
            raise KokoroUnavailable("Kokoro worker response reader failed") from item
        if response:
            try:
                validate_response_frame(item)
            except ProtocolError as error:
                raise KokoroUnavailable("Kokoro worker sent an invalid response") from error
        return item

    def _ensure_ready(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return
        if self._process_factory is None:
            from .kokoro_process import launch_kokoro_worker

            self._process_factory = launch_kokoro_worker
        try:
            process = self._process_factory(self._config)
        except Exception as error:
            raise KokoroUnavailable("Kokoro worker could not be started") from error
        if process.stdout is None:
            raise KokoroUnavailable("Kokoro worker stdout pipe is unavailable")
        self._process = process
        self._inbox = _FrameInbox(process.stdout)

        hello = self._next_frame(_HANDSHAKE_TIMEOUT_SECONDS)
        if hello is None:
            raise KokoroUnavailable("Kokoro worker handshake timed out")
        try:
            validate_hello(hello)
        except ProtocolError as error:
            raise KokoroUnavailable("Kokoro worker protocol compatibility failure") from error
        if (
            hello.get("protocol_version") != self._expected_protocol_version
            or hello.get("worker_version") != self._config.worker_version
            or hello.get("kokoro_version") != self._config.kokoro_version
        ):
            raise KokoroUnavailable("Kokoro worker protocol compatibility failure")

        self._send(
            {
                "type": "initialize",
                "manifest_sha256": self._config.manifest_sha256,
            }
        )
        ready = self._next_frame(_HANDSHAKE_TIMEOUT_SECONDS)
        if ready is None or ready.get("type") != "ready":
            raise KokoroUnavailable("Kokoro worker did not become ready")

    def _record_terminal(self, request_id: int) -> None:
        if request_id in self._terminal_request_ids:
            raise RuntimeError("duplicate Kokoro terminal frame")
        self._terminal_request_ids.add(request_id)

    def _response_chunks(self, request_id: int, cancel_event: Event) -> Iterator[bytes]:
        cancel_sent = False
        cancel_deadline = None
        while True:
            if cancel_event.is_set() and not cancel_sent:
                self._send({"type": "cancel", "request_id": request_id})
                cancel_sent = True
                cancel_deadline = self._monotonic() + _CANCEL_TIMEOUT_SECONDS

            frame = self._next_frame(_RESPONSE_POLL_SECONDS, response=True)
            if frame is None:
                if (
                    cancel_sent
                    and cancel_deadline is not None
                    and self._monotonic() >= cancel_deadline
                ):
                    raise KokoroUnavailable("Kokoro worker cancellation timed out")
                continue
            frame_request_id = frame.get("request_id")
            frame_type = frame.get("type")
            if frame_type in {"response_end", "response_error", "response_cancelled"}:
                self._record_terminal(int(frame_request_id))
            if frame_request_id != request_id:
                continue
            if frame_type == "audio":
                if not cancel_sent:
                    yield decode_audio(frame["audio"])
                continue
            if frame_type == "response_end" or frame_type == "response_cancelled":
                return
            if frame_type == "response_error":
                raise RuntimeError("Kokoro synthesis failed: %s" % frame.get("category"))
