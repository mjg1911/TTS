from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Optional


@dataclass(frozen=True)
class CodexResponseId:
    conversation_id: str
    turn_id: str


@dataclass(frozen=True)
class CodexCompletedResponse:
    response_id: CodexResponseId
    completed_at: datetime
    text: str


class UnsupportedCodexFormat(ValueError):
    pass


def _timestamp(value: object) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


class CodexRolloutParser:
    def __init__(self) -> None:
        self._conversation_id: Optional[str] = None
        self._turn_id: Optional[str] = None
        self._final_text: Optional[str] = None

    def feed_line(self, line: bytes) -> Optional[CodexCompletedResponse]:
        try:
            record = json.loads(line.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            return None
        if not isinstance(record, dict):
            return None
        record_type = record.get("type")
        payload = record.get("payload")
        if record_type == "session_meta":
            self._read_session_meta(payload)
        elif record_type == "response_item":
            self._read_response_item(payload)
        elif record_type == "event_msg":
            return self._read_event(record.get("timestamp"), payload)
        return None

    def _read_session_meta(self, payload: object) -> None:
        if not isinstance(payload, dict) or not isinstance(payload.get("id"), str):
            raise UnsupportedCodexFormat("session_meta.id is unavailable")
        conversation_id = payload["id"].strip()
        if not conversation_id:
            raise UnsupportedCodexFormat("session_meta.id is empty")
        self._conversation_id = conversation_id

    def _read_response_item(self, payload: object) -> None:
        if not isinstance(payload, dict):
            raise UnsupportedCodexFormat("response_item payload is unavailable")
        if payload.get("type") != "message" or payload.get("role") != "assistant":
            return
        if payload.get("phase") != "final_answer" or self._turn_id is None:
            return
        content = payload.get("content")
        if not isinstance(content, list):
            raise UnsupportedCodexFormat("assistant message content is unavailable")
        if any(
            not isinstance(item, dict)
            or item.get("type") != "output_text"
            or not isinstance(item.get("text"), str)
            for item in content
        ):
            self._final_text = None
            return
        parts = [item["text"] for item in content if item["text"].strip()]
        self._final_text = "\n".join(parts) if parts else None

    def _read_event(self, timestamp_value: object, payload: object) -> Optional[CodexCompletedResponse]:
        if not isinstance(payload, dict):
            raise UnsupportedCodexFormat("event_msg payload is unavailable")
        event_type = payload.get("type")
        if event_type in {"task_started", "turn_started"}:
            turn_id = payload.get("turn_id")
            if not isinstance(turn_id, str) or not turn_id.strip():
                raise UnsupportedCodexFormat("turn start id is unavailable")
            self._turn_id = turn_id.strip()
            self._final_text = None
            return None
        if event_type not in {"task_complete", "turn_complete"}:
            return None
        turn_id = payload.get("turn_id")
        if not isinstance(turn_id, str) or not turn_id.strip():
            raise UnsupportedCodexFormat("turn completion id is unavailable")
        completed_at = _timestamp(timestamp_value)
        response = None
        if (
            self._conversation_id is not None
            and self._turn_id == turn_id.strip()
            and self._final_text is not None
            and payload.get("error") is None
            and completed_at is not None
        ):
            response = CodexCompletedResponse(
                CodexResponseId(self._conversation_id, self._turn_id),
                completed_at,
                self._final_text,
            )
        self._turn_id = None
        self._final_text = None
        return response
