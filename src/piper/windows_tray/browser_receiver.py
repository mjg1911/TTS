from __future__ import annotations

from collections import deque
from enum import Enum, auto
import logging
import secrets
import threading
import time
from typing import Callable
from uuid import uuid4

from websockets.exceptions import ConnectionClosed
from websockets.sync.server import Server, serve

from .browser_protocol import (
    AUTH_TIMEOUT_SECONDS,
    ClientMessage,
    LISTEN_HOST,
    LISTEN_PORT,
    MAX_MESSAGES_PER_10_SECONDS,
    MAX_WIRE_MESSAGE_BYTES,
    HelloMessage,
    KeepaliveMessage,
    ProtocolError,
    ProtocolVersionError,
    hello_ack,
    parse_client_message,
)
from .browser_speech import BrowserMessageOutcome
from .logging_setup import log_browser_status


_LOGGER = logging.getLogger(__name__)


class _MetadataOnlyTransportFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= logging.WARNING


_TRANSPORT_LOGGER = logging.getLogger(
    "piper.windows_tray.browser_receiver.transport"
)
_TRANSPORT_LOGGER.setLevel(logging.WARNING)
_TRANSPORT_LOGGER.propagate = False
_TRANSPORT_LOGGER.addFilter(_MetadataOnlyTransportFilter())
if not _TRANSPORT_LOGGER.handlers:
    _TRANSPORT_LOGGER.addHandler(logging.NullHandler())


class BrowserReceiverStatus(Enum):
    DISABLED = auto()
    WAITING = auto()
    CONNECTED = auto()
    TEMPORARILY_UNAVAILABLE = auto()
    UNSUPPORTED_PROTOCOL = auto()


