"""Private framed protocol shared by the tray and Kokoro helper."""

from __future__ import annotations

import base64
import binascii
import json
import struct
from typing import BinaryIO, Dict

PROTOCOL_VERSION = 1
MAX_TEXT_BYTES = 1024 * 1024
MAX_AUDIO_BYTES = 1024 * 1024
MAX_FRAME_BYTES = 4 * 1024 * 1024

_HEADER = struct.Struct(">I")
_MESSAGE_TYPES = {
    "hello",
    "initialize",
    "ready",
    "synthesize",
    "audio",
    "response_end",
    "response_error",
    "response_cancelled",
    "cancel",
    "shutdown",
}


class ProtocolError(RuntimeError):
    """Raised when a worker protocol message is invalid or unsafe."""


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    chunks = []
    remaining = size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def write_frame(stream: BinaryIO, message: Dict[str, object]) -> None:
    """Write one JSON object with a bounded four-byte length prefix."""
    try:
        payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
    except (TypeError, UnicodeEncodeError) as error:
        raise ProtocolError("message is not JSON serializable") from error
    if len(payload) > MAX_FRAME_BYTES:
        raise ProtocolError("frame too large")
    stream.write(_HEADER.pack(len(payload)))
    stream.write(payload)
    stream.flush()


def read_frame(stream: BinaryIO) -> Dict[str, object]:
    """Read one bounded JSON frame without allocating an untrusted payload."""
    header = _read_exact(stream, _HEADER.size)
    if len(header) != _HEADER.size:
        raise EOFError("protocol stream closed")
    (size,) = _HEADER.unpack(header)
    if size > MAX_FRAME_BYTES:
        raise ProtocolError("frame too large")

    payload = _read_exact(stream, size)
    if len(payload) != size:
        raise ProtocolError("truncated frame")
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProtocolError("malformed json frame") from error
    if not isinstance(decoded, dict) or not isinstance(decoded.get("type"), str):
        raise ProtocolError("frame must be a typed object")
    return decoded


def encode_audio(audio: bytes) -> str:
    """Encode one bounded PCM16 audio chunk as base64 text."""
    if len(audio) > MAX_AUDIO_BYTES:
        raise ProtocolError("audio chunk too large")
    if len(audio) % 2:
        raise ProtocolError("audio chunk must contain complete PCM16 samples")
    return base64.b64encode(audio).decode("ascii")


def decode_audio(value: object) -> bytes:
    """Decode one bounded base64 PCM16 audio chunk."""
    if not isinstance(value, str):
        raise ProtocolError("audio payload must be base64 text")
    try:
        audio = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ProtocolError("invalid base64 audio") from error
    if len(audio) > MAX_AUDIO_BYTES:
        raise ProtocolError("audio chunk too large")
    if len(audio) % 2:
        raise ProtocolError("audio chunk must contain complete PCM16 samples")
    return audio


def _positive_request_id(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise ProtocolError("request_id must be a positive integer")
    return value


def _require_type(message: Dict[str, object], expected: str) -> None:
    if message.get("type") != expected:
        raise ProtocolError("message type must be %s" % expected)


def validate_hello(message: Dict[str, object]) -> None:
    """Validate the worker's compatibility handshake."""
    _require_type(message, "hello")
    if message.get("protocol_version") != PROTOCOL_VERSION:
        raise ProtocolError("unsupported protocol version")
    for field in ("worker_version", "kokoro_version"):
        value = message.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ProtocolError("%s must be non-empty" % field)


def validate_initialize(message: Dict[str, object]) -> None:
    """Validate the manifest-only worker initialization message."""
    if set(message) != {"type", "manifest_sha256"}:
        raise ProtocolError("initialize contains unsupported fields")
    _require_type(message, "initialize")
    value = message.get("manifest_sha256")
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise ProtocolError("manifest_sha256 must be lowercase sha256 hex")


def validate_synthesize(message: Dict[str, object]) -> None:
    """Validate a synthesis request and its bounded text input."""
    _require_type(message, "synthesize")
    _positive_request_id(message.get("request_id"))
    text = message.get("text")
    voice_id = message.get("voice_id")
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_TEXT_BYTES:
        raise ProtocolError("synthesis text exceeds limit")
    if not isinstance(voice_id, str) or not voice_id.strip():
        raise ProtocolError("voice_id must be non-empty")


def validate_response_frame(message: Dict[str, object]) -> None:
    """Validate request-scoped worker responses and cancellation messages."""
    message_type = message.get("type")
    if message_type not in {"audio", "response_end", "response_error", "response_cancelled", "cancel"}:
        raise ProtocolError("unsupported response message type")
    _positive_request_id(message.get("request_id"))
    if message_type == "audio":
        decode_audio(message.get("audio"))
    elif message_type == "response_error":
        category = message.get("category")
        if category is not None and (not isinstance(category, str) or not category.strip()):
            raise ProtocolError("response error category must be non-empty text")


def validate_message(message: Dict[str, object]) -> None:
    """Dispatch semantic validation for any supported protocol message."""
    message_type = message.get("type")
    if message_type not in _MESSAGE_TYPES:
        raise ProtocolError("unsupported message type")
    if message_type == "hello":
        validate_hello(message)
    elif message_type == "initialize":
        validate_initialize(message)
    elif message_type == "synthesize":
        validate_synthesize(message)
    elif message_type in {"audio", "response_end", "response_error", "response_cancelled", "cancel"}:
        validate_response_frame(message)
