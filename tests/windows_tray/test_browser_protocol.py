import json

import pytest

from piper.windows_tray.browser_protocol import (
    MAX_IDENTIFIER_LENGTH,
    MAX_SENTENCE_BYTES,
    MAX_WIRE_MESSAGE_BYTES,
    HelloMessage,
    KeepaliveMessage,
    ProtocolError,
    ProtocolVersionError,
    ResponseEndMessage,
    ResponseStartMessage,
    SentenceMessage,
    hello_ack,
    parse_client_message,
)


def test_parses_hello_keepalive_and_response_messages() -> None:
    assert parse_client_message(json.dumps({
        "protocol_version": 1, "type": "hello",
        "client_id": "extension", "auth_token": "token",
    })) == HelloMessage("extension", "token")
    assert parse_client_message(json.dumps({
        "protocol_version": 1, "type": "keepalive",
    })) == KeepaliveMessage()
    assert parse_client_message(json.dumps({
        "protocol_version": 1,
        "type": "response_start",
        "conversation_id": "conv-1",
        "response_id": "resp-1",
        "sequence_start": 4,
    })) == ResponseStartMessage("conv-1", "resp-1", 4)
    assert parse_client_message(json.dumps({
        "protocol_version": 1, "type": "sentence",
        "conversation_id": "conv", "response_id": "resp",
        "sequence": 0, "text": " Hello. ",
    })) == SentenceMessage("conv", "resp", 0, "Hello.")
    assert parse_client_message(json.dumps({
        "protocol_version": 1, "type": "response_end",
        "conversation_id": "conv", "response_id": "resp",
        "next_sequence": 1, "reason": "complete",
    })) == ResponseEndMessage("conv", "resp", 1, "complete")


def test_hello_ack_is_compact_and_versioned() -> None:
    assert hello_ack("server-1") == (
        '{"protocol_version":1,"type":"hello_ack",'
        '"server_instance_id":"server-1"}'
    )


def test_unsupported_version_is_rejected() -> None:
    with pytest.raises(ProtocolVersionError):
        parse_client_message(json.dumps({"protocol_version": 2, "type": "keepalive"}))


@pytest.mark.parametrize("payload", ["[]", '"text"', "null", "1"])
def test_non_object_json_is_rejected(payload: str) -> None:
    with pytest.raises(ProtocolError, match="JSON object"):
        parse_client_message(payload)


@pytest.mark.parametrize("identifier", ["", "a" * (MAX_IDENTIFIER_LENGTH + 1), "has space", "💥"])
def test_invalid_identifiers_are_rejected(identifier: str) -> None:
    payload = json.dumps({
        "protocol_version": 1, "type": "response_start",
        "conversation_id": identifier, "response_id": "resp", "sequence_start": 0,
    })
    with pytest.raises(ProtocolError, match="identifier"):
        parse_client_message(payload)


@pytest.mark.parametrize("sequence", [-1, 1_000_001, 1.5, True, "1"])
def test_invalid_sequence_is_rejected(sequence) -> None:
    payload = json.dumps({
        "protocol_version": 1, "type": "sentence",
        "conversation_id": "conv", "response_id": "resp",
        "sequence": sequence, "text": "Hello.",
    })
    with pytest.raises(ProtocolError, match="sequence"):
        parse_client_message(payload)


def test_sentence_utf8_byte_limit_is_checked_before_stripping() -> None:
    text = "é" * ((MAX_SENTENCE_BYTES // 2) + 1)
    with pytest.raises(ProtocolError, match="sentence text is too large"):
        parse_client_message(json.dumps({
            "protocol_version": 1, "type": "sentence",
            "conversation_id": "conv", "response_id": "resp",
            "sequence": 0, "text": text,
        }))


def test_wire_payload_limit_uses_utf8_bytes() -> None:
    payload = b"x" * (MAX_WIRE_MESSAGE_BYTES + 1)
    with pytest.raises(ProtocolError, match="wire message is too large"):
        parse_client_message(payload)


def test_binary_non_utf8_payload_is_rejected() -> None:
    with pytest.raises(ProtocolError, match="UTF-8"):
        parse_client_message(b"\xff\xfe")


def test_blank_sentence_unknown_type_and_invalid_reason_are_rejected() -> None:
    with pytest.raises(ProtocolError, match="blank"):
        parse_client_message(json.dumps({
            "protocol_version": 1, "type": "sentence",
            "conversation_id": "conv", "response_id": "resp",
            "sequence": 0, "text": "  ",
        }))
    with pytest.raises(ProtocolError, match="unknown"):
        parse_client_message(json.dumps({"protocol_version": 1, "type": "nope"}))
    with pytest.raises(ProtocolError, match="reason"):
        parse_client_message(json.dumps({
            "protocol_version": 1, "type": "response_end",
            "conversation_id": "conv", "response_id": "resp",
            "next_sequence": 0, "reason": "other",
        }))