class BrowserReceiver:
    def __init__(
        self,
        on_message: Callable[[ClientMessage], BrowserMessageOutcome],
        on_status: Callable[[BrowserReceiverStatus], None],
        *,
        host: str = LISTEN_HOST,
        port: int = LISTEN_PORT,
    ) -> None:
        if host not in {"127.0.0.1", "localhost"}:
            raise ValueError("browser receiver must bind to loopback")
        self._on_message = on_message
        self._on_status = on_status
        self._host = host
        self._port = port
        self._server_instance_id = str(uuid4())
        self._lock = threading.RLock()
        self._server: Server | None = None
        self._thread: threading.Thread | None = None
        self._token: str | None = None
        self._run_generation = 0
        self._server_generation: int | None = None
        self._client_owned = False
        self._client_generation: int | None = None
        self._clients: dict[object, int] = {}
        self._client_threads: dict[object, threading.Thread] = {}
        self._stopping = False

    def start(self, token: str) -> None:
        with self._lock:
            if self._server is not None:
                raise RuntimeError("browser receiver is already running")
            self._run_generation += 1
            generation = self._run_generation
            self._token = token
            self._stopping = False
            try:
                server = serve(
                    self._handle_connection,
                    self._host,
                    self._port,
                    compression=None,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=2,
                    max_size=MAX_WIRE_MESSAGE_BYTES,
                    max_queue=8,
                    logger=_TRANSPORT_LOGGER,
                )
            except Exception:
                self._token = None
                self._server = None
                self._thread = None
                self._server_generation = None
                self._stopping = True
                raise
            self._server = server
            self._server_generation = generation
            ready = threading.Event()
            self._thread = threading.Thread(
                target=self._serve_forever,
                args=(server, generation, ready),
                name="piper-browser-websocket",
                daemon=True,
            )
            self._thread.start()
            ready.wait(timeout=1)
            self._emit_status_locked(BrowserReceiverStatus.WAITING, generation=generation)

    def stop(self) -> None:
        with self._lock:
            self._stopping = True
            self._token = None
            self._client_owned = False
            self._client_generation = None
            server, thread = self._server, self._thread
            clients = list(self._clients)
            client_threads = list(self._client_threads.values())
            self._server = None
            self._thread = None
            self._server_generation = None
        for websocket in clients:
            try:
                websocket.close(code=1001, reason="browser receiver stopped")
            except Exception:
                pass
        try:
            if server is not None:
                server.shutdown()
        finally:
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=5)
            for client_thread in client_threads:
                if client_thread is not threading.current_thread():
                    client_thread.join(timeout=5)
            with self._lock:
                self._emit_status_locked(BrowserReceiverStatus.DISABLED)

    def _handle_connection(self, websocket) -> None:
        with self._lock:
            if (
                self._stopping
                or self._server is None
                or self._server_generation is None
                or self._client_owned
            ):
                websocket.close(code=1013, reason="browser receiver unavailable")
                return
            generation = self._server_generation
            self._client_owned = True
            self._client_generation = generation
            self._clients[websocket] = generation
            self._client_threads[websocket] = threading.current_thread()
            token = self._token

        authenticated = False
        disconnected = False
        timestamps: deque[float] = deque()
        try:
            try:
                raw = websocket.recv(timeout=AUTH_TIMEOUT_SECONDS)
                self._record_message_or_raise(timestamps)
                message = parse_client_message(raw)
            except TimeoutError:
                websocket.close(code=1008, reason="authentication timeout")
                return
            except ProtocolVersionError:
                with self._lock:
                    self._emit_status_locked(
                        BrowserReceiverStatus.UNSUPPORTED_PROTOCOL,
                        generation=generation,
                        require_running=True,
                    )
                websocket.close(code=1002, reason="unsupported protocol")
                return
            except ProtocolError:
                websocket.close(code=1008, reason="invalid message")
                return

            if not self._connection_is_active(websocket, generation):
                return
            if not isinstance(message, HelloMessage):
                websocket.close(code=1008, reason="authentication required")
                return
            if token is None or not secrets.compare_digest(message.auth_token, token):
                websocket.close(code=1008, reason="authentication failed")
                return

            with self._lock:
                if not self._connection_is_active_locked(websocket, generation):
                    return
                authenticated = True
                self._emit_status_locked(
                    BrowserReceiverStatus.CONNECTED,
                    generation=generation,
                    require_running=True,
                )
                websocket.send(hello_ack(self._server_instance_id))

            while True:
                try:
                    raw = websocket.recv()
                    self._record_message_or_raise(timestamps)
                    if not self._connection_is_active(websocket, generation):
                        return
                    message = parse_client_message(raw)
                except ConnectionClosed:
                    disconnected = True
                    return
                except ProtocolVersionError:
                    with self._lock:
                        self._emit_status_locked(
                            BrowserReceiverStatus.UNSUPPORTED_PROTOCOL,
                            generation=generation,
                            require_running=True,
                        )
                    websocket.close(code=1002, reason="unsupported protocol")
                    return
                except ProtocolError:
                    websocket.close(code=1008, reason="invalid message")
                    return

                if isinstance(message, HelloMessage):
                    websocket.close(code=1008, reason="already authenticated")
                    return
                if isinstance(message, KeepaliveMessage):
                    continue
                with self._lock:
                    if not self._connection_is_active_locked(websocket, generation):
                        return
                    outcome = self._on_message(message)
                    log_browser_status(
                        _LOGGER,
                        status="DISPATCHED",
                        queue_size=0,
                        outcome=getattr(outcome, "name", type(outcome).__name__),
                    )
        except ConnectionClosed:
            disconnected = True
            return
        finally:
            self._release_client(
                websocket,
                generation,
                authenticated=authenticated,
                disconnected=disconnected,
            )

    def _record_message_or_raise(self, timestamps: deque[float]) -> None:
        now = time.monotonic()
        cutoff = now - 10.0
        while timestamps and timestamps[0] < cutoff:
            timestamps.popleft()
        timestamps.append(now)
        if len(timestamps) > MAX_MESSAGES_PER_10_SECONDS:
            raise ProtocolError("browser message rate exceeded")

    def _serve_forever(
        self,
        server: Server,
        generation: int,
        ready: threading.Event,
    ) -> None:
        with self._lock:
            if self._server is server and self._server_generation == generation:
                ready.set()
        server.serve_forever()

    def _connection_is_active(self, websocket, generation: int) -> bool:
        with self._lock:
            return self._connection_is_active_locked(websocket, generation)

    def _connection_is_active_locked(self, websocket, generation: int) -> bool:
        return (
            not self._stopping
            and self._server is not None
            and self._server_generation == generation
            and self._client_owned
            and self._client_generation == generation
            and self._clients.get(websocket) == generation
        )

    def _release_client(
        self,
        websocket,
        generation: int,
        *,
        authenticated: bool,
        disconnected: bool,
    ) -> None:
        with self._lock:
            if self._clients.get(websocket) == generation:
                del self._clients[websocket]
                self._client_threads.pop(websocket, None)
            owns_current_client = (
                self._client_owned
                and self._client_generation == generation
                and self._server_generation == generation
            )
            if owns_current_client:
                self._client_owned = False
                self._client_generation = None
            if authenticated and disconnected and owns_current_client:
                self._emit_status_locked(
                    BrowserReceiverStatus.TEMPORARILY_UNAVAILABLE,
                    generation=generation,
                    require_running=True,
                )

    def _emit_status_locked(
        self,
        status: BrowserReceiverStatus,
        *,
        generation: int | None = None,
        require_running: bool = False,
    ) -> bool:
        if generation is not None and self._server_generation != generation:
            return False
        if require_running and (self._stopping or self._server is None):
            return False
        log_browser_status(
            _LOGGER,
            status=status.name,
            queue_size=0,
        )
        self._on_status(status)
        return True
