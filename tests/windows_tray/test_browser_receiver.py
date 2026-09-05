from collections import deque
import json
import logging
import socket
import threading
import time

import pytest
from websockets.exceptions import (
    ConnectionClosed,
    ConnectionClosedError,
    ConnectionClosedOK,
)
from websockets.frames import Close
from websockets.sync.client import connect

from piper.windows_tray.browser_protocol import (
    AUTH_TIMEOUT_SECONDS,
    MAX_MESSAGES_PER_10_SECONDS,
    PROTOCOL_VERSION,
    ProtocolError,
    ResponseStartMessage,
)
import piper.windows_tray.browser_receiver as browser_receiver_module
from piper.windows_tray.browser_receiver import BrowserReceiver, BrowserReceiverStatus


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def send_json(websocket, payload: dict) -> None:
    websocket.send(json.dumps(payload, separators=(",", ":")))


def hello(token: str, *, version: int = PROTOCOL_VERSION) -> dict:
    return {
        "protocol_version": version,
        "type": "hello",
        "client_id": "test-client",
        "auth_token": token,
    }


def test_successful_authentication_sends_hello_ack():
    token = "a" * 43
    port = free_port()
    statuses = []
    receiver = BrowserReceiver(lambda _message: None, statuses.append, port=port)
    receiver.start(token)
    try:
        with connect(f"ws://127.0.0.1:{port}") as websocket:
            send_json(websocket, hello(token))
            reply = json.loads(websocket.recv())
            assert reply["protocol_version"] == PROTOCOL_VERSION
            assert reply["type"] == "hello_ack"
            assert BrowserReceiverStatus.CONNECTED in statuses
    finally:
        receiver.stop()


def test_wrong_token_is_rejected_with_policy_close():
    token = "a" * 43
    port = free_port()
    receiver = BrowserReceiver(lambda _message: None, lambda _status: None, port=port)
    receiver.start(token)
    try:
        with connect(f"ws://127.0.0.1:{port}") as websocket:
            send_json(websocket, hello("b" * 43))
            with pytest.raises(ConnectionClosed) as error:
                websocket.recv()
        assert error.value.rcvd.code == 1008
    finally:
        receiver.stop()


def test_pre_auth_non_hello_is_rejected():
    port = free_port()
    receiver = BrowserReceiver(lambda _message: None, lambda _status: None, port=port)
    receiver.start("a" * 43)
    try:
        with connect(f"ws://127.0.0.1:{port}") as websocket:
            send_json(websocket, {"protocol_version": PROTOCOL_VERSION, "type": "keepalive"})
            with pytest.raises(ConnectionClosed) as error:
                websocket.recv()
        assert error.value.rcvd.code == 1008
    finally:
        receiver.stop()


def test_unsupported_protocol_is_rejected_and_reported():
    port = free_port()
    statuses = []
    receiver = BrowserReceiver(lambda _message: None, statuses.append, port=port)
    receiver.start("a" * 43)
    try:
        with connect(f"ws://127.0.0.1:{port}") as websocket:
            send_json(websocket, hello("a" * 43, version=999))
            with pytest.raises(ConnectionClosed) as error:
                websocket.recv()
        assert error.value.rcvd.code == 1002
        assert BrowserReceiverStatus.UNSUPPORTED_PROTOCOL in statuses
    finally:
        receiver.stop()


def test_second_concurrent_client_is_temporarily_unavailable():
    token = "a" * 43
    port = free_port()
    receiver = BrowserReceiver(lambda _message: None, lambda _status: None, port=port)
    receiver.start(token)
    try:
        with connect(f"ws://127.0.0.1:{port}") as first:
            send_json(first, hello(token))
            first.recv()
            with connect(f"ws://127.0.0.1:{port}") as second:
                with pytest.raises(ConnectionClosed) as error:
                    second.recv()
            assert error.value.rcvd.code == 1013
    finally:
        receiver.stop()


def test_idle_unauthenticated_client_is_rejected():
    port = free_port()
    receiver = BrowserReceiver(lambda _message: None, lambda _status: None, port=port)
    receiver.start("a" * 43)
    started = time.monotonic()
    try:
        with connect(f"ws://127.0.0.1:{port}") as websocket:
            with pytest.raises(ConnectionClosed) as error:
                websocket.recv(timeout=AUTH_TIMEOUT_SECONDS + 2)
        assert error.value.rcvd.code == 1008
        assert time.monotonic() - started >= AUTH_TIMEOUT_SECONDS
    finally:
        receiver.stop()


