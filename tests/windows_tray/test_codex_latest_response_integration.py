import time
from pathlib import Path

import pytest

from piper.windows_tray.codex_monitor import CodexMonitor, CodexMonitorStatus
from piper.windows_tray.commands import Command, CommandKind
from piper.windows_tray.controller import Controller, PlaybackState
from piper.windows_tray.settings import TraySettings
from piper.windows_tray.speech import SpeechPurpose
from tests.windows_tray.codex_test_data import session_meta, turn_records


class FakeSpeechWorker:
    def __init__(self) -> None:
        self.submitted = []
        self.cancelled = []
        self.cancel_codex_calls = 0
        self.auxiliary_cancel_calls = 0

    def submit(self, request) -> bool:
        self.submitted.append(request)
        return True

    def cancel_active(self, generation: int) -> None:
        self.cancelled.append(generation)

    def cancel_codex(self) -> None:
        self.cancel_codex_calls += 1

    def cancel_auxiliary(self) -> None:
        self.auxiliary_cancel_calls += 1


def _write_complete_turn(
    path: Path,
    conversation_id: str,
    turn_id: str,
    text: str,
    completion_timestamp: str = "2026-08-31T10:01:03Z",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        session_meta(conversation_id)
        + turn_records(
            turn_id,
            text,
            completion_timestamp=completion_timestamp,
        )
    )


def _append_turn(
    path: Path,
    turn_id: str,
    text: str,
    completion_timestamp: str,
) -> None:
    with path.open("ab") as handle:
        handle.write(
            turn_records(
                turn_id,
                text,
                completion_timestamp=completion_timestamp,
            )
        )


def _pump_until(controller: Controller, predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        command = controller.drain_once()
        if command is not None:
            controller.handle(command)
        if predicate():
            return
        time.sleep(0.01)
    pytest.fail("condition was not reached before timeout")


def _drain_all(controller: Controller) -> None:
    while True:
        command = controller.drain_once()
        if command is None:
            return
        controller.handle(command)


def _start_monitor(
    sessions: Path,
    controller: Controller,
) -> tuple[CodexMonitor, list[CodexMonitorStatus]]:
    statuses = []

    def on_status(status: CodexMonitorStatus) -> None:
        statuses.append(status)
        controller.enqueue_codex_status(status)

    monitor = CodexMonitor(
        sessions,
        controller.enqueue_codex_response,
        on_status,
        poll_interval_seconds=0.01,
    )
    controller.configure_runtime(codex_monitor=monitor)
    assert controller.start_configured_codex_monitoring() is True
    _pump_until(controller, lambda: CodexMonitorStatus.RUNNING in statuses)
    return monitor, statuses


def test_enabled_runtime_skips_baseline_and_speaks_next_final_answer(
    tmp_path: Path,
) -> None:
    sessions = tmp_path / "sessions"
    rollout = sessions / "2026" / "08" / "31" / "rollout.jsonl"
    _write_complete_turn(rollout, "conversation-1", "turn-old", "old answer")

    worker = FakeSpeechWorker()
    controller = Controller(
        settings=TraySettings(codex_enabled=True),
        speech_worker=worker,
    )
    monitor, _statuses = _start_monitor(sessions, controller)
    try:
        assert not [r for r in worker.submitted if r.purpose is SpeechPurpose.CODEX]

        _append_turn(
            rollout,
            "turn-new",
            "new answer",
            "2026-08-31T11:00:00Z",
        )
        _pump_until(
            controller,
            lambda: any(r.purpose is SpeechPurpose.CODEX for r in worker.submitted),
        )

        codex_requests = [r for r in worker.submitted if r.purpose is SpeechPurpose.CODEX]
        assert [r.text for r in codex_requests] == ["new answer"]
    finally:
        monitor.stop()


def test_multiple_new_turns_discovered_together_speak_only_latest(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    rollout = sessions / "rollout.jsonl"
    _write_complete_turn(rollout, "conversation-1", "turn-old", "old")
    worker = FakeSpeechWorker()
    controller = Controller(
        settings=TraySettings(codex_enabled=True),
        speech_worker=worker,
    )
    monitor, _statuses = _start_monitor(sessions, controller)
    try:
        with rollout.open("ab") as handle:
            handle.write(
                turn_records(
                    "turn-1",
                    "first",
                    completion_timestamp="2026-08-31T11:00:00Z",
                )
            )
            handle.write(
                turn_records(
                    "turn-2",
                    "second",
                    completion_timestamp="2026-08-31T11:00:01Z",
                )
            )
            handle.write(
                turn_records(
                    "turn-3",
                    "third",
                    completion_timestamp="2026-08-31T11:00:02Z",
                )
            )

        _pump_until(
            controller,
            lambda: any(r.purpose is SpeechPurpose.CODEX for r in worker.submitted),
        )
        codex_requests = [r for r in worker.submitted if r.purpose is SpeechPurpose.CODEX]
        assert [r.text for r in codex_requests] == ["third"]
    finally:
        monitor.stop()


def test_codex_arriving_during_foreground_is_skipped_without_later_backlog(
    tmp_path: Path,
) -> None:
    sessions = tmp_path / "sessions"
    rollout = sessions / "rollout.jsonl"
    _write_complete_turn(rollout, "conversation-1", "turn-old", "old")
    worker = FakeSpeechWorker()
    controller = Controller(
        settings=TraySettings(codex_enabled=True),
        speech_worker=worker,
    )
    monitor, _statuses = _start_monitor(sessions, controller)
    try:
        controller.state.playback = PlaybackState.SPEAKING
        controller.state.speech_generation = 40
        _append_turn(
            rollout,
            "turn-blocked",
            "must be skipped",
            "2026-08-31T11:10:00Z",
        )
        _pump_until(
            controller,
            lambda: monitor._seen,
        )
        _drain_all(controller)

        controller.state.playback = PlaybackState.IDLE
        time.sleep(0.05)
        _drain_all(controller)

        assert not [r for r in worker.submitted if r.purpose is SpeechPurpose.CODEX]
    finally:
        monitor.stop()


def test_preparation_policy_is_applied_before_codex_speech_request() -> None:
    worker = FakeSpeechWorker()
    controller = Controller(
        settings=TraySettings(codex_enabled=True),
        speech_worker=worker,
    )
    body = "Intro\n```python\nprint('not spoken')\n```\n" + ("x" * 6_100)

    from datetime import datetime, timezone
    from piper.windows_tray.codex_history import CodexCompletedResponse, CodexResponseId

    response = CodexCompletedResponse(
        CodexResponseId("conversation-1", "turn-1"),
        datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc),
        body,
    )
    controller.enqueue_codex_response(response)
    _pump_until(controller, lambda: bool(worker.submitted))

    request = worker.submitted[-1]
    assert request.purpose is SpeechPurpose.CODEX
    assert "print('not spoken')" not in request.text
    assert len(request.text) <= 6_000


def test_restart_with_enabled_setting_baselines_offline_response(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    rollout = sessions / "rollout.jsonl"
    _write_complete_turn(
        rollout,
        "conversation-1",
        "turn-completed-while-offline",
        "offline answer",
    )
    worker = FakeSpeechWorker()
    controller = Controller(
        settings=TraySettings(codex_enabled=True),
        speech_worker=worker,
    )
    monitor, _statuses = _start_monitor(sessions, controller)
    try:
        time.sleep(0.05)
        while True:
            command = controller.drain_once()
            if command is None:
                break
            controller.handle(command)
        assert not [r for r in worker.submitted if r.purpose is SpeechPurpose.CODEX]
    finally:
        monitor.stop()
