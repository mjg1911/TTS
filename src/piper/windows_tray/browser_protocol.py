from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Union


PROTOCOL_VERSION = 1
LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 8766
MAX_WIRE_MESSAGE_BYTES = 16 * 1024
MAX_SENTENCE_BYTES = 8 * 1024
MAX_IDENTIFIER_LENGTH = 128
MAX_BROWSER_QUEUE_SENTENCES = 32
MAX_BROWSER_QUEUE_BYTES = 64 * 1024
MAX_MESSAGES_PER_10_SECONDS = 60
AUTH_TIMEOUT_SECONDS = 5


class ProtocolError(ValueError):
    pass


class ProtocolVersionError(ProtocolError):
    pass


@dataclass(frozen=True)
class HelloMessage:
    client_id: str
    auth_token: str


@dataclass(frozen=True)
class KeepaliveMessage:
    pass


@dataclass(frozen=True)
class ResponseStartMessage:
    conversation_id: str
    response_id: str
    sequence_start: int


@dataclass(frozen=True)
class SentenceMessage:
    conversation_id: str
    response_id: str
    sequence: int
    text: str


@dataclass(frozen=True)
class ResponseEndMessage:
    conversation_id: str
    response_id: str
    next_sequence: int
    reason: str


ClientMessage = Union[
    HelloMessage,
    KeepaliveMessage,
    ResponseStartMessage,
    SentenceMessage,
    ResponseEndMessage,
]

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9._:@/-]{1,128}$")
_END_REASONS = {"complete", "revision_conflict", "replaced"}


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER_RE.fullmatch(value) is None:
        raise ProtocolError(f"invalid {field} identifier")
    return value


def _sequence(value: object, field: str) -> int:
    if type(value) is not int or not 0 <= value <= 1_000_000:
        raise ProtocolError(f"invalid {field} sequence")
    return value


def parse_client_message(payload: str | bytes) -> ClientMessage:
    if isinstance(payload, bytes):
        if len(payload) > MAX_WIRE_MESSAGE_BYTES:
            raise ProtocolError("wire message is too large")
        try:
            payload = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProtocolError("payload is not valid UTF-8") from exc
    elif not isinstance(payload, str):
        raise ProtocolError("payload must be text or bytes")

    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ProtocolError("invalid JSON") from exc
    if not isinstance(data, dict):
        raise ProtocolError("JSON object required")
    wire_too_large = len(payload.encode("utf-8")) > MAX_WIRE_MESSAGE_BYTES
    if data.get("protocol_version") != PROTOCOL_VERSION:
        raise ProtocolVersionError("unsupported protocol version")

    message_type = data.get("type")
    if message_type == "hello":
        if wire_too_large:
            raise ProtocolError("wire message is too large")
        return HelloMessage(
            _identifier(data.get("client_id"), "client_id"),
            _identifier(data.get("auth_token"), "auth_token"),
        )
    if message_type == "keepalive":
        if wire_too_large:
            raise ProtocolError("wire message is too large")
        return KeepaliveMessage()
    if message_type == "response_start":
        if wire_too_large:
            raise ProtocolError("wire message is too large")
        return ResponseStartMessage(
            _identifier(data.get("conversation_id"), "conversation_id"),
            _identifier(data.get("response_id"), "response_id"),
            _sequence(data.get("sequence_start"), "sequence_start"),
        )
    if message_type == "sentence":
        text = data.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ProtocolError("sentence text must not be blank")
        if len(text.encode("utf-8")) > MAX_SENTENCE_BYTES:
            raise ProtocolError("sentence text is too large")
        if wire_too_large:
            raise ProtocolError("wire message is too large")
        return SentenceMessage(
            _identifier(data.get("conversation_id"), "conversation_id"),
            _identifier(data.get("response_id"), "response_id"),
            _sequence(data.get("sequence"), "sentence"),
            text.strip(),
        )
    if message_type == "response_end":
        if wire_too_large:
            raise ProtocolError("wire message is too large")
        reason = data.get("reason")
        if reason not in _END_REASONS:
            raise ProtocolError("invalid response end reason")
        return ResponseEndMessage(
            _identifier(data.get("conversation_id"), "conversation_id"),
            _identifier(data.get("response_id"), "response_id"),
            _sequence(data.get("next_sequence"), "next"),
            reason,
        )
    raise ProtocolError("unknown message type")


def hello_ack(server_instance_id: str) -> str:
    return json.dumps(
        {
            "protocol_version": PROTOCOL_VERSION,
            "type": "hello_ack",
            "server_instance_id": server_instance_id,
        },
        separators=(",", ":"),
    )