def test_non_loopback_constructor_is_rejected():
    with pytest.raises(ValueError, match="loopback"):
        BrowserReceiver(lambda _message: None, lambda _status: None, host="0.0.0.0")


def test_authenticated_protocol_messages_are_dispatched():
    token = "a" * 43
    port = free_port()
    messages = []
    receiver = BrowserReceiver(messages.append, lambda _status: None, port=port)
    receiver.start(token)
    try:
        with connect(f"ws://127.0.0.1:{port}") as websocket:
            send_json(websocket, hello(token))
            websocket.recv()
            send_json(websocket, {
                "protocol_version": PROTOCOL_VERSION,
                "type": "response_start",
                "conversation_id": "conversation",
                "response_id": "response",
                "sequence_start": 0,
            })
            deadline = time.monotonic() + 2
            while not messages and time.monotonic() < deadline:
                time.sleep(0.01)
            assert messages == [ResponseStartMessage("conversation", "response", 0)]
    finally:
        receiver.stop()


def test_stop_releases_port_for_reuse():
    port = free_port()
    receiver = BrowserReceiver(lambda _message: None, lambda _status: None, port=port)
    receiver.start("a" * 43)
    receiver.stop()
    replacement = BrowserReceiver(lambda _message: None, lambda _status: None, port=port)
    replacement.start("b" * 43)
    replacement.stop()


def test_stop_closes_live_client_and_restart_accepts_new_client():
    token = "a" * 43
    port = free_port()
    messages = []
    receiver = BrowserReceiver(messages.append, lambda _status: None, port=port)
    receiver.start(token)
    client = connect(f"ws://127.0.0.1:{port}")
    try:
        send_json(client, hello(token))
        assert json.loads(client.recv())["type"] == "hello_ack"
        receiver.stop()
        with pytest.raises(ConnectionClosed):
            client.recv(timeout=1)
        deadline = time.monotonic() + 2
        while True:
            try:
                replacement = connect(f"ws://127.0.0.1:{port}")
                break
            except ConnectionRefusedError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.01)
        with replacement:
            send_json(replacement, hello(token))
            reply = json.loads(replacement.recv())
            assert reply["type"] == "hello_ack"
    finally:
        client.close()
        receiver.stop()


def test_stop_prevents_a_received_message_from_being_dispatched():
    token = "a" * 43
    received = threading.Event()
    release = threading.Event()
    messages = []

    class FakeServer:
        def shutdown(self):
            pass

    class MessageAfterStop:
        def __init__(self):
            self.recv_calls = 0

        def recv(self, **_kwargs):
            self.recv_calls += 1
            if self.recv_calls == 1:
                return json.dumps(hello(token), separators=(",", ":"))
            if self.recv_calls == 2:
                received.set()
                release.wait(timeout=2)
                return json.dumps(
                    {
                        "protocol_version": PROTOCOL_VERSION,
                        "type": "response_start",
                        "conversation_id": "conversation",
                        "response_id": "response",
                        "sequence_start": 0,
                    },
                    separators=(",", ":"),
                )
            raise ConnectionClosedOK(Close(1000, ""), None)

        def close(self, **_kwargs):
            pass

        def send(self, _message):
            pass

    receiver = BrowserReceiver(messages.append, lambda _status: None)
    receiver._run_generation = 1
    receiver._server_generation = 1
    receiver._server = FakeServer()
    receiver._token = token
    client = MessageAfterStop()
    thread = threading.Thread(target=receiver._handle_connection, args=(client,))
    thread.start()
    assert received.wait(timeout=2)
    receiver.stop()
    release.set()
    thread.join(timeout=2)

    assert messages == []


def test_stale_client_cleanup_cannot_release_new_generation_owner():
    receiver = BrowserReceiver(lambda _message: None, lambda _status: None)
    old_client = object()
    new_client = object()
    receiver._run_generation = 2
    receiver._server_generation = 2
    receiver._server = object()
    receiver._client_owned = True
    receiver._client_generation = 2
    receiver._clients = {old_client: 1, new_client: 2}

    receiver._release_client(old_client, 1, authenticated=True, disconnected=True)

    assert receiver._client_owned is True
    assert receiver._client_generation == 2
    assert new_client in receiver._clients


def test_rate_limit_rejects_the_message_after_the_window_budget(monkeypatch):
    receiver = BrowserReceiver(lambda _message: None, lambda _status: None)
    timestamps = deque([100.0] * MAX_MESSAGES_PER_10_SECONDS)
    monkeypatch.setattr(browser_receiver_module.time, "monotonic", lambda: 100.0)

    with pytest.raises(ProtocolError, match="rate exceeded"):
        receiver._record_message_or_raise(timestamps)


