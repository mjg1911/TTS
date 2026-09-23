import io
import json
import struct

import pytest

from piper.windows_tray.kokoro_protocol import (
    MAX_AUDIO_BYTES,
    MAX_FRAME_BYTES,
    MAX_TEXT_BYTES,
    PROTOCOL_VERSION,
    ProtocolError,
    decode_audio,
    encode_audio,
    read_frame,
    validate_hello,
    validate_initialize,
    validate_response_frame,
    validate_synthesize,
    write_frame,
)


def test_round_trip_control_frame():
    stream = io.BytesIO()
    write_frame(stream, {"type": "cancel", "request_id": 7})
    stream.seek(0)
    assert read_frame(stream) == {"type": "cancel", "request_id": 7}


def test_writes_four_byte_big_endian_length_prefix():
    stream = io.BytesIO()
    write_frame(stream, {"type": "ready"})
    payload = json.dumps({"type": "ready"}, separators=(",", ":")).encode("utf-8")
    assert stream.getvalue() == struct.pack(">I", len(payload)) + payload


def test_rejects_frame_length_before_allocating_payload():
    stream = io.BytesIO(struct.pack(">I", MAX_FRAME_BYTES + 1))
    with pytest.raises(ProtocolError, match="frame too large"):
        read_frame(stream)


def test_rejects_truncated_header():
    with pytest.raises(EOFError, match="protocol stream closed"):
        read_frame(io.BytesIO(b"\x00\x00"))


def test_rejects_truncated_payload():
    stream = io.BytesIO(struct.pack(">I", 4) + b"{}")
    with pytest.raises(ProtocolError, match="truncated frame"):
        read_frame(stream)


def test_rejects_malformed_json_frame():
    stream = io.BytesIO(struct.pack(">I", 3) + b"{no")
    with pytest.raises(ProtocolError, match="malformed json frame"):
        read_frame(stream)


def test_rejects_untagged_json_frame():
    payload = b"[]"
    stream = io.BytesIO(struct.pack(">I", len(payload)) + payload)
    with pytest.raises(ProtocolError, match="typed object"):
        read_frame(stream)


def test_write_rejects_oversized_frame():
    with pytest.raises(ProtocolError, match="frame too large"):
        write_frame(io.BytesIO(), {"type": "x", "value": "a" * MAX_FRAME_BYTES})


def test_text_limit_is_one_mib_utf8():
    assert MAX_TEXT_BYTES == 1024 * 1024


def test_audio_limit_is_one_mib():
    assert MAX_AUDIO_BYTES == 1024 * 1024


def test_audio_round_trip_and_pcm16_validation():
    encoded = encode_audio(b"\x01\x00\xff\x7f")
    assert decode_audio(encoded) == b"\x01\x00\xff\x7f"


def test_encode_audio_rejects_oversized_audio():
    with pytest.raises(ProtocolError, match="audio chunk too large"):
        encode_audio(b"x" * (MAX_AUDIO_BYTES + 1))


def test_decode_audio_rejects_invalid_base64_and_odd_pcm16():
    with pytest.raises(ProtocolError, match="invalid base64 audio"):
        decode_audio("not base64!")
    with pytest.raises(ProtocolError, match="complete PCM16"):
        decode_audio("AQ==")


def test_validate_hello_accepts_matching_protocol_metadata():
    validate_hello(
        {
            "type": "hello",
            "protocol_version": PROTOCOL_VERSION,
            "worker_version": "1",
            "kokoro_version": "0.9.4",
        }
    )


def test_validate_hello_rejects_protocol_mismatch_or_missing_metadata():
    message = {
        "type": "hello",
        "protocol_version": PROTOCOL_VERSION + 1,
        "worker_version": "1",
        "kokoro_version": "0.9.4",
    }
    with pytest.raises(ProtocolError, match="protocol version"):
        validate_hello(message)
    message["protocol_version"] = PROTOCOL_VERSION
    del message["worker_version"]
    with pytest.raises(ProtocolError, match="worker_version"):
        validate_hello(message)


def test_validate_initialize_requires_exact_manifest_fields():
    validate_initialize({"type": "initialize", "manifest_sha256": "a" * 64})
    for message in (
        {"type": "initialize"},
        {"type": "initialize", "manifest_sha256": "A" * 64},
        {"type": "initialize", "manifest_sha256": "a" * 63},
        {"type": "initialize", "manifest_sha256": "a" * 64, "voices": []},
        {"type": "initialize", "manifest_sha256": "a" * 64, "model_path": "model"},
    ):
        with pytest.raises(ProtocolError):
            validate_initialize(message)


def test_validate_synthesize_requires_positive_id_bounded_text_and_voice():
    validate_synthesize(
        {"type": "synthesize", "request_id": 1, "text": "hello", "voice_id": "af_heart"}
    )
    cases = (
        {"type": "synthesize", "text": "hello", "voice_id": "af_heart"},
        {"type": "synthesize", "request_id": True, "text": "hello", "voice_id": "af_heart"},
        {"type": "synthesize", "request_id": 1, "text": "x" * (MAX_TEXT_BYTES + 1), "voice_id": "af_heart"},
        {"type": "synthesize", "request_id": 1, "text": "hello", "voice_id": "   "},
    )
    for message in cases:
        with pytest.raises(ProtocolError):
            validate_synthesize(message)


@pytest.mark.parametrize(
    "message_type",
    ["audio", "response_end", "response_error", "response_cancelled", "cancel"],
)
def test_validate_response_frame_requires_positive_request_id(message_type):
    message = {"type": message_type, "request_id": 1}
    if message_type == "audio":
        message["audio"] = encode_audio(b"\x00\x00")
    validate_response_frame(message)
    for invalid_id in (None, 0, -1, True, "1"):
        invalid = dict(message, request_id=invalid_id)
        with pytest.raises(ProtocolError, match="request_id"):
            validate_response_frame(invalid)


def test_validate_response_frame_checks_audio_payload():
    with pytest.raises(ProtocolError, match="audio"):
        validate_response_frame({"type": "audio", "request_id": 1, "audio": "bad!"})


@pytest.mark.parametrize(
    "message",
    [
        {"type": "hello"},
        {"type": "initialize", "manifest_sha256": "a" * 64},
        {"type": "ready"},
        {"type": "synthesize", "request_id": 1, "text": "x", "voice_id": "v"},
        {"type": "audio", "request_id": 1, "audio": encode_audio(b"\x00\x00")},
        {"type": "response_end", "request_id": 1},
        {"type": "response_error", "request_id": 1},
        {"type": "response_cancelled", "request_id": 1},
        {"type": "cancel", "request_id": 1},
        {"type": "shutdown"},
    ],
)
def test_known_message_types_are_supported(message):
    if message["type"] == "hello":
        validate_hello(
            dict(
                message,
                protocol_version=PROTOCOL_VERSION,
                worker_version="1",
                kokoro_version="0.9.4",
            )
        )
    elif message["type"] == "initialize":
        validate_initialize(message)
    elif message["type"] == "synthesize":
        validate_synthesize(message)
    elif message["type"] in {"ready", "shutdown"}:
        return
    else:
        validate_response_frame(message)


def test_validators_reject_unknown_message_types():
    with pytest.raises(ProtocolError, match="message type"):
        validate_response_frame({"type": "unknown", "request_id": 1})
