from pathlib import Path
import threading
import time

import pytest

from piper.windows_tray.codex_history import CodexResponseId
from piper.windows_tray.codex_monitor import CodexMonitor, CodexMonitorStatus, MAX_JSONL_LINE_BYTES, codex_sessions_dir
from tests.windows_tray.codex_test_data import assistant_message, rollout_line, session_meta, turn_complete, turn_records, turn_started


def _write_complete_turn(path: Path, conversation: str, turn: str, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(session_meta(conversation) + turn_records(turn, text, completion_timestamp="2026-08-31T10:01:03Z"))


def _append_turn(path: Path, turn: str, text: str, completion_timestamp: str) -> None:
    with path.open("ab") as handle:
        handle.write(turn_records(turn, text, completion_timestamp=completion_timestamp))


def _wait_until(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    pytest.fail("condition was not reached before timeout")


def test_codex_sessions_dir_uses_injected_home():
    assert codex_sessions_dir(Path("C:/CodexHome")) == Path("C:/CodexHome/sessions")


def test_baseline_reads_existing_state_but_emits_nothing(tmp_path):
    rollout = tmp_path / "sessions" / "2026" / "08" / "31" / "rollout.jsonl"
    _write_complete_turn(rollout, "conversation-1", "turn-1", "existing")
    monitor = CodexMonitor(tmp_path / "sessions", lambda _: None, lambda _: None)
    monitor._establish_baseline()
    assert monitor._poll_once() is None


def test_appended_completed_response_becomes_candidate_after_baseline(tmp_path):
    rollout = tmp_path / "sessions" / "rollout.jsonl"
    rollout.parent.mkdir(); rollout.write_bytes(session_meta())
    monitor = CodexMonitor(rollout.parent, lambda _: None, lambda _: None)
    monitor._establish_baseline()
    _append_turn(rollout, "turn-2", "new answer", "2026-08-31T10:02:00Z")
    response = monitor._poll_once()
    assert response is not None and response.text == "new answer"
    assert monitor._poll_once() is None


def test_turn_started_before_baseline_can_complete_afterward(tmp_path):
    rollout = tmp_path / "sessions" / "rollout.jsonl"; rollout.parent.mkdir()
    rollout.write_bytes(session_meta() + turn_started("turn-live"))
    monitor = CodexMonitor(rollout.parent, lambda _: None, lambda _: None); monitor._establish_baseline()
    with rollout.open("ab") as handle:
        handle.write(assistant_message("late answer")); handle.write(turn_complete("turn-live"))
    response = monitor._poll_once()
    assert response is not None and response.text == "late answer"


def test_one_poll_returns_only_newest_completion_across_files(tmp_path):
    sessions = tmp_path / "sessions"; first = sessions / "a.jsonl"; second = sessions / "b.jsonl"
    first.parent.mkdir(); first.write_bytes(session_meta("conversation-a")); second.write_bytes(session_meta("conversation-b"))
    monitor = CodexMonitor(sessions, lambda _: None, lambda _: None); monitor._establish_baseline()
    _append_turn(first, "turn-a", "older", "2026-08-31T10:02:00Z"); _append_turn(second, "turn-b", "newer", "2026-08-31T10:03:00Z")
    response = monitor._poll_once()
    assert response is not None and response.response_id == CodexResponseId("conversation-b", "turn-b")
    assert monitor._poll_once() is None


def test_new_rollout_file_can_produce_latest_response(tmp_path):
    sessions = tmp_path / "sessions"; sessions.mkdir()
    monitor = CodexMonitor(sessions, lambda _: None, lambda _: None); monitor._establish_baseline()
    rollout = sessions / "new.jsonl"; _write_complete_turn(rollout, "conversation-new", "turn-new", "new file")
    response = monitor._poll_once()
    assert response is not None and response.response_id.conversation_id == "conversation-new"


def test_partial_completion_line_waits_for_newline(tmp_path):
    rollout = tmp_path / "sessions" / "rollout.jsonl"; rollout.parent.mkdir(); rollout.write_bytes(session_meta())
    monitor = CodexMonitor(rollout.parent, lambda _: None, lambda _: None); monitor._establish_baseline()
    completion = turn_complete("turn-partial")
    with rollout.open("ab") as handle:
        handle.write(turn_started("turn-partial")); handle.write(assistant_message("partial answer")); handle.write(completion[:-1])
    assert monitor._poll_once() is None
    with rollout.open("ab") as handle: handle.write(b"\n")
    assert monitor._poll_once() is not None
    assert monitor._poll_once() is None


def test_oversized_unrelated_record_does_not_lose_next_turn(tmp_path):
    rollout = tmp_path / "sessions" / "rollout.jsonl"; rollout.parent.mkdir(); rollout.write_bytes(session_meta())
    monitor = CodexMonitor(rollout.parent, lambda _: None, lambda _: None); monitor._establish_baseline()
    oversized = b'{"type":"future_blob","payload":"' + b"x" * MAX_JSONL_LINE_BYTES + b'"}\n'
    with rollout.open("ab") as handle: handle.write(oversized); handle.write(turn_records("turn-valid", "valid", completion_timestamp="2026-08-31T10:07:00Z"))
    response = monitor._poll_once()
    assert response is not None and response.response_id.turn_id == "turn-valid"


def test_same_response_identity_is_never_returned_twice(tmp_path):
    rollout = tmp_path / "sessions" / "rollout.jsonl"; rollout.parent.mkdir(); rollout.write_bytes(session_meta())
    monitor = CodexMonitor(rollout.parent, lambda _: None, lambda _: None); monitor._establish_baseline()
    _append_turn(rollout, "turn-1", "first", "2026-08-31T10:08:00Z"); assert monitor._poll_once() is not None
    _append_turn(rollout, "turn-1", "second", "2026-08-31T10:09:00Z"); assert monitor._poll_once() is None


def test_identical_text_from_different_turns_is_not_duplicate(tmp_path):
    rollout = tmp_path / "sessions" / "rollout.jsonl"; rollout.parent.mkdir(); rollout.write_bytes(session_meta())
    monitor = CodexMonitor(rollout.parent, lambda _: None, lambda _: None); monitor._establish_baseline()
    _append_turn(rollout, "turn-a", "same", "2026-08-31T10:08:00Z"); first = monitor._poll_once()
    _append_turn(rollout, "turn-b", "same", "2026-08-31T10:09:00Z"); second = monitor._poll_once()
    assert first is not None and second is not None and first.text == second.text


def test_start_baselines_then_delivers_next_response(tmp_path):
    rollout = tmp_path / "sessions" / "rollout.jsonl"; _write_complete_turn(rollout, "conversation-1", "turn-1", "existing")
    delivered = []; delivery = threading.Event(); running = threading.Event()
    monitor = CodexMonitor(rollout.parent, lambda response: (delivered.append(response), delivery.set()), lambda status: running.set() if status is CodexMonitorStatus.RUNNING else None, poll_interval_seconds=0.01)
    monitor.start()
    try:
        assert running.wait(1); assert delivered == []
        _append_turn(rollout, "turn-2", "new", "2026-08-31T10:05:00Z")
        assert delivery.wait(1) and [item.text for item in delivered] == ["new"]
    finally: monitor.stop()


def test_missing_sessions_recovers_without_backlog(tmp_path):
    sessions = tmp_path / "sessions"; statuses = []; delivered = []
    monitor = CodexMonitor(sessions, delivered.append, statuses.append, poll_interval_seconds=0.01); monitor.start()
    try:
        _wait_until(lambda: CodexMonitorStatus.HISTORY_MISSING in statuses)
        rollout = sessions / "rollout.jsonl"; _write_complete_turn(rollout, "conversation-1", "turn-old", "baseline")
        _wait_until(lambda: CodexMonitorStatus.RUNNING in statuses); assert delivered == []
    finally: monitor.stop()


def test_rebaseline_skips_accumulated_response(tmp_path):
    rollout = tmp_path / "sessions" / "rollout.jsonl"; rollout.parent.mkdir(); rollout.write_bytes(session_meta())
    running = threading.Event(); delivered = []
    monitor = CodexMonitor(rollout.parent, delivered.append, lambda status: running.set() if status is CodexMonitorStatus.RUNNING else None, poll_interval_seconds=60)
    monitor.start()
    try:
        assert running.wait(1); _append_turn(rollout, "missed", "missed", "2026-08-31T10:06:00Z"); monitor.rebaseline()
        _wait_until(lambda: monitor._cursors[rollout].offset == rollout.stat().st_size); assert delivered == []
    finally: monitor.stop()


def test_unsupported_shape_reports_once(tmp_path):
    rollout = tmp_path / "sessions" / "rollout.jsonl"; rollout.parent.mkdir(); rollout.write_bytes(rollout_line("2026-08-31T10:00:00Z", "session_meta", {"cwd": "C:/work"}))
    statuses = []; monitor = CodexMonitor(rollout.parent, lambda _: None, statuses.append, poll_interval_seconds=0.01); monitor.start()
    try:
        _wait_until(lambda: CodexMonitorStatus.UNSUPPORTED_FORMAT in statuses); monitor._wake.set(); time.sleep(0.03)
        assert statuses.count(CodexMonitorStatus.UNSUPPORTED_FORMAT) == 1
    finally: monitor.stop()


class _TrackingFile:
    def __init__(self, raw, seeks):
        self._raw = raw; self._seeks = seeks
    def __enter__(self): self._raw.__enter__(); return self
    def __exit__(self, exc_type, exc, tb): return self._raw.__exit__(exc_type, exc, tb)
    def seek(self, offset, whence=0): self._seeks.append((offset, whence)); return self._raw.seek(offset, whence)
    def __getattr__(self, name): return getattr(self._raw, name)


def test_incremental_poll_seeks_to_baseline_offset_not_file_start(tmp_path, monkeypatch):
    rollout = tmp_path / "sessions" / "rollout.jsonl"; _write_complete_turn(rollout, "conversation-1", "turn-1", "existing")
    monitor = CodexMonitor(rollout.parent, lambda _: None, lambda _: None); monitor._establish_baseline()
    baseline_offset = monitor._cursors[rollout].offset; seeks = []
    monkeypatch.setattr(monitor, "_open_binary", lambda path: _TrackingFile(path.open("rb"), seeks))
    _append_turn(rollout, "turn-2", "new", "2026-08-31T10:10:00Z")
    assert monitor._poll_once() is not None
    assert (baseline_offset, 0) in seeks and (0, 0) not in seeks
    assert monitor._poll_once() is None


def test_stop_invalidates_in_flight_delivery(tmp_path, monkeypatch):
    sessions = tmp_path / "sessions"; sessions.mkdir(); entered = threading.Event(); release = threading.Event(); delivered = []
    monitor = CodexMonitor(sessions, delivered.append, lambda _: None, poll_interval_seconds=0.01)
    original = monitor._poll_once
    def blocked_poll():
        entered.set(); release.wait(1); return original()
    monkeypatch.setattr(monitor, "_poll_once", blocked_poll)
    monitor.start(); assert entered.wait(1); before = monitor._lifecycle_generation
    stopper = threading.Thread(target=monitor.stop); stopper.start(); _wait_until(lambda: monitor._lifecycle_generation > before); release.set(); stopper.join(1)
    assert delivered == []


def test_permission_error_recovers_with_status(tmp_path, monkeypatch):
    sessions = tmp_path / "sessions"; sessions.mkdir(); statuses = []
    monitor = CodexMonitor(sessions, lambda _: None, statuses.append, poll_interval_seconds=0.01)
    original = monitor._paths; calls = 0
    def flaky_paths():
        nonlocal calls
        calls += 1
        if calls == 1: raise PermissionError("synthetic")
        return original()
    monkeypatch.setattr(monitor, "_paths", flaky_paths); monitor.start()
    try:
        _wait_until(lambda: CodexMonitorStatus.TEMPORARILY_UNAVAILABLE in statuses)
        _wait_until(lambda: CodexMonitorStatus.RUNNING in statuses)
    finally: monitor.stop()
