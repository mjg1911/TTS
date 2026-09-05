from __future__ import annotations

from collections import deque
from enum import Enum, auto
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
        self._client_owned = False
        self._stopping = False

    def start(self, token: str) -> None:
        with self._lock:
            if self._server is not None:
                raise RuntimeError("browser receiver is already running")
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
                )
            except Exception:
                self._token = None
                self._server = None
                self._thread = None
                self._stopping = True
                raise
            self._server = server
            self._thread = threading.Thread(
                target=server.serve_forever,
                name="piper-browser-websocket",
                daemon=True,
            )
            self._thread.start()
        self._on_status(BrowserReceiverStatus.WAITING)

    def stop(self) -> None:
        with self._lock:
            self._stopping = True
            self._token = None
            self._client_owned = False
            server, thread = self._server, self._thread
            self._server = None
            self._thread = None
        if server is not None:
            server.shutdown()
        if thread is not None:
            thread.join(timeout=5)
        self._on_status(BrowserReceiverStatus.DISABLED)

    def _handle_connection(self, websocket) -> None:
        with self._lock:
            if self._stopping or self._client_owned:
                websocket.close(code=1013, reason="browser receiver unavailable")
                return
            self._client_owned = True
            token = self._token

        authenticated = False
        unexpected_disconnect = True
        timestamps: deque[float] = deque()
        try:
            try:
                raw = websocket.recv(timeout=AUTH_TIMEOUT_SECONDS)
                self._record_message_or_raise(timestamps)
                message = parse_client_message(raw)
            except TimeoutError:
                unexpected_disconnect = False
                websocket.close(code=1008, reason="authentication timeout")
                return
            except ProtocolVersionError:
                unexpected_disconnect = False
                self._on_status(BrowserReceiverStatus.UNSUPPORTED_PROTOCOL)
                websocket.close(code=1002, reason="unsupported protocol")
                return
            except ProtocolError:
                unexpected_disconnect = False
                websocket.close(code=1008, reason="invalid message")
                return

            if not isinstance(message, HelloMessage):
                unexpected_disconnect = False
                websocket.close(code=1008, reason="authentication required")
                return
            if token is None or not secrets.compare_digest(message.auth_token, token):
                unexpected_disconnect = False
                websocket.close(code=1008, reason="authentication failed")
                return

            websocket.send(hello_ack(self._server_instance_id))
            authenticated = True
            self._on_status(BrowserReceiverStatus.CONNECTED)

            while True:
                try:
                    raw = websocket.recv()
                    self._record_message_or_raise(timestamps)
                    message = parse_client_message(raw)
                except ConnectionClosed as error:
                    unexpected_disconnect = self._is_unexpected_disconnect(error)
                    return
                except ProtocolVersionError:
                    unexpected_disconnect = False
                    self._on_status(BrowserReceiverStatus.UNSUPPORTED_PROTOCOL)
                    websocket.close(code=1002, reason="unsupported protocol")
                    return
                except ProtocolError:
                    unexpected_disconnect = False
                    websocket.close(code=1008, reason="invalid message")
                    return

                if isinstance(message, HelloMessage):
                    unexpected_disconnect = False
                    websocket.close(code=1008, reason="already authenticated")
                    return
                if isinstance(message, KeepaliveMessage):
                    continue
                self._on_message(message)
        except ConnectionClosed as error:
            unexpected_disconnect = self._is_unexpected_disconnect(error)
            return
        finally:
            with self._lock:
                running = self._server is not None and not self._stopping
                self._client_owned = False
            if authenticated and unexpected_disconnect and running:
                self._on_status(BrowserReceiverStatus.TEMPORARILY_UNAVAILABLE)

    def _record_message_or_raise(self, timestamps: deque[float]) -> None:
        now = time.monotonic()
        cutoff = now - 10.0
        while timestamps and timestamps[0] < cutoff:
            timestamps.popleft()
        timestamps.append(now)
        if len(timestamps) > MAX_MESSAGES_PER_10_SECONDS:
            raise ProtocolError("browser message rate exceeded")

    @staticmethod
    def _is_unexpected_disconnect(error: ConnectionClosed) -> bool:
        return getattr(getattr(error, "rcvd", None), "code", None) not in {1000, 1001}
