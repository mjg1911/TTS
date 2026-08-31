from datetime import datetime, timezone

import pytest

from piper.windows_tray.codex_history import CodexRolloutParser, CodexResponseId, UnsupportedCodexFormat
from .codex_test_data import assistant_message, rollout_line, session_meta, turn_complete, turn_started


def test_final_answer_is_emitted_only_after_matching_turn_completion():
    parser = CodexRolloutParser()
    assert parser.feed_line(session_meta()) is None
    assert parser.feed_line(turn_started()) is None
    assert parser.feed_line(assistant_message("Final answer.")) is None
    response = parser.feed_line(turn_complete())
    assert response is not None
    assert response.response_id == CodexResponseId("conversation-1", "turn-1")
    assert response.text == "Final answer."
    assert response.completed_at == datetime(2026, 8, 31, 10, 1, 3, tzinfo=timezone.utc)


@pytest.mark.parametrize("phase", ["commentary", "analysis", None])
def test_non_final_assistant_messages_are_never_emitted(phase):
    parser = CodexRolloutParser()
    parser.feed_line(session_meta()); parser.feed_line(turn_started())
    payload = {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "do not speak"}]}
    if phase is not None: payload["phase"] = phase
    parser.feed_line(rollout_line("2026-08-31T10:01:02Z", "response_item", payload))
    assert parser.feed_line(turn_complete()) is None


def test_internal_agent_session_final_answer_is_never_emitted():
    parser = CodexRolloutParser()
    parser.feed_line(session_meta(thread_source="subagent"))
    parser.feed_line(turn_started())
    parser.feed_line(assistant_message("Risk level: high"))
    assert parser.feed_line(turn_complete()) is None


@pytest.mark.parametrize(
    ("metadata_records", "expected_response_id"),
    [
        (
            [session_meta("root-conversation", thread_source="user"), session_meta("agent-conversation", thread_source="subagent")],
            CodexResponseId("root-conversation", "turn-1"),
        ),
        (
            [session_meta("root-conversation", thread_source="subagent"), session_meta("user-conversation", thread_source="user")],
            None,
        ),
    ],
)
def test_first_valid_session_metadata_controls_response_identity_and_filtering(metadata_records, expected_response_id):
    parser = CodexRolloutParser()
    for record in metadata_records:
        parser.feed_line(record)
    parser.feed_line(turn_started())
    parser.feed_line(assistant_message("root response"))

    response = parser.feed_line(turn_complete())

    if expected_response_id is None:
        assert response is None
    else:
        assert response is not None
        assert response.response_id == expected_response_id
        assert response.text == "root response"


def test_aliases_and_multiple_output_text_parts_are_supported():
    parser = CodexRolloutParser()
    parser.feed_line(session_meta()); parser.feed_line(turn_started(alias=True))
    parser.feed_line(assistant_message("one", content=[{"type": "output_text", "text": "one"}, {"type": "output_text", "text": "two"}]))
    response = parser.feed_line(turn_complete(alias=True))
    assert response is not None and response.text == "one\ntwo"


def test_invalid_content_fails_closed():
    parser = CodexRolloutParser()
    parser.feed_line(session_meta()); parser.feed_line(turn_started())
    parser.feed_line(assistant_message("ignored", content=[{"type": "input_text", "text": "secret"}]))
    assert parser.feed_line(turn_complete()) is None


@pytest.mark.parametrize("payload", [{}, {"id": ""}, {"id": 3}])
def test_required_session_shape_is_rejected(payload):
    with pytest.raises(UnsupportedCodexFormat):
        CodexRolloutParser().feed_line(rollout_line("2026-08-31T10:00:00Z", "session_meta", payload))


def test_completion_requires_matching_turn_and_timezone_timestamp():
    parser = CodexRolloutParser()
    parser.feed_line(session_meta()); parser.feed_line(turn_started("turn-a")); parser.feed_line(assistant_message("answer"))
    assert parser.feed_line(turn_complete("turn-b")) is None
    parser.feed_line(turn_started("turn-a")); parser.feed_line(assistant_message("answer"))
    assert parser.feed_line(turn_complete(timestamp="2026-08-31T10:01:03")) is None
