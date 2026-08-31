import json


def rollout_line(timestamp: str, record_type: str, payload: dict) -> bytes:
    return (json.dumps({"timestamp": timestamp, "type": record_type, "payload": payload}, separators=(",", ":")) + "\n").encode("utf-8")


def session_meta(
    conversation_id="conversation-1",
    *,
    timestamp="2026-08-31T10:00:00Z",
    thread_source="user",
):
    return rollout_line(
        timestamp,
        "session_meta",
        {"id": conversation_id, "thread_source": thread_source},
    )


def turn_started(turn_id="turn-1", *, timestamp="2026-08-31T10:01:00Z", alias=False):
    return rollout_line(timestamp, "event_msg", {"type": "turn_started" if alias else "task_started", "turn_id": turn_id})


def assistant_message(text, phase="final_answer", *, timestamp="2026-08-31T10:01:02Z", content=None):
    return rollout_line(timestamp, "response_item", {"type": "message", "role": "assistant", "phase": phase, "content": [{"type": "output_text", "text": text}] if content is None else content})


def turn_complete(turn_id="turn-1", *, timestamp="2026-08-31T10:01:03Z", alias=False, error=None):
    payload = {"type": "turn_complete" if alias else "task_complete", "turn_id": turn_id, "last_agent_message": "must-not-be-used"}
    if error is not None:
        payload["error"] = error
    return rollout_line(timestamp, "event_msg", payload)


def turn_records(turn_id, text, *, completion_timestamp):
    return b"".join([turn_started(turn_id), assistant_message(text), turn_complete(turn_id, timestamp=completion_timestamp)])