def test_browser_transport_debug_logging_drops_wire_payloads(caplog):
    secret = "PRIVATE-BROWSER-TOKEN-AND-TEXT"
    transport_logger = browser_receiver_module._TRANSPORT_LOGGER
    old_level = transport_logger.level
    try:
        transport_logger.setLevel(logging.DEBUG)
        with caplog.at_level(logging.DEBUG):
            transport_logger.debug("received TEXT %s", secret)
    finally:
        transport_logger.setLevel(old_level)

    assert secret not in caplog.text


def test_authentication_status_is_ordered_before_stop_disabled():
    token = "a" * 43
    connected = threading.Event()
    release = threading.Event()
    stop_done = threading.Event()
    statuses = []

    class FakeServer:
        def shutdown(self):
            pass

    class AuthenticatedClient:
        def __init__(self):
            self.recv_calls = 0

        def recv(self, **_kwargs):
            self.recv_calls += 1
            if self.recv_calls == 1:
                return json.dumps(hello(token), separators=(",", ":"))
            raise ConnectionClosedOK(Close(1000, ""), None)

        def close(self, **_kwargs):
            pass

        def send(self, _message):
            pass

    def on_status(status):
        statuses.append(status)
        if status is BrowserReceiverStatus.CONNECTED:
            connected.set()
            assert release.wait(timeout=2)

    receiver = BrowserReceiver(lambda _message: None, on_status)
    receiver._run_generation = 1
    receiver._server_generation = 1
    receiver._server = FakeServer()
    receiver._token = token
    thread = threading.Thread(
        target=receiver._handle_connection,
        args=(AuthenticatedClient(),),
    )
    thread.start()
    assert connected.wait(timeout=2)

    def stop_receiver():
        receiver.stop()
        stop_done.set()

    stopper = threading.Thread(target=stop_receiver)
    stopper.start()
    assert not stop_done.wait(timeout=0.1)
    release.set()
    assert stop_done.wait(timeout=2)
    thread.join(timeout=2)
    stopper.join(timeout=2)

    assert statuses == [
        BrowserReceiverStatus.CONNECTED,
        BrowserReceiverStatus.DISABLED,
    ]


def test_clean_authenticated_disconnect_reports_temporary_unavailability():
    receiver = BrowserReceiver(lambda _message: None, lambda _status: None)
    statuses = []
    receiver._on_status = statuses.append

    class CleanDisconnect:
        def recv(self, **_kwargs):
            if not hasattr(self, "authenticated"):
                self.authenticated = True
                return json.dumps(hello("a" * 43), separators=(",", ":"))
            raise ConnectionClosedOK(Close(1000, ""), None)

        def close(self, **_kwargs):
            pass

        def send(self, _message):
            pass

    receiver._token = "a" * 43
    receiver._run_generation = 1
    receiver._server_generation = 1
    receiver._server = object()
    receiver._handle_connection(CleanDisconnect())

    assert BrowserReceiverStatus.TEMPORARILY_UNAVAILABLE in statuses


def test_unexpected_authenticated_disconnect_reports_temporary_unavailability():
    receiver = BrowserReceiver(lambda _message: None, lambda _status: None)
    statuses = []
    receiver._on_status = statuses.append

    class UnexpectedDisconnect:
        def recv(self, **_kwargs):
            if not hasattr(self, "authenticated"):
                self.authenticated = True
                return json.dumps(hello("a" * 43), separators=(",", ":"))
            raise ConnectionClosedError(Close(1006, ""), None)

        def close(self, **_kwargs):
            pass

        def send(self, _message):
            pass

    receiver._token = "a" * 43
    receiver._run_generation = 1
    receiver._server_generation = 1
    receiver._server = object()
    receiver._handle_connection(UnexpectedDisconnect())

    assert BrowserReceiverStatus.TEMPORARILY_UNAVAILABLE in statuses


def test_start_clears_token_and_restores_stopped_state_when_bind_fails(monkeypatch):
    receiver = BrowserReceiver(lambda _message: None, lambda _status: None)

    def fail_to_bind(*_args, **_kwargs):
        raise OSError("address already in use")

    monkeypatch.setattr("piper.windows_tray.browser_receiver.serve", fail_to_bind)

    with pytest.raises(OSError, match="address already in use"):
        receiver.start("a" * 43)

    assert receiver._token is None
    assert receiver._server is None
    assert receiver._thread is None
    assert receiver._stopping is True
