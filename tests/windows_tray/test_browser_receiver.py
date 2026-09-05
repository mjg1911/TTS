import json
import socket
import time

import pytest
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

from piper.windows_tray.browser_protocol import (
    AUTH_TIMEOUT_SECONDS,
    PROTOCOL_VERSION,
    ResponseStartMessage,
)
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
